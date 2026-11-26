"""기존 전략 엔진으로 종합 화면의 현재월과 이후 확정월을 계산."""
from dataclasses import dataclass

import FinanceDataReader as fdr
import pandas as pd
import streamlit as st

from utils import calculator as ca, snowball as sb
from utils.data_loader import get_folder_hash, load_archive_data
from utils.kr_inverse import KOSPI_INVERSE_CODE, KOSPI_INVERSE_NAME
from utils.momentum_daily import holding_performance, kospi_holding_weights
from utils.snowball_daily import (
    SNAPSHOTS, combine_month_performance, holding_weights, month_performance, read_snapshot, signal_for_month,
)
from utils.three_strategy import LEG_LABELS, SNOW, VERIFIED_HISTORY_END
from utils.three_strategy_store import smallcap_positions


KOSPI_RANK_P = (1, 6)
KOSPI_RANK_S = (1, 2)
KOSPI_CUT = 30
KOSPI_TIMING_MONTHS = 6
KOSPI_COST_PCT = .25
KOSPI_ENSEMBLE_COLUMN = "앙상블 (50:50 전략)"
KOSPI_DEFENSE = {"금": ("GOLD_KRW", "국내 금"), "현금": ("CASH", "현금"),
                 "인버스": (KOSPI_INVERSE_CODE, KOSPI_INVERSE_NAME)}
SNOW_HOLDING_NAMES = {
    "mam_isa": sb.PEN_TICKER_NAMES,
    "ddo_pension": sb.MAMTAX_TICKER_NAMES,
    "sso_pension": sb.SSOPEN_TICKER_NAMES,
}


@dataclass
class CurrentHoldings:
    holdings: pd.DataFrame
    performance: pd.DataFrame
    note: str = ""


def kospi_records():
    path = "archive_kospi"
    records = load_archive_data(path, get_folder_hash(path))
    if records.empty:
        return records
    records = records.assign(종목코드=records["종목코드"].astype(str).str.zfill(6))
    records = records[records["종목코드"].str.endswith("0")].copy()
    for col in ["시가총액", "종가", "거래량", "1개월(%)", "3개월(%)", "6개월(%)", "12개월(%)",
                "다음달수익률(%)", "이번달수익률"]:
        if col in records:
            records[col] = pd.to_numeric(records[col], errors="coerce").fillna(0)
    if "시가총액" in records and records["시가총액"].max() > 1e9:
        records["시가총액"] /= 1e8
    return records


@st.cache_data(ttl=900, show_spinner=False)
def kospi_results():
    records = kospi_records()
    if records.empty:
        return pd.DataFrame()
    yrs = records["투자연도"].astype(int)
    output, _, _ = ca.run_backtest_k200(
        records, yrs.min(), yrs.max(), KOSPI_TIMING_MONTHS, True,
        KOSPI_RANK_P, KOSPI_RANK_S, KOSPI_CUT, KOSPI_CUT,
        trading_cost_pct=KOSPI_COST_PCT, gold_returns=ca.get_gold_returns(),
        use_gold=True, use_gold_ma=True, gold_ma_months=ca.KOREA_GOLD_DEFENSE_MA_MONTHS,
        use_inverse=ca.KOSPI_USE_INVERSE,
        inverse_returns=ca.get_kospi_inverse_returns() if ca.KOSPI_USE_INVERSE else {},
    )
    return output.set_index("투자월") if not output.empty else output


@st.cache_data(ttl=900, show_spinner=False)
def snowball_inputs():
    us = sb.load_monthly_prices()
    mom = sb.load_pen_prices()
    ddo = sb.load_mamtax_prices()
    sso = sb.load_ssopen_prices()
    return {
        "meritz": (us, sb.compute_signals(us, sb.load_dividend_yield())),
        "mam_isa": (mom, sb.compute_signals_pension(mom)),
        "ddo_pension": (ddo, sb.compute_signals_mamtax(ddo, us)),
        "sso_pension": (sso, sb.compute_signals_ssopen(sso, us)),
    }


@st.cache_data(ttl=900, show_spinner=False)
def fx_monthly(start, end):
    try:
        fx = fdr.DataReader("USD/KRW", start, end)["Close"].dropna().sort_index()
        values = fx.groupby(pd.DatetimeIndex(fx.index).to_period("M")).last().pct_change()
        return values
    except (OSError, KeyError, ValueError, IndexError):
        return pd.Series(dtype=float)


def combine_daily(curves, amounts):
    """모든 양수 비중이 관측된 종가일을 사용한다."""
    selected = {key: value for key, value in amounts.items() if value > 0}
    if not selected or not selected.keys() <= curves.keys():
        return pd.DataFrame()
    common = pd.concat({key: curves[key] for key in selected}, axis=1, join="inner").dropna()
    return combine_month_performance(dict(common.items()), selected)


