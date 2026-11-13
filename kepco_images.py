"""코스피/코스닥 지수 박스 이미지를 직접 그린다 (원본은 다음 검색 화면 캡처).

서버에는 브라우저가 없으므로, 수집한 숫자로 같은 모양(이름·지수·등락·등락률)을 그립니다.
한글 글꼴이 필요합니다 (Streamlit Cloud: packages.txt에 fonts-nanum).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent

FONT_CANDIDATES = [
    # 저장소에 올려 둔 글꼴 우선
    BASE_DIR / "KoPubDotum.ttf",
    # Streamlit Cloud (packages.txt: fonts-nanum)
    Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    # Noto CJK
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    # Windows
    Path("C:/Windows/Fonts/malgunbd.ttf"),
]
REGULAR_CANDIDATES = [
    BASE_DIR / "KoPubDotum.ttf",
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("C:/Windows/Fonts/malgun.ttf"),
]

RED = (222, 0, 0)
BLUE = (10, 90, 230)
GRAY = (90, 90, 90)
BLACK = (20, 20, 20)


def _font(cands, size):
    for p in cands:
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    raise RuntimeError("한글 글꼴을 찾지 못했습니다 (packages.txt에 fonts-nanum을 추가해 주세요)")


def render_index_box(label, price_text, change_text, ratio_text, direction, size):
    """label 예: '한국 코스피'. size=(w,h). 4배로 그린 뒤 줄여서 부드럽게 만든다."""
    w, h = size
    k = 4
    img = Image.new("RGB", (w * k, h * k), "white")
    d = ImageDraw.Draw(img)
    color = RED if direction == "up" else (BLUE if direction == "down" else GRAY)
    sign = "+" if direction == "up" else ("-" if direction == "down" else "")
    ratio_full = sign + ratio_text + "%"
    x0 = int(w * 0.05 * k)
    avail = w * k - 2 * x0

    # 가로 폭에 맞을 때까지 글자 크기를 줄인다
    scale = 1.0
    while True:
        f_price = _font(FONT_CANDIDATES, int(h * 0.46 * k * scale))
        f_small = _font(REGULAR_CANDIDATES, int(h * 0.21 * k * scale))
        tw, th = int(h * 0.11 * k * scale), int(h * 0.09 * k * scale)
        gap = int(h * 0.08 * k * scale)
        total = (d.textlength(price_text, font=f_price) + gap + tw + gap // 2
                 + d.textlength(change_text, font=f_small) + gap // 2
                 + d.textlength(ratio_full, font=f_small))
        if total <= avail or scale < 0.4:
            break
        scale -= 0.04

    f_label = _font(FONT_CANDIDATES, int(h * 0.27 * k))
    d.text((x0, int(h * 0.05 * k)), label, font=f_label, fill=BLACK)
    y_price = int(h * 0.38 * k)
    d.text((x0, y_price), price_text, font=f_price, fill=color)
    px = x0 + d.textlength(price_text, font=f_price) + gap
    ty = y_price + int(h * 0.30 * k * scale)
    if direction == "up":
        d.polygon([(px + tw // 2, ty - th // 2), (px, ty + th // 2), (px + tw, ty + th // 2)], fill=color)
    elif direction == "down":
        d.polygon([(px, ty - th // 2), (px + tw, ty - th // 2), (px + tw // 2, ty + th // 2)], fill=color)
    else:
        d.rectangle([px, ty - 2 * k, px + tw, ty + 2 * k], fill=color)
    px += tw + gap // 2
    y_small = y_price + int(h * 0.17 * k * scale)
    d.text((px, y_small), change_text, font=f_small, fill=color)
    px += d.textlength(change_text, font=f_small) + gap // 2
    d.text((px, y_small), ratio_full, font=f_small, fill=color)
    return img.resize((w, h), Image.LANCZOS)


def render_kospi(q):
    return render_index_box("한국 코스피", q["priceText"], q["changeText"], q["ratioText"],
                            q["direction"], (254, 70))


def render_kosdaq(q):
    return render_index_box("한국 코스닥", q["priceText"], q["changeText"], q["ratioText"],
                            q["direction"], (218, 66))
