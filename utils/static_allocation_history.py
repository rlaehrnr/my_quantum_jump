import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import time, timedelta

import pandas as pd
import requests
import yfinance as yf

from utils.static_allocation import plan_weights, valid_ticker


SESSION_PROXY = {"kr": "069500", "us": "SPY"}
MARKET_CLOCK = {"kr": ("Asia/Seoul", time(15, 40)), "us": ("America/New_York", time(16, 10))}
NAVER_HISTORY = "https://api.finance.naver.com/siseJson.naver"


def market_dates(market):
    timezone, published_after = MARKET_CLOCK[market]
    now = pd.Timestamp.now(tz=timezone)
    cutoff = now.date() if now.time() >= published_after else now.date() - timedelta(days=1)
    return pd.Period(now.date(), freq="M"), cutoff


def _load_close(ticker, market, cutoff):
    if market == "kr":
        response = requests.get(NAVER_HISTORY, params={
            "symbol": ticker, "requestType": 1, "startTime": "19900101",
            "endTime": cutoff.strftime("%Y%m%d"), "timeframe": "day",
        }, timeout=10)
        response.raise_for_status()
        rows = ast.literal_eval(response.text.strip())
        dates = pd.to_datetime([row[0] for row in rows[1:]], format="%Y%m%d")
        closes = pd.Series([row[4] for row in rows[1:]], index=dates, dtype="float64")
    else:
        history = yf.Ticker(ticker).history(
            period="max", interval="1d", auto_adjust=True, timeout=10,
        )
        if history.empty:
            return pd.Series(dtype="float64")
        closes = history["Close"].copy()
        closes.index = closes.index.tz_localize(None).normalize()
    closes = closes.loc[~closes.index.duplicated(keep="last")].sort_index()
    return closes.loc[(closes.index <= pd.Timestamp(cutoff)) & closes.gt(0)]


def load_price_history(market, tickers, cutoff):
    all_tickers = tuple(sorted(set(tickers) | {SESSION_PROXY[market]}))

    def get_close(ticker):
        try:
            return _load_close(ticker, market, cutoff)
        except (requests.RequestException, ValueError, SyntaxError, KeyError, TypeError, IndexError):
            return pd.Series(dtype="float64")

    with ThreadPoolExecutor(max_workers=8) as pool:
        return pd.DataFrame(dict(zip(all_tickers, pool.map(get_close, all_tickers))))


def target_weights(rows, market):
    weights = plan_weights(rows)
    if weights is None or sum(weights) != 100:
        raise ValueError("목표 비중 합계를 100%로 맞춰 주세요.")
    tickers = {}
    for row, weight in zip(rows, weights):
        if not weight or not row["asset"].ticker:
            continue
        ticker = row["ticker"]
        if not valid_ticker(ticker, market):
            raise ValueError("비중이 있는 ETF의 종목코드를 확인해 주세요.")
        tickers[ticker] = tickers.get(ticker, 0.0) + float(weight / 100)
    return tickers


@dataclass
class AllocationHistory:
    daily: pd.DataFrame
    monthly: pd.Series
    equity: pd.Series


def calculate_history(prices, sessions, winter, summer, current_month):
    """전월 마지막 종가에서 시작한 자산의 월중 매수·보유 수익률."""
    sessions = pd.DatetimeIndex(sessions).sort_values().unique()
    month_days = {
        month: dates for month, dates in pd.Series(sessions, index=sessions).groupby(sessions.to_period("M"))
    }
    daily = pd.DataFrame(columns=["포트 일간", "포트 누적"])
    equity_blocks = []
    month_end = {}
    level = 1.0
    last_complete_month = None

    for month, dates in month_days.items():
        if month > current_month or month - 1 not in month_days:
            continue
        previous_close = month_days[month - 1].iloc[-1]
        weights = summer if 5 <= month.month <= 10 else winter
        prices_for_month = prices.reindex(
            index=pd.DatetimeIndex([previous_close, *dates]), columns=list(weights),
        )
        complete = (prices_for_month.notna() & prices_for_month.gt(0)).all(axis=1)
        if month == current_month:
            # 최신 종가가 아직 안 들어왔으면 데이터가 연속으로 있는 날까지만 표시한다.
            prices_for_month = prices_for_month.loc[complete.cummin()]
        elif not complete.all():
            continue
        if len(prices_for_month) < 2:
            continue
        relative = prices_for_month.div(prices_for_month.iloc[0])
        wealth = 1.0 - sum(weights.values()) + relative.mul(pd.Series(weights, dtype=float)).sum(axis=1)

        if month == current_month:
            daily = pd.DataFrame({
                "포트 일간": wealth.pct_change(fill_method=None).iloc[1:],
                "포트 누적": wealth.iloc[1:] - 1.0,
            })
            continue
        month_end[month] = float(wealth.iloc[-1] - 1.0)
        if last_complete_month != month - 1:
            equity_blocks = [wealth.iloc[:1]]
            level = 1.0
        equity_blocks.append(wealth.iloc[1:] * level)
        level *= float(wealth.iloc[-1])
        last_complete_month = month

    monthly = pd.Series(month_end, dtype=float, name="월 수익률")
    if not monthly.empty:
        monthly = monthly.reindex(pd.period_range(monthly.index[0], monthly.index[-1], freq="M"))
    equity = pd.concat(equity_blocks) if equity_blocks else pd.Series(dtype=float)
    return AllocationHistory(daily, monthly, equity)
