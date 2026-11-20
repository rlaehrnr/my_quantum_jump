"""KODEX 인버스(114800)의 실제 상장 이후 종가."""

import ast
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import requests


KOSPI_INVERSE_CODE = "114800"
KOSPI_INVERSE_NAME = "KODEX 인버스 (114800)"
KOSPI_INVERSE_LISTING = pd.Timestamp("2009-09-16")
KOSPI_INVERSE_FIRST_MONTH = "2009-10"
INVERSE_PATH = Path("data/kospi_inverse_daily.csv")
SEOUL = "Asia/Seoul"


def _validated_closes(dates, prices):
    close = pd.Series(pd.to_numeric(prices, errors="coerce"), index=pd.DatetimeIndex(dates, name="날짜"),
                      name="종가").sort_index()
    if (close.empty or close.index.hasnans or close.index.has_duplicates
            or close.index[0] != KOSPI_INVERSE_LISTING or not (close.gt(0) & close.lt(float("inf"))).all()):
        raise ValueError("KODEX 인버스 일별 종가가 유효하지 않습니다.")
    return close


def _naver_rows(symbol, last_day):
    response = requests.get(
        "https://api.finance.naver.com/siseJson.naver",
        params={"symbol": symbol, "requestType": "1", "timeframe": "day",
                "startTime": KOSPI_INVERSE_LISTING.strftime("%Y%m%d"), "endTime": last_day.strftime("%Y%m%d")},
        timeout=10,
    )
    response.raise_for_status()
    return ast.literal_eval(response.content.decode("utf-8-sig").replace("null", "None").strip())[1:]


def fetch_inverse_daily():
    """상장일부터의 종가를 받고 KOSPI200 거래일과 대조한다."""
    now = pd.Timestamp.now(tz=SEOUL).tz_localize(None)
    last_day = now.normalize()
    if (now.hour, now.minute) < (15, 30):
        last_day -= pd.Timedelta(days=1)
    rows = _naver_rows(KOSPI_INVERSE_CODE, last_day)
    dates = pd.to_datetime([row[0] for row in rows], format="%Y%m%d")
    close = _validated_closes(dates, [row[4] for row in rows]).loc[:last_day]
    calendar = _naver_rows("KPI200", last_day)
    sessions = pd.to_datetime([row[0] for row in calendar], format="%Y%m%d").sort_values()
    if not close.index.equals(sessions):
        raise ValueError("KOSPI200 거래일과 인버스 종가 날짜가 일치하지 않습니다.")
    return close


def read_inverse_daily(path=INVERSE_PATH):
    data = pd.read_csv(path, encoding="utf-8-sig")
    return _validated_closes(pd.to_datetime(data["날짜"]), data["종가"].to_numpy())


def update_inverse_daily(path=INVERSE_PATH):
    """수집 로봇에서만 사용한다. 불완전한 응답이면 기존 파일을 보존한다."""
    close = fetch_inverse_daily()
    if path.exists():
        old = read_inverse_daily(path)
        if not old.index.isin(close.index).all():
            raise ValueError("기존 인버스 시세가 누락되어 현재 CSV를 보존합니다.")
        if old.equals(close):
            return close
    with NamedTemporaryFile(dir=path.parent, delete=False) as file:
        tmp = Path(file.name)
    try:
        close.to_csv(tmp, encoding="utf-8-sig")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return close
