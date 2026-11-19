"""일일브리핑 자료 서비스. 헤드라인은 표준 라이브러리만 사용합니다."""
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import re
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit, urlencode
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))
HEADLINE_URL = "https://www.yna.co.kr/report/headline"
VERSION = "DAILY-YNA-SCRAPMASTER-20261113"


class _Node:
    def __init__(self, tag="", attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def find_all(self, predicate):
        for child in self.children:
            if isinstance(child, _Node):
                if predicate(child):
                    yield child
                yield from child.find_all(predicate)

    def text(self):
        def flatten(node):
            if isinstance(node, str):
                return node
            if node.tag in {"script", "style", "figure", "aside", "noscript"}:
                return ""
            if node.tag == "br":
                return "\n"
            return "".join(flatten(child) for child in node.children)
        return "\n".join(re.sub(r"[\t\r \u00a0]+", " ", line).strip()
                         for line in flatten(self).splitlines()).strip()


class _Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        # HTML permits omitted closing paragraph/list tags.
        if tag in {"p", "li"}:
            for i in range(len(self.stack)-1, 0, -1):
                if self.stack[i].tag == tag:
                    self.stack = self.stack[:i]
                    break
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def _get_html(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9", "Accept": "text/html"})
    try:
        with urlopen(request, timeout=25) as response:
            final = urlsplit(response.geturl())
            if final.hostname not in {"www.yna.co.kr", "yna.co.kr"}:
                raise RuntimeError("연합뉴스 기사 페이지 대신 다른 사이트로 이동했습니다.")
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise RuntimeError("연합뉴스 응답 크기가 예상 범위를 초과했습니다.")
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset)
    except HTTPError as exc:
        raise RuntimeError(f"연합뉴스 접속 실패(HTTP {exc.code}). 서버의 접속 허용 여부를 확인해 주세요.") from exc
    except (URLError, TimeoutError, UnicodeError) as exc:
        raise RuntimeError("연합뉴스 응답을 읽지 못했습니다. 잠시 후 다시 수집해 주세요.") from exc


def _date(value):
    if isinstance(value, datetime):
        return value.astimezone(KST).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).replace("/", "-"))


def _canonical_article(href, base=HEADLINE_URL):
    parts = urlsplit(urljoin(base, href or ""))
    if parts.scheme != "https" or parts.hostname not in {"www.yna.co.kr", "yna.co.kr"}:
        return None
    if not re.fullmatch(r"/view/AKR\d+/?", parts.path):
        return None
    return urlunsplit(("https", "www.yna.co.kr", parts.path.rstrip("/"), "", ""))


def _is_roundup_title(text):
    return "연합뉴스 이 시각 헤드라인" in text and bool(re.search(r"07\s*:\s*30(?!\d)", text))


def _candidate_urls(html, day):
    tree = _Tree(html).root
    result = []
    for node in tree.find_all(lambda n: n.tag == "a" and "href" in n.attrs):
        url = _canonical_article(node.attrs["href"])
        title = node.text() + " " + (node.attrs.get("title") or "")
        if url and urlsplit(url).path.startswith("/view/AKR"+day.strftime("%Y%m%d")) and _is_roundup_title(title) and url not in result:
            result.append(url)
    return result


def _article_text(html, day):
    root = _Tree(html).root
    meta = {n.attrs.get("property", n.attrs.get("name", "")).lower(): n.attrs.get("content", "")
            for n in root.find_all(lambda n: n.tag == "meta")}
    title = meta.get("og:title") or " ".join(n.text() for n in root.find_all(lambda n: n.tag == "h1"))
    if not _is_roundup_title(title):
        raise RuntimeError("연합뉴스 07:30 헤드라인 묶음 기사가 아닙니다.")
    published = meta.get("article:published_time", "")
    try:
        when = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("기사의 최초 게시시각을 확인하지 못했습니다.") from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=KST)
    when = when.astimezone(KST)
    if when.date() != day or (when.hour, when.minute) != (7, 30):
        raise RuntimeError("선택한 날짜의 오전 07:30 게시물이 아닙니다.")
    bodies = list(root.find_all(lambda n: "story-news" in (n.attrs.get("class") or "").split() and "article" in (n.attrs.get("class") or "").split()))
    if not bodies:
        raise RuntimeError("기사 본문 영역을 찾지 못했습니다. 연합뉴스 페이지 구조를 확인해 주세요.")
    lines = []
    for paragraph in bodies[0].find_all(lambda n: n.tag == "p"):
        if "txt-copyright" in (paragraph.attrs.get("class") or "").split():
            break
        ancestor = paragraph.parent
        if _ignored_ancestor(ancestor, bodies[0]):
            continue
        text = paragraph.text()
        if not text:
            continue
        if re.match(r"전문\s*보기\s*[:：]", text):
            urls = [_canonical_article(n.attrs.get("href")) for n in paragraph.find_all(lambda n: n.tag == "a")]
            urls = [url for url in urls if url]
            if urls:
                text = "전문보기: " + urls[0]
        lines.append(text)
    # No fixed count: preserve every item in this particular 07:30 roundup.
    if not any(line.startswith("■") for line in lines):
        raise RuntimeError("07:30 헤드라인 기사 항목을 본문에서 찾지 못했습니다.")
    return "\n\n".join(lines)


