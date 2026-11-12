from pathlib import Path
from datetime import datetime, timezone, timedelta
import base64
import json

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
from bs4 import BeautifulSoup

from data_services import (
    fetch_keywords,
    fetch_headlines,
    error_message,
)


# ==================================================
# 1. 기본 설정
# ==================================================
st.set_page_config(
    page_title="AI 큐레이터 | 일일브리핑",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))

HTML_CANDIDATES = [
    BASE_DIR / "briefing.html",
    BASE_DIR / "일일브리핑_통합작성기.html",
    BASE_DIR / "조간브리핑_통합작성기_서버연결.html",
    BASE_DIR / "조간브리핑_통합작성기.html",
    BASE_DIR / "완성본_조간브리핑_통합작성기.html",
    BASE_DIR / "조간브리핑_통합편집_130836.html",
]

HTML_PATH = next(
    (path for path in HTML_CANDIDATES if path.is_file()),
    None,
)

LOGO_PATH = BASE_DIR / "ai_curator_logo.png"

if "page" not in st.session_state:
    st.session_state.page = "home"

if "eff_subtab" not in st.session_state:
    st.session_state.eff_subtab = "monitoring"

if "sum_subtab" not in st.session_state:
    st.session_state.sum_subtab = "mss"


# ==================================================
# 2. 화면 및 서브탭 이동
# ==================================================
def go_home():
    st.session_state.page = "home"


def go_editor():
    st.session_state.editor_ready = False
    st.session_state.page = "editor"


def go_efficiency():
    st.session_state.page = "efficiency"


def go_summary():
    st.session_state.page = "summary"


def set_eff_subtab(tab_name):
    st.session_state.eff_subtab = tab_name


def set_sum_subtab(tab_name):
    st.session_state.sum_subtab = tab_name


# ==================================================
# 3. 파일 읽기 및 기사 발췌 로직
# ==================================================
def file_to_base64(path):
    return base64.b64encode(
        path.read_bytes()
    ).decode("ascii")


def read_text_file(path):
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(
            encoding="cp949",
            errors="replace",
        )


def extract_article_summary(url):
    """URL에 직접 접근하여 기사 본문 또는 공개 설명문을 발췌하는 함수"""
    if not url or not str(url).startswith("http"):
        return None  
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            return f"[요약 불가] 페이지 접근 실패 (HTTP 상태 코드: {response.status_code})"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('articleBody'):
                    body = data['articleBody'].strip()
                    return body[:300] + "..." if len(body) > 300 else body
            except Exception:
                pass
                
        article_tags = soup.find_all(['article', 'div'], class_names=['article_body', 'news_body', 'article-view', 'content'])
        for tag in article_tags:
            text = tag.get_text(strip=True)
            if len(text) > 50:
                return text[:300] + "..." if len(text) > 300 else text
                
        meta_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc.get('content').strip()
            return f"[설명문 발췌] {desc}"
            
        return "[요약 불가] 본문 영역을 추출할 수 없습니다 (유료/로그인/차단 페이지 가능성)."
        
    except requests.exceptions.Timeout:
        return "[요약 불가] 페이지 요청 시간 초과 (Timeout)"
    except Exception as e:
        return f"[요약 불가] 오류 발생: {str(e)}"


# ==================================================
# 4. 폰트와 로고
# ==================================================
FONT_CANDIDATES = [
    (BASE_DIR / "KoPubDotum.woff2", "font/woff2", "woff2"),
    (BASE_DIR / "KoPubDotum.ttf", "font/ttf", "truetype"),
]

font_face_css = ""

for font_path, mime_type, font_format in FONT_CANDIDATES:
    if font_path.is_file():
        encoded_font = file_to_base64(font_path)

        font_face_css = f"""
        @font-face {{
            font-family: "KoPubDotum";
            src: url("data:{mime_type};base64,{encoded_font}")
                     format("{font_format}");
            font-style: normal;
            font-weight: 400;
            font-display: swap;
        }}
        """
        break

if LOGO_PATH.is_file():
    logo_html = (
        '<div class="brief-logo brief-logo-image">'
        f'<img src="data:image/png;base64,{file_to_base64(LOGO_PATH)}" '
        'alt="AI CURATOR">'
        '</div>'
    )
else:
    logo_html = (
        '<div class="brief-logo brief-logo-text">'
        'AI CURATOR'
        '<small>하루를 시작하는 일일브리핑</small>'
        '</div>'
    )

