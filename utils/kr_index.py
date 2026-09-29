"""한국 주요 지수 데이터의 단일 출처.

FinanceDataReader의 축약 티커(KS11·KQ11)는 GitHub 연도별 캐시를 읽는다.
캐시 갱신이 멈추면 앱과 로봇이 모두 오래된 지수를 쓰게 되므로,
날짜별 원시세를 제공하는 Naver 경로를 명시적으로 사용한다.
"""

import FinanceDataReader as fdr


KR_INDEX_SYMBOLS = {
    "KOSPI": "NAVER:KOSPI",
    "KOSDAQ": "NAVER:KOSDAQ",
}


def load_kr_index(market, start, end=None):
    """KOSPI 또는 KOSDAQ 일별 지수를 최신 Naver 경로에서 읽는다."""
    market = str(market).upper()
    if market not in KR_INDEX_SYMBOLS:
        raise ValueError(f"지원하지 않는 한국 지수: {market}")
    return fdr.DataReader(KR_INDEX_SYMBOLS[market], start, end)
