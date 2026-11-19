"""한전 자동보고서용 수치 수집 — 파워셸 수집 스크립트를 파이썬(requests)으로 옮긴 것.

각 함수는 {'ok': True, ...} 또는 {'ok': False, 'reason': '...'} 를 돌려줍니다.
(예외를 밖으로 던지지 않으므로, 한 항목이 실패해도 나머지는 계속 진행됩니다.)
"""
import html as htmllib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import requests

KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
NUM = r"\d[\d,]*(?:\.\d+)?"


def now_kst():
    return datetime.now(KST)


def _get(url, **kw):
    headers = {"User-Agent": UA}
    headers.update(kw.pop("headers", {}))
    r = requests.get(url, headers=headers, timeout=kw.pop("timeout", 20), **kw)
    r.raise_for_status()
    return r


def _fail(e):
    return {"ok": False, "reason": "%s: %s" % (type(e).__name__, e)}


def _direction(signed):
    return "up" if signed > 0 else ("down" if signed < 0 else "flat")


def _trend_direction(trend_name, signed):
    n = str(trend_name or "").upper()
    if n in ("RISING", "UPPER_LIMIT"):
        return "up"
    if n in ("FALLING", "LOWER_LIMIT"):
        return "down"
    if n in ("UNCHANGED", "STEADY"):
        return "flat"
    return _direction(signed)


def _to_float(text):
    return float(str(text).replace(",", "").replace("+", ""))


# ---------------- 환율 (네이버 USD/KRW) ----------------
def read_fx():
    url = "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"
    try:
        data = _get(url, headers={"Accept": "application/json",
                                  "Referer": "https://stock.naver.com/"}).json()
        fx = data["exchangeInfo"]
        if fx.get("reutersCode") != "FX_USDKRW" or fx.get("symbolCode") != "USD":
            raise ValueError("네이버 USD/KRW 응답 항목 검증 실패")
        price_text = str(fx["closePrice"])
        change_text = str(fx["fluctuations"])
        price = _to_float(price_text)
        signed = _to_float(change_text)
        if not 100 <= price <= 10000:
            raise ValueError("USD/KRW 환율 범위 확인 필요")
        trend = (fx.get("fluctuationsType") or {}).get("name")
        direction = _trend_direction(trend, signed)
        return {"ok": True, "key": "fx", "label": "미국 달러 환율", "price": price,
                "priceText": price_text, "changeText": change_text.lstrip("+-"),
                "direction": direction, "source": url,
                "sourceTime": str(fx.get("localTradedAt", ""))}
    except Exception as e:
        return _fail(e)