D_ICON_SVG = """
<svg viewBox="0 0 100 100"
     fill="none"
     xmlns="http://www.w3.org/2000/svg"
     style="width:120px;height:120px;
            filter:drop-shadow(0 0 20px rgba(56,189,248,.45));">
    <defs>
        <linearGradient id="grad-d"
                        x1="0%" y1="0%"
                        x2="100%" y2="100%">
            <stop offset="0%" stop-color="#38bdf8"/>
            <stop offset="50%" stop-color="#818cf8"/>
            <stop offset="100%" stop-color="#4f46e5"/>
        </linearGradient>
    </defs>
    <path d="M20 10 H52 C74 10,90 26,90 50
             C90 74,74 90,52 90 H20 Z"
          fill="url(#grad-d)"/>
    <path d="M38 28 H50 C62 28,72 36,72 50
             C72 64,62 72,50 72 H38 Z"
          fill="#0d1c59"/>
    <path d="M46 58 L54 42 L60 48 L48 60 Z"
          fill="url(#grad-d)"/>
    <circle cx="58" cy="44" r="2" fill="#ffffff"/>
</svg>
"""


# ==================================================
# 5. 화면 스타일
# ==================================================
page_css = f"""
<style>
{font_face_css}

:root {{
    --navy: #0d1c59;
    --sky: #9be7ff;
}}

html, body, .stApp, .stApp button {{
    font-family: "KoPubDotum", sans-serif !important;
}}

.stApp {{
    min-height: 100vh;
    background: var(--navy);
}}

.block-container {{
    max-width: 100%;
    padding: 0 !important;
}}

header[data-testid="stHeader"] {{
    display: none;
}}

footer {{
    display: none;
}}

.st-key-landing, .st-key-editor_page_container, .st-key-eff_page_container, .st-key-sum_page_container {{
    min-height: 100vh;
    color: #ffffff;
    background: linear-gradient(
        180deg,
        #0d1c59 0%,
        #0d1c59 48%,
        #29477f 77%,
        #7895be 100%
    );
}}

.brief-nav {{
    max-width: 1180px;
    margin: 0 auto;
    padding: 25px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}

.brief-logo-image {{
    width: min(400px, 45vw);
}}

.brief-logo-image img {{
    width: 100%;
    height: auto;
}}

.brief-logo-text {{
    color: #ffffff;
    font-size: 28px;
    font-weight: 800;
}}

.brief-logo-text small {{
    display: block;
    margin-top: 8px;
    font-size: 12px;
    font-weight: 400;
}}

.brief-hero {{
    max-width: 1000px;
    margin: 0 auto;
    padding: 30px 20px 0;
    text-align: center;
}}

.brief-hero h1 {{
    margin: 0;
    color: #ffffff;
    font-size: clamp(20px, 2.2vw, 26px);
    font-weight: 700;
    line-height: 1.4;
}}

.brief-hero h1 span {{
    color: var(--sky);
}}

.brief-hero p {{
    margin: 16px auto 0;
    color: #f0f4ff;
    font-size: clamp(15px, 1.6vw, 18px);
    line-height: 1.7;
}}

.st-key-main_tabs {{
    max-width: 680px;
    margin: 40px auto 80px;
    padding: 0 20px;
}}

.st-key-main_tabs button {{
    min-height: 54px !important;
    border-radius: 27px !important;
    font-size: 18px !important;
    font-weight: 700 !important;
}}

.st-key-tab_daily button,
.st-key-tab_efficiency button,
.st-key-tab_summary button {{
    background: rgba(255,255,255,.08) !important;
    color: #c2d6ff !important;
    border: 1px solid rgba(255,255,255,.2) !important;
}}

.st-key-tab_daily button p,
.st-key-tab_efficiency button p,
.st-key-tab_summary button p {{
    color: #c2d6ff !important;
}}

.st-key-tab_daily button:hover,
.st-key-tab_efficiency button:hover,
.st-key-tab_summary button:hover {{
    background: rgba(255,255,255,.2) !important;
    border-color: #9be7ff !important;
    color: #ffffff !important;
}}

.st-key-tab_daily button:hover p,
.st-key-tab_efficiency button:hover p,
.st-key-tab_summary button:hover p {{
    color: #ffffff !important;
}}

.st-key-eff_subtabs,
.st-key-sum_subtabs {{
    max-width: 800px;
    margin: 20px auto 30px;
    padding: 0 20px;
}}

.st-key-eff_subtabs button,
.st-key-sum_subtabs button {{
    min-height: 50px !important;
    border-radius: 25px !important;
    font-size: 16px !important;
    font-weight: 700 !important;
}}

.st-key-eff_sub1 button,
.st-key-eff_sub2 button,
.st-key-eff_sub3 button,
.st-key-eff_sub4 button,
.st-key-sum_sub1 button,
.st-key-sum_sub2 button {{
    background: rgba(255,255,255,.08) !important;
    color: #c2d6ff !important;
    border: 1px solid rgba(255,255,255,.2) !important;
}}

.st-key-eff_sub1 button p,
.st-key-eff_sub2 button p,
.st-key-eff_sub3 button p,
.st-key-eff_sub4 button p,
.st-key-sum_sub1 button p,
.st-key-sum_sub2 button p {{
    color: #c2d6ff !important;
}}

.st-key-eff_sub1 button:hover,
.st-key-eff_sub2 button:hover,
.st-key-eff_sub3 button:hover,
.st-key-eff_sub4 button:hover,
.st-key-sum_sub1 button:hover,
.st-key-sum_sub2 button:hover {{
    background: rgba(255,255,255,.2) !important;
    border-color: #9be7ff !important;
    color: #ffffff !important;
}}

.st-key-eff_sub1 button:hover p,
.st-key-eff_sub2 button:hover p,
.st-key-eff_sub3 button:hover p,
.st-key-eff_sub4 button:hover p,
.st-key-sum_sub1 button:hover p,
.st-key-sum_sub2 button:hover p {{
    color: #ffffff !important;
}}

.sub-page-container {{
    max-width: 1100px;
    margin: 20px auto 60px;
    padding: 40px;
    background: rgba(255,255,255,.05);
    border-radius: 16px;
    border: 1px solid rgba(255,255,255,.1);
    color: #ffffff;
}}

.sub-page-container h2,
.sub-page-container p,
.sub-page-container label {{
    color: #ffffff !important;
}}

.stTextArea textarea {{
    color: #0d1c59 !important;
    background-color: #ffffff !important;
    font-weight: 600 !important;
}}

.st-key-editor_home button,
.st-key-eff_home button,
.st-key-sum_home button {{
    min-height: 50px !important;
    padding: 0 28px !important;
    border-radius: 25px !important;
    background: rgba(255,255,255,0.12) !important;
    border: 1px solid #9be7ff !important;
    color: #ffffff !important;
    font-size: 17px !important;
    font-weight: 700 !important;
    box-shadow: 0 0 12px rgba(155,231,255,0.25) !important;
}}

.st-key-editor_home button:hover,
.st-key-eff_home button:hover,
.st-key-sum_home button:hover {{
    background: #ffffff !important;
    color: #0d1c59 !important;
    border-color: #ffffff !important;
}}

.st-key-editor_home button p,
.st-key-editor_home button span,
.st-key-eff_home button p,
.st-key-eff_home button span,
.st-key-sum_home button p,
.st-key-sum_home button span {{
    color: #ffffff !important;
    font-size: 17px !important;
    font-weight: 700 !important;
}}

.st-key-editor_home button:hover p,
.st-key-editor_home button:hover span,
.st-key-eff_home button:hover p,
.st-key-eff_home button:hover span,
.st-key-sum_home button:hover p,
.st-key-sum_home button:hover span {{
    color: #0d1c59 !important;
}}

.st-key-open_final_editor button {{
    background: #174b91 !important;
    border: 1px solid #174b91 !important;
    min-height: 52px !important;
}}

.st-key-open_final_editor button [data-testid="stMarkdownContainer"] p,
.st-key-open_final_editor button p,
.st-key-open_final_editor button span {{
    color: #ffffff !important;
    font-size: 18px !important;
    font-weight: 700 !important;
}}

.st-key-open_final_editor button:hover {{
    background: #10396f !important;
}}

.editor-file-error {{
    margin: 24px;
    padding: 22px;
    border: 1px solid #e3cf82;
    border-radius: 10px;
    background: #fff8dc;
    color: #5a4914;
}}
</style>
"""

