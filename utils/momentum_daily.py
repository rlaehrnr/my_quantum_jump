"""월별 모멘텀 페이지의 보유 종목 일봉과 성과 계산."""

from concurrent.futures import ThreadPoolExecutor

import FinanceDataReader as fdr
import pandas as pd
import streamlit as st

from utils.calculator import get_gold_krw_daily, get_kospi_inverse_daily
from utils.kr_index import load_kr_index
from utils.kr_inverse import KOSPI_INVERSE_CODE
from utils.snowball_daily import month_performance
from utils.ui_components import render_daily_performance


def _read_close(reader, *args):
    try:
        close = pd.to_numeric(reader(*args)["Close"], errors="coerce")
    except Exception:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    return close[close.gt(0) & ~close.index.duplicated(keep="last")].sort_index()


def _read_stock_close(ticker, start, end):
    # Yahoo's end date is exclusive. Trim to the market sessions after fetching.
    return _read_close(fdr.DataReader, ticker.replace(".", "-"), start, end + pd.Timedelta(days=1))


@st.cache_data(ttl=900, max_entries=64, show_spinner=False)
def _market_sessions(market, start, end):
    if market == "KR":
        close = _read_close(load_kr_index, "KOSPI", start, end)
    else:
        close = _read_stock_close("SPY", start, end)
    return close.loc[start:end].index


@st.cache_data(ttl=900, max_entries=128, show_spinner=False)
def load_holding_closes(market, tickers, start, end):
    sessions = _market_sessions(market, start, end)
    if sessions.empty or not tickers:
        return pd.DataFrame(index=sessions)

    special = {"GOLD_KRW": get_gold_krw_daily}
    if market == "KR":
        special[KOSPI_INVERSE_CODE] = get_kospi_inverse_daily
    stock_tickers = [ticker for ticker in tickers if ticker not in special]

    def stock_close(ticker):
        # 월간 수집기와 같은 FDR 티커 형식(예: BRK.B → BRK-B).
        return _read_stock_close(ticker, start, end)

    prices = {}
    if stock_tickers:
        with ThreadPoolExecutor(max_workers=min(6, len(stock_tickers))) as pool:
            prices.update(zip(stock_tickers, pool.map(stock_close, stock_tickers)))
    for ticker in tickers:
        if ticker in special:
            prices[ticker] = special[ticker]()
    return pd.DataFrame(prices, index=sessions)


def kospi_holding_weights(perfect, running):
    """50:50 앙상블과 중복 제외 통합 전략의 월초 비중."""
    perfect, running = tuple(dict.fromkeys(perfect)), tuple(dict.fromkeys(running))
    ensemble = {}
    for group in (perfect, running):
        group = group or ("CASH",)
        for ticker in group:
            ensemble[ticker] = ensemble.get(ticker, 0.0) + 0.5 / len(group)
    unique = tuple(dict.fromkeys(perfect + running))
    integrated = dict.fromkeys(unique, 1 / len(unique)) if unique else {}
    return ensemble, integrated


def usa500_holding_weights(original, residual, original_ranks, residual_ranks):
    """두 순위 구간에 절반씩 균등 배분하고 중복 종목 비중을 합산한다."""
    weights = {}
    for ranked, (first, last) in ((original, original_ranks), (residual, residual_ranks)):
        selected = ranked[first - 1:last]
        if len(set(selected)) != last - first + 1:
            return {}
        for ticker in selected:
            weights[ticker] = weights.get(ticker, 0.0) + 0.5 / len(selected)
    return weights


def holding_performance(market, tickers, month, *, weights=None):
    """월초에 정한 비중으로 계속 보유한 가격 성과. 현금은 거래일마다 0%."""
    tickers = tuple(dict.fromkeys(tickers))
    if not tickers:
        return pd.DataFrame()

    # 장중 시세가 확정 종가로 들어가지 않도록 현지 정규장 종료 전에는 전일까지 사용한다.
    timezone, close_hour, close_minute = ("Asia/Seoul", 15, 30) if market == "KR" else (
        "America/New_York", 16, 0
    )
    now = pd.Timestamp.now(tz=timezone).tz_localize(None)
    last_closed = now.normalize()
    if (now.hour, now.minute) < (close_hour, close_minute):
        last_closed -= pd.Timedelta(days=1)

    start = (month - 1).start_time
    end = min(last_closed, month.end_time.normalize())
    if end < month.start_time:
        return pd.DataFrame()

    daily = load_holding_closes(market, tuple(sorted(set(tickers) - {"CASH"})), start, end)
    if "CASH" in tickers:
        daily = daily.assign(CASH=1.0)
    if weights is None:
        weights = dict.fromkeys(tickers, 1 / len(tickers))
    return month_performance(daily, weights, month)


def render_holding_performance(market, holdings, month, key, *, weights=None):
    if not holdings:
        st.caption("선택한 순위 구간에 보유 종목이 없습니다.")
        return
    performance = holding_performance(market, holdings, month, weights=weights)
    if performance.empty:
        st.caption("보유 종목의 전월 말과 선택한 달의 종가가 모두 준비되면 표시됩니다.")
        return

    latest = performance.iloc[-1]
    st.metric(f"{month.month}월 누적", f'{latest["포트 누적"]:+.2%}')
    st.caption(
        f"{performance.index[-1]:%Y-%m-%d} 종가까지 · "
        + " · ".join(f'{name} ({latest[f"{ticker} 누적"]:+.2%})' for ticker, name in holdings.items())
    )
    labels = {f"{ticker} {period}": f"{name} {period}"
              for ticker, name in holdings.items() for period in ("일간", "누적")}
    render_daily_performance(performance, key, labels)
