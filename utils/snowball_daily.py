"""스노우볼 이번 달 성과와 다음 달 잠정 신호에 쓰는 일봉 계산."""
from pathlib import Path

import pandas as pd


SNAPSHOTS = {"US": Path("data/snowball/daily_snapshot.csv"),
             "KR": Path("data/snowball_kr/daily_snapshot.csv")}


def read_snapshot(path):
    try:
        daily = pd.read_csv(path, index_col="날짜", parse_dates=["날짜"])
    except (OSError, ValueError):
        return pd.DataFrame(index=pd.DatetimeIndex([]))
    return daily.sort_index()


def signal_for_month(signals, month):
    key = month if isinstance(signals.index, pd.PeriodIndex) else str(month)
    return signals.loc[key] if key in signals.index else {}


def holding_weights(signal, alias=lambda ticker: ticker):
    """각 전략 신호에서 월초 비중을 읽고 실운용 종목코드로 변환한다."""
    holds = signal.get("holds", signal.get("hold"))
    if isinstance(holds, str):
        holds = [holds]
    if not isinstance(holds, (list, tuple, dict)) or not holds:
        return {}
    weights = holds if isinstance(holds, dict) else dict.fromkeys(holds, 1 / len(holds))
    live_weights = {}
    for ticker, weight in weights.items():
        live = alias(ticker) or ticker
        live_weights[live] = live_weights.get(live, 0) + weight
    return live_weights


def month_performance(daily, weights, month):
    """전월 마지막 종가로 진입한 뒤 월초 비중으로 계속 보유한 가격 성과."""
    dates = daily.index.to_period("M")
    previous = daily.loc[dates == month - 1]
    current = daily.loc[dates == month].reindex(columns=list(weights))
    if not weights or previous.empty or current.empty:
        return pd.DataFrame()

    base = previous.iloc[-1].reindex(list(weights))
    if "CASH" in weights:
        base["CASH"] = 1.
        current["CASH"] = 1.
    if base.isna().any():
        return pd.DataFrame()

    growth = current.div(base)
    portfolio = growth.mul(pd.Series(weights)).sum(axis=1, min_count=len(weights))
    daily_returns = current.div(current.shift()).sub(1)
    daily_returns.iloc[0] = growth.iloc[0] - 1
    portfolio_daily = portfolio.div(portfolio.shift()).sub(1)
    portfolio_daily.iloc[0] = portfolio.iloc[0] - 1

    result = pd.DataFrame({"포트 일간": portfolio_daily, "포트 누적": portfolio - 1})
    for ticker in weights:
        result[f"{ticker} 일간"] = daily_returns[ticker]
        result[f"{ticker} 누적"] = growth[ticker] - 1
    return result.loc[portfolio.notna()]


def preview_monthly(monthly, daily, tickers, month):
    """월봉의 가격 척도를 유지하며 일봉의 월중 등락률로 잠정 월봉을 만든다."""
    history = monthly.loc[monthly.index < month]
    dates = daily.index.to_period("M")
    previous = daily.loc[dates == month - 1]
    current = daily.loc[dates == month]
    if month - 1 not in history.index or previous.empty or current.empty:
        return None

    tickers = list(dict.fromkeys(tickers))
    anchor = history.loc[month - 1].reindex(tickers)
    base = previous.iloc[-1].reindex(tickers)
    latest = current.iloc[-1].reindex(tickers)
    if (anchor.isna().any() or base.isna().any() or latest.isna().any()):
        return None

    # 12개월 수익률, 이동평균 등에 쓰이는 월 간격을 보존한다.
    history = history.reindex(pd.period_range(history.index.min(), month, freq="M"))
    history.loc[month, tickers] = anchor * latest / base
    return history, current.index[-1]