st.markdown(page_css, unsafe_allow_html=True)


# ==================================================
# 6. 메인 화면
# ==================================================
if st.session_state.page == "home":
    with st.container(key="landing"):
        st.markdown(
            f'<div class="brief-nav">{logo_html}</div>',
            unsafe_allow_html=True,
        )

        hero_html = (
            '<div class="brief-hero">'
            f'<div class="brief-hero-icon">{D_ICON_SVG}</div>'
            '<h1><span>오늘의 뉴스,</span> 한눈에 정리하세요.</h1>'
            '<p>'
            '워드클라우드부터 주요 기사와 정부 동향까지.<br>'
            '필요한 내용을 입력하고 일일브리핑을 완성해 보세요.'
            '</p>'
            '</div>'
        )

        st.markdown(hero_html, unsafe_allow_html=True)

        with st.container(key="main_tabs"):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.button(
                    "일일브리핑",
                    key="tab_daily",
                    on_click=go_editor,
                    use_container_width=True,
                )

            with col2:
                st.button(
                    "효율화",
                    key="tab_efficiency",
                    on_click=go_efficiency,
                    use_container_width=True,
                )

            with col3:
                st.button(
                    "요약",
                    key="tab_summary",
                    on_click=go_summary,
                    use_container_width=True,
                )


