"""임시(placeholder) data_services.py

기존에 쓰던 data_services.py가 있다면 이 파일 대신 그 파일을 올리세요.
이 임시 파일은 앱이 오류 없이 실행되도록 만든 것이며,
키워드/헤드라인 자동 수집은 하지 않고 '수집 불가' 안내만 표시합니다.
(효율화 > 모니터링, 요약 탭은 이 파일과 상관없이 동작합니다.)
"""


def fetch_keywords(report_date, national=False):
    raise RuntimeError("자동 수집 기능이 아직 연결되지 않았습니다. 작성기에서 직접 입력해 주세요.")


def fetch_headlines(report_date):
    raise RuntimeError("자동 수집 기능이 아직 연결되지 않았습니다. 작성기에서 직접 입력해 주세요.")


def error_message(exc):
    return str(exc)