def _ignored_ancestor(node, body):
    while node is not None and node is not body:
        if node.tag in {"figure", "aside", "script", "style", "noscript"}:
            return True
        node = node.parent
    return False


def fetch_headlines(report_date):
    """선택일 07:30 묶음 기사의 원문 본문과 검증된 출처 URL을 반환합니다."""
    day = _date(report_date)
    urls = _candidate_urls(_get_html(HEADLINE_URL), day)
    if not urls:
        raise RuntimeError(f"{day:%Y-%m-%d} 07:30 헤드라인이 현재 목록에 없습니다. 게시 전이거나 목록에서 지난 날짜일 수 있습니다.")
    failures = []
    for url in urls[:5]:
        try:
            return _article_text(_get_html(url), day), url
        except RuntimeError as exc:
            failures.append(str(exc))
    raise RuntimeError(failures[0])


SCRAPMASTER_ORIGIN = "https://dnai.scrapmaster.co.kr"
SCRAPMASTER_PAGE = SCRAPMASTER_ORIGIN + "/dnai/DNA_wordcloud.jsp?sm3ID=gbpr5v-0"


def _keyword_json(national, day):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": SCRAPMASTER_PAGE,
        "Origin": SCRAPMASTER_ORIGIN,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
    if national:
        path = "/dnai/utils/total_word_score/word_score.jsp"
        request = Request(SCRAPMASTER_ORIGIN + path, headers=headers)
    else:
        path = "/dnai/utils/total_word_score/word_score_by_today_setting.jsp"
        form = {"user_seq": "981", "start_date": day.isoformat(),
                "end_date": day.isoformat(), "pair_type": "1", "removeChecked": "false"}
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        request = Request(SCRAPMASTER_ORIGIN + path, data=urlencode(form).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=40) as response:
            if urlsplit(response.geturl()).hostname != "dnai.scrapmaster.co.kr":
                raise RuntimeError("스크랩마스터 자료 주소가 다른 사이트로 이동했습니다.")
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise RuntimeError("스크랩마스터 응답 크기가 예상 범위를 초과했습니다.")
            text = raw.decode(response.headers.get_content_charset() or "utf-8-sig")
    except HTTPError as exc:
        raise RuntimeError(f"스크랩마스터 접속 실패(HTTP {exc.code}). 웹 서버의 접속 권한을 확인해 주세요.") from exc
    except (URLError, TimeoutError, UnicodeError) as exc:
        raise RuntimeError("스크랩마스터 응답을 읽지 못했습니다. 잠시 후 다시 수집해 주세요.") from exc
    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("스크랩마스터가 키워드 JSON 대신 다른 화면을 반환했습니다. 로그인 또는 서버 접근 권한을 확인해 주세요.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("스크랩마스터 키워드 응답 형식이 달라졌습니다.")
    return payload


def _keyword_pairs(payload, national=False):
    key = "today_1_word_score_pair" if national else "period_member_word_score_pair"
    rows = payload.get(key)
    if not isinstance(rows, (list, dict)) or not rows:
        raise RuntimeError("해당 날짜의 키워드가 없거나 스크랩마스터 응답에 " + key + " 항목이 없습니다.")
    if isinstance(rows, dict):
        rows = list(rows.values())
    pairs = []
    for row in rows:
        if isinstance(row, dict):
            if all(str(k).isdigit() for k in row):
                row = [row[k] for k in sorted(row, key=lambda k: int(k))]
            else:
                word = next((row[k] for k in ("word", "keyword", "word_name") if k in row), None)
                score = next((row[k] for k in ("score", "count", "weight", "word_score") if k in row), None)
                row = [word, score] if national else [None, word, score]
        if not isinstance(row, (list, tuple)) or len(row) < (2 if national else 3):
            continue
        word, raw_score = (row[0], row[1]) if national else (row[1], row[2])
        if not isinstance(word, str) or isinstance(raw_score, bool):
            continue
        word = re.sub(r"\s+", " ", word).strip()
        try:
            score = float(str(raw_score).replace(",", ""))
        except (ValueError, TypeError):
            continue
        if word and math.isfinite(score) and score > 0:
            pairs.append({"word": word, "score": score})
    if not pairs:
        raise RuntimeError("스크랩마스터 응답에서 유효한 키워드와 양수 점수를 추출하지 못했습니다.")
    return pairs


def fetch_keywords(report_date, national=False):
    """원본 연결 프로그램과 동일한 자료를 웹 서버에서 직접 수집합니다."""
    day = _date(report_date)
    if national and day != datetime.now(KST).date():
        raise RuntimeError("신문 1면 단어쌍은 오늘 자료만 제공됩니다. 과거 날짜 자료로 표시하지 않습니다.")
    payload = _keyword_json(national, day)
    return _keyword_pairs(payload, national=national)


def error_message(exc):
    return str(exc)