# ==================================================
# 7. 일일브리핑 작성기
# ==================================================
elif st.session_state.page == "editor":
    with st.container(key="editor_page_container"):
        col_nav1, col_nav2 = st.columns([8, 2])
        with col_nav1:
            st.markdown(f'<div class="brief-nav" style="padding: 25px 0 25px 32px;">{logo_html}</div>', unsafe_allow_html=True)
        with col_nav2:
            st.markdown('<div style="padding: 26px 32px 0 0; text-align: right;">', unsafe_allow_html=True)
            st.button("← 홈으로", key="editor_home", on_click=go_home)
            st.markdown('</div>', unsafe_allow_html=True)

        if HTML_PATH is None:
            st.markdown(
                '<div class="editor-file-error">'
                '<strong>일일브리핑 HTML 파일을 찾을 수 없습니다.</strong>'
                '<p>app.py와 같은 폴더에 briefing.html을 올려 주세요.</p>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.stop()

        try:
            html_content = read_text_file(HTML_PATH)
        except Exception as exc:
            st.error(f"HTML 파일을 읽을 수 없습니다: {exc}")
            st.stop()

        html_content = (
            html_content
            .replace("조간 브리핑", "일일브리핑")
            .replace("조간브리핑", "일일브리핑")
        )

        if not st.session_state.get("editor_ready", False):
            st.subheader("일일브리핑 자료 준비")

            selected = st.date_input(
                "보고일",
                value=datetime.now(KST).date(),
            )

            collect = st.checkbox(
                "스크랩마스터 키워드·신문 1면 단어쌍·"
                "연합뉴스 07:30 헤드라인 수집",
                value=True,
            )

            st.caption(
                "선택한 날짜로 조회합니다. "
                "신문 1면 단어쌍은 오늘 자료만 제공합니다. "
                "수집에 실패한 자료는 작성기에서 직접 넣을 수 있습니다."
            )

            if st.button(
                "작성기 열기",
                key="open_final_editor",
                type="primary",
            ):
                report_date = selected.strftime("%Y-%m-%d")

                boot = {
                    "version": 1,
                    "date": report_date,
                    "sources": {},
                }

                messages = []

                if collect:
                    with st.spinner(
                        "선택한 날짜의 자료를 수집하고 있습니다…"
                    ):
                        targets = [
                            ("도정 키워드", "words", False),
                            ("신문 1면 단어쌍", "nationalWords", True),
                        ]

                        for label, target, national in targets:
                            try:
                                pairs = fetch_keywords(
                                    report_date,
                                    national=national,
                                )

                                boot[target] = "\n".join(
                                    f"{item['word']},{item['score']:g}"
                                    for item in pairs
                                )

                                source_key = (
                                    "nationalCloud"
                                    if national
                                    else "cloud"
                                )

                                boot["sources"][source_key] = report_date

                                messages.append(
                                    (
                                        True,
                                        f"{label}: {len(pairs)}개 수집"
                                        f" / {report_date}",
                                    )
                                )

                            except Exception as exc:
                                messages.append(
                                    (
                                        False,
                                        label + ": " + error_message(exc),
                                    )
                                )

                        try:
                            text, source_url = fetch_headlines(
                                report_date
                            )

                            boot["headlines"] = text
                            boot["sources"]["headlines"] = report_date
                            boot["sources"]["headline_url"] = source_url

                            messages.append(
                                (
                                    True,
                                    "헤드라인: "
                                    + report_date
                                    + " 07:30 게시시각 검증 완료",
                                )
                            )

                        except Exception as exc:
                            messages.append(
                                (
                                    False,
                                    "헤드라인: " + error_message(exc),
                                )
                            )

                st.session_state.editor_boot = boot
                st.session_state.editor_messages = messages
                st.session_state.editor_ready = True
                st.rerun()

            st.stop()

        for ok, message in st.session_state.get(
            "editor_messages",
            [],
        ):
            if ok:
                st.success(message)
            else:
                st.warning(message)

        st.caption(
            "홈으로 이동하거나 새로고침하기 전에 "
            "작성기 안의 ‘작업 저장’을 눌러 주세요. "
            "입력 내용과 이미지는 작업 JSON으로 보관합니다."
        )

        boot_json = json.dumps(
            st.session_state.get("editor_boot", {}),
            ensure_ascii=False,
        ).replace("<", "\\u003c")

        boot_script = (
            '<script type="application/json" id="boot-data">'
            + boot_json
            + "</script>"
        )

        html_content = html_content.replace(
            "<!--BOOT-->",
            boot_script,
        )

        editor_css = f"""
        <style>
        {font_face_css}

        html, body {{
            font-family: "KoPubDotum", sans-serif !important;
        }}

        body {{
            background: #eef3fb;
            color: #172b48;
        }}

        header.top {{
            background: #0d1c59 !important;
            color: #ffffff !important;
        }}

        header.top h1 {{
            color: #9be7ff !important;
        }}

        header.top p {{
            color: #e5edff !important;
        }}

        aside {{
            background: #0d1c59 !important;
            color: #ffffff !important;
        }}

        aside * {{
            color: #ffffff !important;
        }}

        .card {{
            background: #ffffff !important;
            color: #172b48 !important;
            border-radius: 10px !important;
        }}

        .card h2,
        .card h3,
        .card label {{
            color: #172b48 !important;
        }}

        .hint {{
            color: #425570;
        }}

        textarea, input {{
            background: #ffffff !important;
            color: #102653 !important;
        }}

        button.primary {{
            background: #0d1c59 !important;
            color: #ffffff !important;
        }}

        @media print {{
            body {{
                background: #ffffff;
            }}
        }}
        </style>
        """

        head_end = html_content.lower().find("</head>")

        if head_end != -1:
            html_content = (
                html_content[:head_end]
                + editor_css
                + html_content[head_end:]
            )
        else:
            html_content = editor_css + html_content

        components.html(
            html_content,
            height=1100,
            scrolling=True,
        )


# ==================================================
# 8. 효율화 (1. 모니터링 탭 포함)
# ==================================================
elif st.session_state.page == "efficiency":
    with st.container(key="editor_page_container"):
        col_nav1, col_nav2 = st.columns([8, 2])
        with col_nav1:
            st.markdown(f'<div class="brief-nav" style="padding: 25px 0 25px 32px;">{logo_html}</div>', unsafe_allow_html=True)
        with col_nav2:
            st.markdown('<div style="padding: 26px 32px 0 0; text-align: right;">', unsafe_allow_html=True)
            st.button("← 홈으로", key="eff_home", on_click=go_home)
            st.markdown('</div>', unsafe_allow_html=True)

        with st.container(key="eff_subtabs"):
            sc1, sc2, sc3, sc4 = st.columns(4)

            with sc1:
                st.button(
                    "1. 모니터링",
                    key="eff_sub1",
                    on_click=lambda: set_eff_subtab("monitoring"),
                    use_container_width=True,
                )
            with sc2:
                st.button(
                    "2. 한국전력공사 목차",
                    key="eff_sub2",
                    on_click=lambda: set_eff_subtab("kepco"),
                    use_container_width=True,
                )
            with sc3:
                st.button(
                    "3. 청송군청 목차",
                    key="eff_sub3",
                    on_click=lambda: set_eff_subtab("cheongsong"),
                    use_container_width=True,
                )
            with sc4:
                st.button(
                    "4. 고성군청 목차",
                    key="eff_sub4",
                    on_click=lambda: set_eff_subtab("goseong"),
                    use_container_width=True,
                )

        current_sub = st.session_state.get("eff_subtab", "monitoring")

        if current_sub == "monitoring":
            st.markdown(
                """
                <div class="sub-page-container">
                    <h2>📊 1. 모니터링 (기사 발췌 및 엑셀 연동 도구)</h2>
                    <p>기사 엑셀 파일(`.xlsx`)을 업로드하면 유효한 URL이 존재하는 기사만 접근하여 본문을 발췌하고 리포트를 생성합니다. (URL이 없는 항목은 자동 제외)</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.container():
                st.markdown("### 📂 기사 엑셀 파일 열기")
                uploaded_article_file = st.file_uploader(
                    "기사 데이터 엑셀 파일 (.xlsx)",
                    type=["xlsx"],
                    key="article_uploader"
                )

                if uploaded_article_file is not None:
                    try:
                        excel_file = pd.ExcelFile(uploaded_article_file)
                        sheet_names = excel_file.sheet_names
                        df_articles = pd.read_excel(uploaded_article_file, sheet_name=sheet_names[0])
                        
                        st.success(f"엑셀 파일 로드 성공! (총 {len(df_articles)}행 감지)")

                        with st.expander("업로드된 엑셀 데이터 미리보기"):
                            st.dataframe(df_articles.head(10))

                        if st.button("🚀 유효 기사 발췌 및 요약 수행", key="run_article_scraping", type="primary"):
                            with st.spinner("언론사 페이지에 접속하여 유효 기사 본문 발췌 중..."):
                                
                                report_lines = []
                                report_lines.append("< '26. 11. 9(월), 조간 주요 보도 발췌 >\n\n")
                                report_lines.append("■ 기사 발췌 결과\n\n")

                                url_col = None
                                title_col = None
                                press_col = None
                                
                                for col in df_articles.columns:
                                    col_lower = str(col).lower()
                                    if 'url' in col_lower or '링크' in col_lower:
                                        url_col = col
                                    elif '제목' in col_lower or 'title' in col_lower:
                                        title_col = col
                                    elif '매체' in col_lower or '언론' in col_lower or 'press' in col_lower:
                                        press_col = col

                                if not url_col:
                                    for col in df_articles.columns:
                                        sample_val = str(df_articles[col].iloc[0]) if len(df_articles) > 0 else ""
                                        if sample_val.startswith("http"):
                                            url_col = col
                                            break

                                success_count = 0
                                for idx, row in df_articles.iterrows():
                                    url = str(row[url_col]) if url_col and pd.notna(row[url_col]) else ""
                                    
                                    if not url or not url.startswith("http"):
                                        continue
                                        
                                    extracted_text = extract_article_summary(url)
                                    if extracted_text and "[요약 불가] URL이 존재하지 않습니다" not in extracted_text:
                                        title = str(row[title_col]) if title_col and pd.notna(row[title_col]) else f"기사 {idx+1}"
                                        press = str(row[press_col]) if press_col and pd.notna(row[press_col]) else "언론사"

                                        report_lines.append(f"ㅇ [{press}] {title}\n")
                                        report_lines.append(f"접속 URL: {url}\n")
                                        report_lines.append(f"발췌 내용: {extracted_text}\n\n")
                                        success_count += 1

                                final_report = "".join(report_lines)

                            st.success(f"발췌 완료! (총 {success_count}건의 유효 기사 반영)")
                            st.text_area("발췌 결과 미리보기", final_report, height=400, key="article_preview")

                            st.download_button(
                                label="📥 발췌 리포트 텍스트 다운로드 (.txt)",
                                data=final_report.encode("utf-8-sig"),
                                file_name="기사_발췌_요약리포트.txt",
                                mime="text/plain",
                                key="download_article_txt"
                            )

                    except Exception as exc:
                        st.error(f"엑셀 파일을 처리하는 도중 오류가 발생했습니다: {exc}")

        elif current_sub == "kepco":
            st.markdown(
                """
                <div class="sub-page-container">
                    <h2>⚡ 2. 한국전력공사 목차</h2>
                    <p>한국전력공사 맞춤형 뉴스 브리핑 및 문서 목차 생성 공간입니다.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif current_sub == "cheongsong":
            st.markdown(
                """
                <div class="sub-page-container">
                    <h2>🌱 3. 청송군청 목차</h2>
                    <p>청송군청 맞춤형 뉴스 브리핑 및 문서 목차 생성 공간입니다.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif current_sub == "goseong":
            st.markdown(
                """
                <div class="sub-page-container">
                    <h2>🌊 4. 고성군청 목차</h2>
                    <p>고성군청 맞춤형 뉴스 브리핑 및 문서 목차 생성 공간입니다.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ==================================================
# 9. 요약 (중기부 조간 요약 포함)
# ==================================================
elif st.session_state.page == "summary":
    with st.container(key="editor_page_container"):
        col_nav1, col_nav2 = st.columns([8, 2])
        with col_nav1:
            st.markdown(f'<div class="brief-nav" style="padding: 25px 0 25px 32px;">{logo_html}</div>', unsafe_allow_html=True)
        with col_nav2:
            st.markdown('<div style="padding: 26px 32px 0 0; text-align: right;">', unsafe_allow_html=True)
            st.button("← 홈으로", key="sum_home", on_click=go_home)
            st.markdown('</div>', unsafe_allow_html=True)

        with st.container(key="sum_subtabs"):
            sc1, sc2 = st.columns(2)

            with sc1:
                st.button(
                    "1. 중기부 조간 요약",
                    key="sum_sub1",
                    on_click=lambda: set_sum_subtab("mss"),
                    use_container_width=True,
                )
            with sc2:
                st.button(
                    "2. 문체부 조간 요약",
                    key="sum_sub2",
                    on_click=lambda: set_sum_subtab("mcst"),
                    use_container_width=True,
                )

        current_sum_sub = st.session_state.get("sum_subtab", "mss")

        if current_sum_sub == "mss":
            st.markdown(
                """
                <div class="sub-page-container">
                    <h2>🏢 1. 중기부 조간 요약 (맞춤 양식 변환)</h2>
                    <p>데이터 파일을 업로드하시면 요청하신 보도 양식에 맞춘 TXT 요약본으로 자동 변환해 드립니다.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.container():
                st.markdown("### 📂 조간 데이터 파일 업로드")
                uploaded_macro_file = st.file_uploader(
                    "중기부 조간 데이터 파일 (.xlsx, .xls)",
                    type=["xlsx", "xls"],
                    key="mss_uploader"
                )

                if uploaded_macro_file is not None:
                    try:
                        excel_file = pd.ExcelFile(uploaded_macro_file)
                        sheet_names = excel_file.sheet_names
                        df_mss = pd.read_excel(uploaded_macro_file, sheet_name=sheet_names[0])
                        
                        st.success(f"데이터 로드 성공! (총 {len(df_mss)}행 감지)")

                        with st.expander("업로드된 데이터 미리보기"):
                            st.dataframe(df_mss.head())

                        if st.button("🚀 요청 양식으로 TXT 변환", key="run_mss_python", type="primary"):
                            with st.spinner("요청하신 양식에 맞춰 변환 중..."):
                                
                                cleaned_df = df_mss.dropna(how="all").fillna("")
                                
                                txt_lines = []
                                txt_lines.append("< '26. 11. 9(월), 조간 주요 보도 >\n\n")
                                txt_lines.append("■ 우리부 관련\n\n")

                                for idx, row in cleaned_df.iterrows():
                                    row_vals = [str(val).strip() for val in row.values if str(val).strip() != ""]
                                    if len(row_vals) >= 2:
                                        press = row_vals[0]
                                        title = row_vals[1]
                                        link = row_vals[2] if len(row_vals) > 2 else ""
                                        
                                        txt_lines.append(f"ㅇ {press}, {title}\n")
                                        if link:
                                            txt_lines.append(f"{link}\n\n")
                                        else:
                                            txt_lines.append("\n")
                                    elif len(row_vals) == 1:
                                        txt_lines.append(f"ㅇ {row_vals[0]}\n\n")

                                text_content = "".join(txt_lines)

                            st.success("양식 변환이 완료되었습니다!")
                            st.text_area("변환된 텍스트 미리보기", text_content, height=350, key="mss_preview")

                            st.download_button(
                                label="📥 양식 맞춤 텍스트 파일 다운로드 (.txt)",
                                data=text_content.encode("utf-8-sig"),
                                file_name="중기부_조간요약_양식적용.txt",
                                mime="text/plain",
                                key="download_mss_txt"
                            )

                    except Exception as exc:
                        st.error(f"데이터를 처리하는 도중 오류가 발생했습니다: {exc}")

        elif current_sum_sub == "mcst":
            st.markdown(
                """
                <div class="sub-page-container">
                    <h2>🏛️ 2. 문체부 조간 요약</h2>
                    <p>문화체육관광부 관련 조간 뉴스 및 주요 동향 요약 공간입니다.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
