"""기존 전략 엔진으로 종합 화면의 현재월과 이후 확정월을 계산."""
import numpy as np
import pandas as pd
import streamlit as st

from utils import calculator as ca, snowball as sb
from utils.data_loader import get_folder_hash, load_archive_data
from utils.snowball_daily import SNAPSHOTS, holding_weights, month_performance, read_snapshot, signal_for_month
from utils.three_strategy import SNOW, VERIFIED_HISTORY_END


KOSPI_RANK_P = (1, 6)
KOSPI_RANK_S = (1, 2)
KOSPI_CUT = 30
KOSPI_TIMING_MONTHS = 6
KOSPI_COST_PCT = .25
KOSPI_ENSEMBLE_COLUMN = "앙상블 (50:50 전략)"


@st.cache_data(ttl=900, show_spinner=False)
def kospi_results():
    records = load_archive_data("archive_kospi", get_folder_hash("archive_kospi"))
    if records.empty:
        return pd.DataFrame()
    records = records.assign(종목코드=records["종목코드"].astype(str).str.zfill(6))
    records = records[records["종목코드"].str.endswith("0")].copy()
    for col in ["시가총액", "종가", "거래량", "1개월(%)", "3개월(%)", "6개월(%)", "12개월(%)",
                "다음달수익률(%)", "이번달수익률"]:
        if col in records:
            records[col] = pd.to_numeric(records[col], errors="coerce").fillna(0)
    if "시가총액" in records and records["시가총액"].max() > 1e9:
        records["시가총액"] /= 1e8
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
    import FinanceDataReader as fdr
    try:
        fx = fdr.DataReader("USD/KRW", start, end)["Close"].dropna().sort_index()
        values = fx.groupby(pd.DatetimeIndex(fx.index).to_period("M")).last().pct_change()
        return values
    except (OSError, KeyError, ValueError, IndexError):
        return pd.Series(dtype=float)


@st.cache_data(ttl=900, show_spinner=False)
def snowball_current(month):
    key = pd.Period(month, freq="M")
    snapshots = {m: read_snapshot(path) for m, path in SNAPSHOTS.items()}
    info = {}
    for name, (_, signals) in snowball_inputs().items():
        market = "US" if name == "meritz" else "KR"
        alias = sb.mamtax_live_ticker if name == "ddo_pension" else str
        signal = signal_for_month(signals, key-1)
        weights = holding_weights(signal, alias)
        if not weights:
            continue
        performance = month_performance(snapshots[market], weights, key)
        data = {
            "hold": " · ".join(f"{ticker} {w:.0%}" for ticker, w in weights.items()),
            "mode": "방어" if signal.get("defensive") else "공격",
        }
        if not performance.empty:
            data["date"] = performance.index[-1].date().isoformat()
            data["local"] = float(performance["포트 누적"].iloc[-1])
            if market == "KR":
                data["krw"] = data["local"]
            else:
                end = performance.index[-1] + pd.Timedelta(days=1)
                fx = fx_monthly((key-1).start_time, end)
                if pd.notna(fx.get(key, np.nan)):
                    data["krw"] = (1+data["local"])*(1+fx[key])-1
        info[name] = data
    return info


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