def kospi_current(month):
    records = kospi_records()
    if records.empty:
        return CurrentHoldings(pd.DataFrame(), pd.DataFrame())
    rows = records.loc[records["투자월"].eq(str(month))]
    previous = records.loc[records["투자월"].eq(str(month - 1))]
    status = ca.get_korea_market_status(rows, previous)
    if status is None:
        return CurrentHoldings(pd.DataFrame(), pd.DataFrame())
    if status["stop"]:
        ticker, name = KOSPI_DEFENSE[status["defense_asset"]]
        weights, names = {ticker: 1.0}, {ticker: name}
    else:
        _, perfect, running = ca.get_strategy_stocks_korea(rows)
        perfect = perfect.iloc[KOSPI_RANK_P[0] - 1:KOSPI_RANK_P[1]]
        running = running.iloc[KOSPI_RANK_S[0] - 1:KOSPI_RANK_S[1]]
        weights, _ = kospi_holding_weights(perfect["종목코드"], running["종목코드"])
        names = dict(zip(rows["종목코드"], rows["종목명"])) | {"CASH": "현금"}
    holdings = pd.DataFrame([
        {"종목명": names[ticker], "종목코드": ticker if ticker != "CASH" else "",
         "보유 비중": weight}
        for ticker, weight in weights.items()
    ])
    performance = holding_performance("KR", tuple(weights), month, weights=weights)
    return CurrentHoldings(holdings, performance[["포트 일간", "포트 누적"]] if not performance.empty else performance)


@st.cache_data(ttl=900, show_spinner=False)
def fx_daily(start, end):
    try:
        close = pd.to_numeric(fdr.DataReader("USD/KRW", start, end)["Close"], errors="coerce")
    except Exception:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    return close[close.gt(0) & ~close.index.duplicated(keep="last")].sort_index()


def usd_curve_to_krw(curve, fx, base_date):
    anchor = fx.loc[:base_date]
    if anchor.empty:
        return curve.iloc[:0]
    return (curve.add(1) * fx.reindex(curve.index) / anchor.iloc[-1] - 1).dropna()


def snowball_current(month):
    snapshots = {m: read_snapshot(path) for m, path in SNAPSHOTS.items()}
    curves, holdings = {}, []
    for name, (_, signals) in snowball_inputs().items():
        market = "US" if name == "meritz" else "KR"
        alias = sb.mamtax_live_ticker if name == "ddo_pension" else str
        signal = signal_for_month(signals, month - 1)
        weights = holding_weights(signal, alias)
        if not weights:
            continue
        names = SNOW_HOLDING_NAMES.get(name, {})
        holdings.extend(
            {"전략": LEG_LABELS[name], "국면": "방어" if signal.get("defensive") else "공격",
             "종목명": "현금" if ticker == "CASH" else names.get(ticker, ticker),
             "종목코드": ticker if ticker != "CASH" else "", "보유 비중": weight}
            for ticker, weight in weights.items()
        )
        daily = snapshots[market]
        performance = month_performance(daily, weights, month)
        if performance.empty:
            continue
        curve = performance["포트 누적"]
        if market == "US":
            base_date = daily.index[daily.index.to_period("M") == month - 1][-1]
            fx = fx_daily((month - 1).start_time, curve.index[-1] + pd.Timedelta(days=1))
            curve = usd_curve_to_krw(curve, fx, base_date)
        if not curve.empty:
            curves[name] = curve
    return curves, pd.DataFrame(holdings)


def smallcap_current(month):
    positions, unread = smallcap_positions()
    holdings = positions[["계좌", "종목명", "종목코드"]]
    if unread:
        return CurrentHoldings(holdings, pd.DataFrame(), "보유 자료를 읽지 못한 계좌 · " + ", ".join(unread))
    tickers = tuple(holdings["종목코드"].unique())
    performance = holding_performance("KR", tickers, month)
    return CurrentHoldings(holdings, performance[["포트 일간", "포트 누적"]] if not performance.empty else performance)


@st.cache_data(ttl=1800, show_spinner=False)
def extend_history(history, last_closed):
    """최근 운영 월의 이력만 채운다. 소형주 실현 월수익은 시트가 원본이다."""
    later = history.loc[(history.index > VERIFIED_HISTORY_END) & (history.index <= last_closed)]
    if later.empty or not later["small"].notna().any():
        return history
    history = history.copy()
    dates = later.index[later["small"].notna()]
    engine = kospi_results()
    if KOSPI_ENSEMBLE_COLUMN in engine:
        history.loc[dates, "kospi"] = history.loc[dates, "kospi"].fillna(
            (engine[KOSPI_ENSEMBLE_COLUMN]/100).reindex(dates))
    funcs = (sb.run_backtest, sb.run_backtest_pension, sb.run_backtest_mamtax, sb.run_backtest_ssopen)
    fx = fx_monthly((pd.Period(dates[0], freq="M")-1).start_time,
                    (pd.Period(dates[-1], freq="M")+1).start_time)
    for key, backtest in zip(SNOW, funcs):
        prices, signals = snowball_inputs()[key]
        bt = backtest(prices, signals)
        if bt.empty:
            continue
        values = bt.set_index("hold_month")["ret_strategy"].reindex(dates)
        if key == "meritz":
            inflation = fx.reindex(pd.PeriodIndex(dates, freq="M")).set_axis(dates)
            values = (1+values)*(1+inflation)-1
        history.loc[dates, key] = history.loc[dates, key].fillna(values)
    return history
