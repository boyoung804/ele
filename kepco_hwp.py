"""한전 자동보고서(V6) 한글 양식 채우기 — 파워셸 WriteReport.ps1을 파이썬으로 옮긴 것.

template.hwp(압축 HWP5) 안의 본문 레코드를 찾아 값만 바꿉니다.
"""
import hashlib
import io
import struct
import zlib
from decimal import Decimal, ROUND_HALF_UP

from kepco_cfb import CFB

TEMPLATE_SHA256 = "C2481EE84DAC674555290B2944147BF62F1CA0357ED4B931A949062F87150106"

# 양식에 들어 있는 연평균 기준값 (원본 프로그램과 동일)
BASELINE = {
    "smp": {"2025": Decimal("112.73"), "2024": Decimal("128.33")},
    "dubai": {"2025": Decimal("69.36"), "2024": Decimal("79.58")},
}


# ---------------- 압축 / 레코드 ----------------
def expand(b):
    return zlib.decompress(b, -15)


def compress(b):
    c = zlib.compressobj(6, zlib.DEFLATED, -15)
    return c.compress(b) + c.flush()


class Rec:
    __slots__ = ("tag", "level", "data")

    def __init__(self, tag, level, data):
        self.tag, self.level, self.data = tag, level, bytearray(data)


def parse_records(b):
    recs, pos = [], 0
    while pos < len(b):
        if pos + 4 > len(b):
            raise ValueError("한글 레코드 헤더 손상")
        h = struct.unpack_from("<I", b, pos)[0]
        pos += 4
        size = h >> 20
        if size == 4095:
            size = struct.unpack_from("<I", b, pos)[0]
            pos += 4
        if pos + size > len(b):
            raise ValueError("한글 레코드 길이 오류")
        recs.append(Rec(h & 1023, (h >> 10) & 1023, b[pos:pos + size]))
        pos += size
    return recs


def join_records(recs):
    out = bytearray()
    for r in recs:
        size = len(r.data)
        h = r.tag | (r.level << 10)
        if size >= 4095:
            h |= 0xFFF00000
            out += struct.pack("<II", h, size)
        else:
            h |= size << 20
            out += struct.pack("<I", h)
        out += r.data
    return bytes(out)