# ---------------- 미국 한국전력 (구글 파이낸스 KEP:NYSE) ----------------
def read_us():
    url = "https://www.google.com/finance/quote/KEP:NYSE?hl=en"
    try:
        raw = _get(url, headers={"Accept": "text/html",
                                 "Accept-Language": "en-US,en;q=0.9"}, timeout=25).text
        text = re.sub(r"(?is)<head\b[^>]*>.*?</head>", " ", raw)
        text = re.sub(r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", "\n", text)
        text = htmllib.unescape(text).replace("−", "-")
        text = re.sub(r"\s+", " ", text).strip()
        if not re.search(r"KEP\s*:\s*NYSE", text):
            raise ValueError("구글 응답에서 KEP:NYSE 종목을 확인하지 못했습니다 (차단/동의 화면일 수 있음)")
        heading = re.search(r"Korea\s+Electric\s+Power\s+Corp(?:oration)?\b", text)
        if not heading:
            raise ValueError("구글 응답에서 한국전력 회사명을 확인하지 못했습니다")
        block = text[heading.end():heading.end() + 2000]
        pm = re.match(r"\s*\$\s*(?P<price>\d[\d,]*(?:\.\d+)?)", block)
        if not pm:
            raise ValueError("회사명 바로 다음의 정규장 가격을 구분하지 못했습니다")
        tail = block[pm.end():]
        boundary = re.search(r"\$|After\s*hours|Pre[- ]?market|Closed:|Open:|area_chart", tail)
        if boundary:
            tail = tail[:boundary.start()]
        tail = tail[:240]
        cm = re.search(r"(?P<sign>[+-]?)(?P<percent>\d+(?:\.\d+)?)\s*%", tail)
        if not cm:
            raise ValueError("정규장 가격의 등락률을 찾지 못했습니다")
        sign = cm.group("sign")
        arrow = re.search(r"arrow_(upward|downward)", tail)
        absolute = re.search(r"\(\s*(?P<sign>[+-])\s*\d", tail)
        if not sign and arrow:
            sign = "-" if arrow.group(0) == "arrow_downward" else "+"
        if not sign and absolute:
            sign = absolute.group("sign")
        price = _to_float(pm.group("price"))
        percent = _to_float(cm.group("percent"))
        if not sign and percent != 0:
            raise ValueError("미국 주가 등락 방향을 확인하지 못했습니다")
        if price <= 0 or price > 10000 or percent > 1000:
            raise ValueError("미국 주가 숫자 범위 확인 필요")
        direction = "flat" if percent == 0 else ("down" if sign == "-" else "up")
        return {"ok": True, "key": "us", "label": "한국전력 미국(KEP)", "price": price,
                "priceText": pm.group("price"), "changeText": cm.group("percent"),
                "direction": direction, "source": url}
    except Exception as e:
        return _fail(e)


# ---------------- 국내 한국전력 (네이버 증권) ----------------
def read_domestic():
    url = "https://m.stock.naver.com/api/stock/015760/basic"
    try:
        d = _get(url, headers={"Accept": "application/json",
                               "Referer": "https://m.stock.naver.com/"}).json()
        if "한국전력" not in str(d.get("stockName", "")):
            raise ValueError("한국전력 종목 확인 실패")
        price_text = str(d["closePrice"])
        change_raw = str(d["compareToPreviousClosePrice"])
        price = _to_float(price_text)
        signed = _to_float(change_raw)
        trend = (d.get("compareToPreviousPrice") or {}).get("name")
        direction = _trend_direction(trend, signed)
        if not 100 <= price <= 10000000:
            raise ValueError("국내 주가 범위 확인 필요")
        return {"ok": True, "key": "domestic", "label": "한국전력 국내", "price": price,
                "priceText": price_text, "changeText": change_raw.lstrip("+-"),
                "direction": direction, "source": url,
                "sourceTime": str(d.get("localTradedAt", ""))}
    except Exception as e:
        return _fail(e)


# ---------------- 코스피 / 코스닥 지수 ----------------
def read_index(code):
    """code: 'KOSPI' | 'KOSDAQ'"""
    url = "https://m.stock.naver.com/api/index/%s/basic" % code
    try:
        d = _get(url, headers={"Accept": "application/json",
                               "Referer": "https://m.stock.naver.com/"}).json()
        price_text = str(d["closePrice"])
        change_raw = str(d["compareToPreviousClosePrice"])
        ratio_raw = str(d["fluctuationsRatio"])
        signed = _to_float(change_raw)
        trend = (d.get("compareToPreviousPrice") or {}).get("name")
        direction = _trend_direction(trend, signed)
        return {"ok": True, "key": code.lower(), "label": "한국 " + ("코스피" if code == "KOSPI" else "코스닥"),
                "price": _to_float(price_text), "priceText": price_text,
                "changeText": change_raw.lstrip("+-"),
                "ratioText": ratio_raw.lstrip("+-"), "direction": direction, "source": url}
    except Exception as e:
        return _fail(e)


# ---------------- SMP (전력거래소, 육지 가중평균) ----------------
def _plain(html_text):
    s = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", html_text)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def read_smp(report_date):
    url = "https://kpx.or.kr/smpInland.es?mid=a30301000000"
    try:
        r = _get(url, timeout=25)
        r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
        raw = r.text
        plain = _plain(raw)
        if "육지" not in plain or not re.search(r"원\s*/\s*kWh", plain):
            raise ValueError("육지 SMP 페이지 및 단위 확인 실패")
        am = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*거래분", plain)
        if not am:
            raise ValueError("SMP 거래분 날짜를 찾지 못했습니다")
        anchor = datetime(int(am.group(1)), int(am.group(2)), int(am.group(3))).date()
        candidates = []
        for table in re.finditer(r"(?is)<table\b[^>]*>.*?</table>", raw):
            rows = []
            for tr in re.finditer(r"(?is)<tr\b[^>]*>(.*?)</tr>", table.group(0)):
                cells = [_plain(c.group(1)) for c in
                         re.finditer(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", tr.group(1))]
                if cells:
                    rows.append(cells)
            weighted = [r_ for r_ in rows
                        if re.match(r"^가중평균(?:SMP)?$", re.sub(r"\s", "", r_[0]))]
            if len(weighted) != 1:
                continue
            values = weighted[0]
            for row in rows:
                if len(row) != len(values):
                    continue
                if not re.match(r"^(구분|날짜|일자|시간)$", re.sub(r"\s", "", row[0])):
                    continue
                for i in range(1, len(row)):
                    dm = re.match(r"^\s*(\d{1,2})\s*[./]\s*(\d{1,2})\s*(?:\([가-힣]\))?\s*$", row[i])
                    if not dm:
                        continue
                    year, month, day = anchor.year, int(dm.group(1)), int(dm.group(2))
                    if month > anchor.month + 6:
                        year -= 1
                    elif month < anchor.month - 6:
                        year += 1
                    try:
                        day_date = datetime(year, month, day).date()
                    except ValueError:
                        continue
                    number = values[i].replace(",", "")
                    if (day_date > report_date or day_date < report_date - timedelta(days=7)
                            or not re.match(r"^\d+(?:\.\d+)?$", number)):
                        continue
                    price = Decimal(number)
                    if price <= 0 or price > 10000:
                        continue
                    candidates.append((day_date, price))
        if not candidates:
            raise ValueError("SMP 날짜 열과 가중평균 값을 연결하지 못했습니다")
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_date = candidates[0][0]
        same = {p for d_, p in candidates if d_ == best_date}
        if len(same) != 1:
            raise ValueError("같은 날짜의 육지 SMP 값이 여러 개입니다")
        price = candidates[0][1]
        return {"ok": True, "key": "smp", "label": "SMP(육지 가중평균)",
                "price": float(price),
                "priceText": format(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
                "unit": "원/kWh", "sourceDate": best_date.isoformat(), "source": url}
    except Exception as e:
        return _fail(e)


# ---------------- 두바이유 선물 (네이버 DCBc1) ----------------
def read_dubai(report_date):
    url = "https://api.stock.naver.com/marketindex/energy/DCBc1"
    try:
        data = _get(url, headers={"Accept": "application/json",
                                  "Referer": "https://stock.naver.com/"}).json()
        options = [data.get("energyInfo"), data.get("marketIndexInfo"), data.get("result"), data] \
            if isinstance(data, dict) else []
        valid = [o for o in options if isinstance(o, dict) and o.get("reutersCode") == "DCBc1"
                 and re.search(r"두바이|Dubai", str(o.get("name", ""))) and o.get("closePrice")]
        if len(valid) != 1:
            raise ValueError("네이버 두바이유 DCBc1 항목을 유일하게 확인하지 못했습니다")
        q = valid[0]
        if not re.search(r"Futures|선물", str(q.get("nameEng", "")) + " " + str(q.get("description", ""))):
            raise ValueError("두바이유 선물 상품인지 확인하지 못했습니다")
        if not re.match(r"^USD\s*/\s*(?:BBL|barrel)$", str(q.get("unit", "")), re.I):
            raise ValueError("두바이유 달러/배럴 단위 검증 실패")
        text = str(q["closePrice"]).replace(",", "")
        if not re.match(r"^\d+(?:\.\d+)?$", text):
            raise ValueError("두바이유 가격 형식 검증 실패")
        price = Decimal(text)
        traded = datetime.fromisoformat(str(q["localTradedAt"]).replace("Z", "+00:00"))
        if traded.tzinfo is None:
            traded = traded.replace(tzinfo=KST)
        traded_kst = traded.astimezone(KST)
        if (price <= 0 or price > 1000 or traded > datetime.now(timezone.utc) + timedelta(minutes=2)
                or traded_kst.date() < report_date - timedelta(days=10)):
            raise ValueError("두바이유 가격 또는 실제 시세 기준 시각 확인 필요")
        return {"ok": True, "key": "dubai", "label": "두바이유(Dubai 선물)",
                "price": float(price),
                "priceText": format(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
                "unit": "USD/bbl", "sourceDate": traded_kst.date().isoformat(),
                "sourceTime": str(q["localTradedAt"]), "source": url}
    except Exception as e:
        return _fail(e)


def collect_all(report_date=None):
    report_date = report_date or now_kst().date()
    return {
        "domestic": read_domestic(),
        "us": read_us(),
        "fx": read_fx(),
        "kospi": read_index("KOSPI"),
        "kosdaq": read_index("KOSDAQ"),
        "smp": read_smp(report_date),
        "dubai": read_dubai(report_date),
    }
