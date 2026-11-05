"""KOSPI 모멘텀용 과거 월별 아카이브 변환기.

외부 원천의 전종목 일별 시가총액 자료를, 앱이 읽는 월별 종목선정 파일 형식으로
바꾼다. 이 모듈은 네트워크·Streamlit·파일 쓰기를 전혀 하지 않아 원천자료를
받은 뒤의 변환 규칙을 독립적으로 검증할 수 있다.
"""

from pathlib import Path

import pandas as pd


ARCHIVE_COLUMNS = [
    "순위", "투자연도", "투자월", "종목선정일", "종목코드", "종목명", "시장",
    "1개월(%)", "3개월(%)", "6개월(%)", "12개월(%)",
    "시가총액", "종가", "거래량", "이번달수익률",
]


def with_return_prices(source):
    """KRX 당일 기준가격(종가-전일대비)으로 기업행동 가격단절을 제거한다.

    배당·분할 신주·인적분할 수령주식의 총수익을 재현하지는 않는다.
    상장폐지 정산도 별도 검증이 필요한 연구용 가격지수다.
    """
    data = source.sort_values(["Code", "Date"]).copy()
    close = pd.to_numeric(data["Close"], errors="raise")
    reference = close - pd.to_numeric(data["Changes"], errors="raise")
    valid = (close > 0) & (reference > 0)
    if not valid.all():
        raise ValueError("KRX 기준가격을 계산할 수 없는 행이 있습니다")
    factors = close / reference
    data["ReturnClose"] = factors.groupby(data["Code"]).cumprod()
    return data


def _price_on_or_before(prices, cutoff):
    """cutoff 이후 데이터를 절대 쓰지 않고, 직전 거래일 종가를 돌려준다."""
    eligible = prices[prices["Date"] <= cutoff]
    if eligible.empty:
        return None
    value = eligible.iloc[-1]["ReturnClose"]
    return float(value) if pd.notna(value) and value > 0 else None


def _return_to(prices, base_close, cutoff):
    previous_close = _price_on_or_before(prices, cutoff)
    if previous_close is None or base_close <= 0:
        return float("nan")
    return round((base_close / previous_close - 1.0) * 100.0, 2)


def _next_month_return(prices, base_date, base_close):
    """선정일 직후부터 다음 달 말까지의 실제 보유수익률을 계산한다."""
    next_end = (base_date.to_period("M") + 1).end_time.normalize()
    eligible = prices[(prices["Date"] > base_date) & (prices["Date"] <= next_end)]
    if eligible.empty or base_close <= 0:
        return float("nan")
    next_close = float(eligible.iloc[-1]["ReturnClose"])
    return round((next_close / base_close - 1.0) * 100.0, 2) if next_close > 0 else float("nan")


def build_monthly_archive(source, start_month, end_month, top_n=200):
    """전종목 일별 자료에서 월말 KOSPI 보통주 시총 상위 종목을 만든다.

    Args:
        source: ``Date, Code, Name, Close, Volume, Marcap, MarketId, Market`` 열을
            가진 일별 전종목 DataFrame. ``MarketId == 'STK'``가 KOSPI다.
        start_month, end_month: 포함 범위의 ``YYYY-MM`` 문자열.
        top_n: 선정 종목 수. 제품 데이터는 200, 테스트에서는 작은 값도 가능하다.

    Returns:
        앱의 ``archive_kospi/only_kospi_YYYY_MM.csv``와 호환되는 DataFrame.
        과거 가격이 없으면 수익률을 0으로 꾸미지 않고 NaN으로 보존한다.
    """
    required = {"Date", "Code", "Name", "Close", "Volume", "Marcap", "MarketId", "Market"}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError("원천 필수 열 누락: " + ", ".join(sorted(missing)))

    data = source.copy()
    if "ReturnClose" not in data:
        data["ReturnClose"] = data["Close"]
    data["Date"] = pd.to_datetime(data["Date"])
    data["Code"] = data["Code"].astype(str).str.strip().str.zfill(6)
    for column in ("Close", "Volume", "Marcap"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.sort_values(["Code", "Date"])
    # 49개월×200종목을 만들 때 매 행마다 전체 원천을 다시 필터하면 수십억 행을
    # 훑게 된다. 코드별 가격표는 한 번만 나눠 이후의 과거·다음달 조회에 재사용한다.
    prices_by_code = {code: frame for code, frame in data.groupby("Code", sort=False)}

    # 기존 로봇과 동일하게 KOSPI(STK) 보통주(코드 끝 0)만 월말 시총으로 자른다.
    universe = data[
        (data["MarketId"].astype(str) == "STK")
        & data["Code"].str.endswith("0")
        & (data["Close"] > 0)
        & (data["Volume"] > 0)
        & (data["Marcap"] > 0)
    ].copy()
    if universe.empty:
        return pd.DataFrame(columns=ARCHIVE_COLUMNS)

    start = pd.Period(start_month, freq="M")
    end = pd.Period(end_month, freq="M")
    records = []
    for month in pd.period_range(start, end, freq="M"):
        # 앱의 투자월은 그 달 *직전* 월말에 종목을 고른 뒤 한 달 보유한 결과다.
        # 같은 달 말 스냅샷을 쓰면 그 달 수익률을 보고 매수한 look-ahead가 된다.
        selection_month = month - 1
        in_month = universe[universe["Date"].dt.to_period("M") == selection_month]
        if in_month.empty:
            continue
        base_date = in_month["Date"].max()
        snapshot = universe[universe["Date"] == base_date].nlargest(top_n, "Marcap").copy()
        snapshot = snapshot.sort_values("Marcap", ascending=False).reset_index(drop=True)
        for rank, row in snapshot.iterrows():
            code = row["Code"]
            prices = prices_by_code[code]
            base_close = float(row["Close"])
            return_close = float(row["ReturnClose"])
            records.append(
                {
                    "순위": rank + 1,
                    "투자연도": int(month.year),
                    "투자월": str(month),
                    "종목선정일": base_date.strftime("%Y-%m-%d"),
                    "종목코드": code,
                    "종목명": row["Name"],
                    "시장": "KOSPI",
                    "1개월(%)": _return_to(prices, return_close, (selection_month - 1).end_time.normalize()),
                    "3개월(%)": _return_to(prices, return_close, (selection_month - 3).end_time.normalize()),
                    "6개월(%)": _return_to(prices, return_close, (selection_month - 6).end_time.normalize()),
                    "12개월(%)": _return_to(prices, return_close, (selection_month - 12).end_time.normalize()),
                    "시가총액": int(row["Marcap"]),
                    "종가": base_close,
                    "거래량": int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
                    "이번달수익률": _next_month_return(prices, base_date, return_close),
                }
            )
    return pd.DataFrame(records, columns=ARCHIVE_COLUMNS)


def write_monthly_archives(source, start_month, end_month, output_dir, top_n=200):
    """월별 파일을 새로만 쓴다. 기존 파일은 절대 덮어쓰지 않는다.

    반환된 경로 목록은 생성 직후 행 수·기간 검증에 사용한다. 이 함수의 보수적
    덮어쓰기 금지는 로봇이 소유한 기존 월별 자료를 수동 백필이 훼손하지 않게 한다.
    """
    archive = build_monthly_archive(source, start_month, end_month, top_n=top_n)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    written = []
    for month, frame in archive.groupby("투자월", sort=True):
        path = output / ("only_kospi_" + month.replace("-", "_") + ".csv")
        if path.exists():
            raise FileExistsError("기존 아카이브 덮어쓰기 금지: " + str(path))
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        written.append(path)
    return written