def set_text(recs, old, new, shape=-1, record_index=-1):
    matches = [
        i for i, r in enumerate(recs)
        if (record_index < 0 or i == record_index) and r.tag == 67
        and old in bytes(r.data).decode("utf-16-le", errors="ignore")
    ]
    if len(matches) != 1:
        raise ValueError("양식의 교체 대상이 유일하지 않습니다: " + old)
    i = matches[0]
    r = recs[i]
    text = bytes(r.data).decode("utf-16-le")
    if i == 0 or recs[i - 1].tag != 66 or recs[i - 1].level != r.level - 1:
        raise ValueError("문단 구조 확인 실패")
    new_text = text.replace(old, new)
    r.data = bytearray(new_text.encode("utf-16-le"))
    header = recs[i - 1].data
    count = struct.unpack_from("<I", header, 0)[0]
    flags = count & 0x80000000
    # 문자 수는 UTF-16 코드 단위 기준
    header[0:4] = struct.pack("<I", flags | (len(new_text.encode("utf-16-le")) // 2))
    j = i + 1
    while j < len(recs) and recs[j].level >= r.level:
        if recs[j].tag == 68 and recs[j].level == r.level:
            old_shape = struct.unpack_from("<I", recs[j].data, 4)[0]
            if shape >= 0:
                old_shape = shape
            recs[j].data = bytearray(8)
            struct.pack_into("<I", recs[j].data, 4, old_shape)
            struct.pack_into("<H", header, 12, 1)
        j += 1


# ---------------- 값 서식 ----------------
def format_change(q):
    sym = {"up": "▲", "down": "▼", "flat": "-"}[q["direction"]]
    return sym + q["changeText"] + ("%" if q["key"] == "us" else "")


def change_shape(q):
    return {"up": 37, "down": 6, "flat": 12}[q["direction"]]


def format_energy_change(v):
    v = Decimal(v)
    if v == 0:
        return "(-0)"
    sym = "▲" if v > 0 else "▼"
    return "(" + sym + format(abs(v).quantize(Decimal("0.01")), "f") + ")"


def energy_shape(v):
    v = Decimal(v)
    return 38 if v > 0 else (23 if v < 0 else 44)


def diff_from_baseline(key, price, year):
    d = Decimal(str(price)) - BASELINE[key][year]
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def date_label(dt):
    return "%04d.%02d.%02d(%s)조간" % (dt.year, dt.month, dt.day, WEEKDAY_KO[dt.weekday()])


def build_values(finance, energy, now):
    """수집값(dict)으로 양식에 넣을 문구 목록을 만든다.

    finance: {'domestic','us','fx'} 각각 {key, priceText, changeText, direction}
    energy : {'smp','dubai'} 각각 {price, priceText}
    now    : 보고서 생성 시각 (한국시간 datetime)
    """
    smp, dubai = energy["smp"], energy["dubai"]
    cmp = {
        "smp": {y: diff_from_baseline("smp", smp["price"], y) for y in ("2025", "2024")},
        "dubai": {y: diff_from_baseline("dubai", dubai["price"], y) for y in ("2025", "2024")},
    }
    return cmp


def fill_template(template_bytes, finance, energy, kospi_bmp, kosdaq_bmp, now, check_hash=True):
    """양식에 값을 채운 HWP 바이트를 돌려준다."""
    if check_hash and hashlib.sha256(template_bytes).hexdigest().upper() != TEMPLATE_SHA256:
        raise ValueError("기본 양식이 변경되었습니다. 제공된 template.hwp를 사용해 주세요.")

    domestic, us, fx = finance["domestic"], finance["us"], finance["fx"]
    smp, dubai = energy["smp"], energy["dubai"]
    cmp = build_values(finance, energy, now)
    cell_date = "%04d/%02d/%02d" % (now.year, now.month, now.day)
    label = date_label(now)
    reference = "(%02d:%02d 현재)" % (now.hour, now.minute)

    store = CFB.from_bytes(template_bytes)
    header = store.read("FileHeader")
    flags = struct.unpack_from("<I", header, 36)[0]
    if (flags & 1) == 0 or (flags & 2) != 0:
        raise ValueError("압축 HWP5 양식인지 확인해 주세요.")
    body = parse_records(expand(store.read("BodyText/Section0")))

    pairs = [
        ("2026.10.23(금)조간", label, -1),
        ("(Dubai)", "(Dubai 선물)", -1),
        ("28,500원", domestic["priceText"] + "원", -1),
        ("▼350", format_change(domestic), change_shape(domestic)),
        ("10.72USD", us["priceText"] + "USD", -1),
        ("▲0.0050", format_change(us), change_shape(us)),
        ("1327.30", fx["priceText"], -1),
        ("▼0.20", format_change(fx), change_shape(fx)),
        ("(7시 현재)", reference, -1),
    ]
    preview = store.read("PrvText").decode("utf-16-le")
    for old, new, shape in pairs:
        set_text(body, old, new, shape)
        preview = preview.replace(old, new)

    energy_cells = [
        (131, "2026/00/00", cell_date, -1),
        (136, "00.00", smp["priceText"], -1),
        (141, "(▲00.00)", format_energy_change(cmp["smp"]["2025"]), energy_shape(cmp["smp"]["2025"])),
        (147, "2026/00/00", cell_date, -1),
        (152, "00.00", dubai["priceText"], -1),
        (157, "(▼00.00)", format_energy_change(cmp["dubai"]["2025"]), energy_shape(cmp["dubai"]["2025"])),
        (204, "(▼15.6)", format_energy_change(cmp["smp"]["2025"]), energy_shape(cmp["smp"]["2025"])),
        (219, "(▼10.22)", format_energy_change(cmp["dubai"]["2025"]), energy_shape(cmp["dubai"]["2025"])),
        (243, "(▼38.67)", format_energy_change(cmp["smp"]["2024"]), energy_shape(cmp["smp"]["2024"])),
        (258, "(▼2.52)", format_energy_change(cmp["dubai"]["2024"]), energy_shape(cmp["dubai"]["2024"])),
    ]
    for idx, old, new, shape in energy_cells:
        set_text(body, old, new, shape, idx)
    preview = preview.replace(
        "<2026/00/00><00.00><(▲00.00)>",
        "<%s><%s><%s>" % (cell_date, smp["priceText"], format_energy_change(cmp["smp"]["2025"])))
    preview = preview.replace(
        "<2026/00/00><00.00><(▼00.00)>",
        "<%s><%s><%s>" % (cell_date, dubai["priceText"], format_energy_change(cmp["dubai"]["2025"])))
    for idx, old, new, shape in energy_cells:
        if idx in (204, 219, 243, 258):
            preview = preview.replace(old, new)

    body_bytes = join_records(body)
    store.write("BodyText/Section0", compress(body_bytes))
    store.write("PrvText", preview.encode("utf-16-le"))
    store.write("BinData/BIN0001.bmp", compress(kospi_bmp))
    store.write("BinData/BIN0002.bmp", compress(kosdaq_bmp))
    try:
        store.remove("PrvImage")
    except KeyError:
        pass
    out = store.to_bytes()

    # 저장 후 검증: 다시 열어 본문이 같은지 확인
    check = CFB.from_bytes(out)
    if expand(check.read("BodyText/Section0")) != body_bytes:
        raise ValueError("한글 저장 후 본문 검증 실패")
    return out


_SINGLE_CTRL = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


def _clean_para_text(data):
    """PARA_TEXT 레코드에서 제어 문자(표·그림 위치 등)를 빼고 글자만 남긴다."""
    chars = struct.unpack("<%dH" % (len(data) // 2), bytes(data[:len(data) // 2 * 2]))
    out, i = [], 0
    while i < len(chars):
        c = chars[i]
        if c < 32:
            if c in _SINGLE_CTRL:
                if c == 10:
                    out.append("\n")
                i += 1
            else:
                i += 8  # 확장/인라인 제어: 8글자 분량
        else:
            out.append(chr(c))
            i += 1
    return "".join(out)


def paragraph_texts(hwp_bytes):
    """HWP 본문의 문단 글자들을 순서대로 돌려준다 (화면 미리보기용)."""
    store = CFB.from_bytes(hwp_bytes)
    body = parse_records(expand(store.read("BodyText/Section0")))
    out = []
    for r in body:
        if r.tag == 67:
            t = _clean_para_text(r.data).strip()
            if t:
                out.append(t)
    return out


def to_bmp(img, width, height):
    """PIL 이미지를 흰 바탕의 width×height BMP(바이트)로 만든다 (비율 유지, 가운데 정렬)."""
    from PIL import Image
    canvas = Image.new("RGB", (width, height), "white")
    scale = min(width / img.width, height / img.height)
    w, h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    resized = img.convert("RGB").resize((w, h), Image.LANCZOS)
    canvas.paste(resized, ((width - w) // 2, (height - h) // 2))
    buf = io.BytesIO()
    canvas.save(buf, format="BMP")
    return buf.getvalue()


# ---------------- 화면 미리보기 (HTML) ----------------
def _color(direction):
    return {"up": "#d00000", "down": "#0a5be8"}.get(direction, "#555555")


def _energy_color(v):
    v = Decimal(v)
    return "#d00000" if v > 0 else ("#0a5be8" if v < 0 else "#555555")


def preview_html(finance, energy, now, kospi_b64, kosdaq_b64):
    """한글 양식 상단 표와 같은 구성을 화면(HTML)으로 보여 준다."""
    from html import escape as e
    cmp = build_values(finance, energy, now)
    cell_date = "%04d/%02d/%02d" % (now.year, now.month, now.day)
    d, u, f = finance["domestic"], finance["us"], finance["fx"]
    sm, du = energy["smp"], energy["dubai"]
    th = "padding:8px 10px;border:1px solid #9aa7c0;background:#e8eef9;font-weight:700;text-align:center;"
    td = "padding:8px 10px;border:1px solid #9aa7c0;text-align:center;"
    def chg(q):
        return '<span style="color:%s;font-weight:700">%s</span>' % (_color(q["direction"]), e(format_change(q)))
    def ech(v):
        return '<span style="color:%s;font-weight:700">%s</span>' % (_energy_color(v), e(format_energy_change(v)))
    html = f"""
<div style="background:#fff;color:#172b48;border-radius:12px;padding:24px 28px;max-width:1000px;margin:8px auto 8px;font-family:'KoPubDotum','Malgun Gothic',sans-serif;">
 <div style="text-align:center;font-size:22px;font-weight:800;margin-bottom:4px;">{e(date_label(now))}</div>
 <div style="text-align:center;color:#6b7a99;font-size:13px;margin-bottom:16px;">홍보처 편집 : OOO(061-OOOO), OOO(061-OOOO)</div>
 <table style="width:100%;border-collapse:collapse;font-size:15px;margin-bottom:18px;">
  <tr><th style="{th}" colspan="3">주 가 <span style="font-weight:400;font-size:12px;">({now:%H:%M} 현재)</span></th></tr>
  <tr><td style="{td}font-weight:700;">KOSPI(국내증시)</td><td style="{td}">{e(d['priceText'])}원</td><td style="{td}">{chg(d)}</td></tr>
  <tr><td style="{td}font-weight:700;">NYSE(뉴욕증시)</td><td style="{td}">{e(u['priceText'])}USD</td><td style="{td}">{chg(u)}</td></tr>
  <tr><td style="{td}font-weight:700;">환 율 · 미국USD</td><td style="{td}">{e(f['priceText'])}</td><td style="{td}">{chg(f)}</td></tr>
  <tr><td style="{td}" colspan="3"><img src="data:image/png;base64,{kospi_b64}" style="width:254px;max-width:48%;vertical-align:middle;"> <img src="data:image/png;base64,{kosdaq_b64}" style="width:218px;max-width:42%;vertical-align:middle;margin-left:12px;"></td></tr>
 </table>
 <table style="width:100%;border-collapse:collapse;font-size:15px;">
  <tr><th style="{th}" colspan="4">SMP(육지) <span style="font-weight:400;font-size:12px;">(단위:원/kWh)</span></th></tr>
  <tr><th style="{th}">날 짜</th><th style="{th}">평균가</th><th style="{th}">전년대비(2025년 평균 {BASELINE['smp']['2025']})</th><th style="{th}">2024년 평균 {BASELINE['smp']['2024']}</th></tr>
  <tr><td style="{td}">{cell_date}</td><td style="{td}">{e(sm['priceText'])}</td><td style="{td}">{ech(cmp['smp']['2025'])}</td><td style="{td}">{ech(cmp['smp']['2024'])}</td></tr>
  <tr><th style="{th}" colspan="4">유 가(Dubai 선물) <span style="font-weight:400;font-size:12px;">(단위:$/bbl)</span></th></tr>
  <tr><th style="{th}">날 짜</th><th style="{th}">가 격</th><th style="{th}">전년대비(2025년 평균 {BASELINE['dubai']['2025']})</th><th style="{th}">2024년 평균 {BASELINE['dubai']['2024']}</th></tr>
  <tr><td style="{td}">{cell_date}</td><td style="{td}">{e(du['priceText'])}</td><td style="{td}">{ech(cmp['dubai']['2025'])}</td><td style="{td}">{ech(cmp['dubai']['2024'])}</td></tr>
 </table>
 <div style="margin-top:14px;font-size:12px;color:#6b7a99;">※ 한글(.hwp) 양식에 들어가는 값을 같은 구성으로 보여 주는 화면입니다. 실제 모양은 내려받은 한글 파일에서 확인해 주세요.</div>
</div>"""
    return html
