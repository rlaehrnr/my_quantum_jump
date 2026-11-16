import csv
from io import BytesIO, StringIO
from pathlib import Path
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

import numpy as np
import pandas as pd
import streamlit as st

from utils.data_loader import load_archive_data
from utils.ui_components import apply_custom_total_styling, get_monthly_heatmap, us_main_cfg
from utils.us_helpers import SPY_TIMING_MA_MONTHS, add_naver_links, get_spx_history_cached, run_backtest_triple_us_m4
from utils.us_residual_backtest import RESIDUAL_DEFAULT_RANKS, calculate_residual_scores, run_residual_backtest


RESEARCH = Path(__file__).resolve().parents[1] / "기록" / "2026-11-10-USA500-잔차모멘텀"
SCORE_CASE = "supplemented_lag2"
SCORE_FILE = RESEARCH / "signal_scores.csv.gz"
FACTOR_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"
)
RESULT_KEY = "usa500_residual_result"
SP500_LABEL = "S&P 500 (가격 지수)"
RESIDUAL_RANKING_HELP = (
    "**잔차**는 실제 월수익률에서 시장 전체, 기업 규모, 가치주·성장주 차이로 "
    "모형이 설명한 수익률을 뺀 값이에요.\n\n"
    "예를 들어 실제로 +8% 올랐고 모형이 설명한 수익률이 +5%라면, "
    "잔차는 **+3%p**예요.\n\n"
    "순위는 직전 1개월을 건너뛴 11개월의 **평균 잔차 ÷ 잔차의 표준편차**로 매겨요. "
    "꾸준히 모형보다 좋은 성과를 낸 종목이 높은 점수를 받는 방식이에요."
)


@st.cache_data(max_entries=2, show_spinner=False)
def _load_scores(path):
    scores = pd.read_csv(path, usecols=["case", "month", "ticker", "score"],
                         dtype={"ticker": str, "month": str})
    return scores.loc[scores.case.eq(SCORE_CASE), ["month", "ticker", "score"]].copy()


def _parse_factors(content):
    rows = [row for row in csv.reader(StringIO(content))
            if len(row) == 5 and len(row[0].strip()) == 6 and row[0].strip().isdigit()]
    factors = pd.DataFrame(rows, columns=["month", "Mkt-RF", "SMB", "HML", "RF"])
    factors.index = pd.PeriodIndex(factors.pop("month").str.strip(), freq="M")
    factors = factors.apply(pd.to_numeric, errors="coerce").replace([-99.99, -999], np.nan)
    return factors / 100


@st.cache_data(ttl=21600, show_spinner=False)
def _load_new_factors():
    try:
        with urlopen(FACTOR_URL, timeout=5) as response:
            with ZipFile(BytesIO(response.read())) as archive:
                content = archive.read(archive.namelist()[0]).decode("utf-8-sig")
        return _parse_factors(content)
    except (OSError, BadZipFile, ValueError, IndexError):
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def _supplemental_returns():
    path = RESEARCH / "downloaded_monthly_prices.csv.gz"
    if not path.is_file():
        return pd.DataFrame(dtype=float)
    data = pd.read_csv(path, usecols=["month", "ticker", "Adj Close"], dtype={"ticker": str})
    data["month"] = pd.PeriodIndex(data["month"], freq="M")
    close = data.pivot(index="month", columns="ticker", values="Adj Close").sort_index()
    months = pd.period_range(close.index.min(), close.index.max(), freq="M")
    return close.reindex(months).pct_change(fill_method=None)


@st.cache_data(ttl=21600, max_entries=16, show_spinner=False)
def _new_scores(month, tickers, archive_path, folder_hash):
    period = pd.Period(month, freq="M")
    end = period - 2
    window = pd.period_range(end=end, periods=36, freq="M")
    factors = _parse_factors((RESEARCH / "F-F_Research_Data_Factors.csv").read_text(encoding="utf-8-sig"))
    if factors.reindex(window).isna().any().any():
        fresh = _load_new_factors()
        if not fresh.empty:
            factors = fresh.combine_first(factors)
    if factors.reindex(window).isna().any().any():
        return pd.Series(dtype=float)

    raw = load_archive_data(archive_path, folder_hash)
    historical_month = pd.to_datetime(raw["종목선정일"], errors="coerce").dt.to_period("M") + 1
    scoped = raw.loc[historical_month.isin(window) & raw["종목코드"].isin(tickers)]
    history = scoped.assign(
        month=historical_month.loc[scoped.index],
        ret=pd.to_numeric(scoped["이번달수익률"], errors="coerce") / 100,
    )
    archive = history.pivot(index="month", columns="종목코드", values="ret").reindex(columns=list(tickers))
    return calculate_residual_scores(period, archive, _supplemental_returns(), factors)


def _ranking_table(candidates, scores, returns):
    ranked = (candidates.assign(**{"잔차 점수": candidates["종목코드"].map(scores)})
              .dropna(subset=["잔차 점수"])
              .sort_values(["잔차 점수", "종목코드"], ascending=[False, True])
              .head(10)
              .reset_index(drop=True))
    ranked["순위"] = range(1, len(ranked) + 1)
    ranked["이번달수익률"] = ranked["종목코드"].map(returns)
    return ranked


def _render_ranking_table(ranked, *, key):
    control, result = st.columns([1, 2])
    with control:
        start, end = 1, len(ranked)
        if end > 1:
            start, end = st.slider(
                "잔차 순위 범위", 1, end, (1, min(end, RESIDUAL_DEFAULT_RANKS[1])), key=key,
            )
    picked = ranked.iloc[start - 1:end]
    realized = picked["이번달수익률"].dropna()
    with result:
        if realized.empty:
            st.markdown(f"**{start}~{end}위 평균 수익률** · 수익률 자료 없음")
        else:
            coverage = f" · 수익률 확인 {len(realized)}/{len(picked)}종" if len(realized) < len(picked) else ""
            st.markdown(f"**{start}~{end}위 평균 수익률 {realized.mean():+.2f}%**{coverage}")
    columns = ["순위", "통합티커_L", "종목명_L", "잔차 점수", "이번달수익률"]
    styled = ranked.style.apply(apply_custom_total_styling, top_codes=picked["종목코드"].tolist(), axis=1)
    config = {**us_main_cfg, "잔차 점수": st.column_config.NumberColumn(format="%.4f")}
    st.dataframe(styled, width="stretch", hide_index=True, column_order=columns, column_config=config)


def render_residual_ranking(master, month, archive_path, folder_hash, *, key, daily_returns=None):
    st.markdown("#### 잔차 모멘텀 순위", help=RESIDUAL_RANKING_HELP)
    candidates = (master.loc[master["투자월"].eq(month)]
                  .sort_values("시가총액", ascending=False).head(500))
    if candidates.empty:
        st.caption(f"{month} 투자월 종목 자료가 아직 없습니다.")
        return

    saved = _load_scores(str(SCORE_FILE)) if SCORE_FILE.is_file() else pd.DataFrame(columns=["month", "ticker", "score"])
    scores = saved.loc[saved.month.eq(month)].set_index("ticker")["score"]
    if scores.empty and (saved.empty or month > saved.month.max()):
        scores = _new_scores(month, tuple(candidates["종목코드"]), archive_path, folder_hash)
    if daily_returns is None:
        raw = load_archive_data(archive_path, folder_hash)
        monthly = raw.loc[raw["투자월"].eq(month)].set_index("종목코드")["이번달수익률"]
        returns = pd.to_numeric(monthly, errors="coerce")
    else:
        returns = daily_returns
    ranked = _ranking_table(candidates, scores, returns)
    if ranked.empty:
        st.caption(f"{month} 투자월 잔차 점수에 필요한 월간 가격 또는 요인 자료가 아직 없습니다.")
        return

    eligible = candidates["종목코드"].isin(scores.index).sum()
    end = pd.Period(month, freq="M") - 2
    daily = " · 이번달 수익률은 데일리 기준일 종가까지" if daily_returns is not None else ""
    st.caption(f"{month} 투자월 · {end}까지 36개월 회귀 · 직전 1개월 제외 · 점수 {eligible}/{len(candidates)}종{daily}")
    _render_ranking_table(add_naver_links(ranked), key=key)


def _equity(returns):
    equity = (1 + returns).cumprod()
    initial = pd.DataFrame(1.0, columns=returns.columns,
                           index=[str(pd.Period(returns.index[0], freq="M") - 1)])
    return pd.concat([initial, equity])


def _sp500_monthly_returns(prices, months):
    if prices.empty or "Close" not in prices:
        return pd.Series(index=months, dtype=float)
    close = pd.to_numeric(prices["Close"], errors="coerce").sort_index()
    month_end = close.resample("ME").last()
    returns = month_end.pct_change(fill_method=None)
    returns.index = returns.index.strftime("%Y-%m")
    return returns.reindex(months)


def _summary(gross, net, benchmark):
    benchmark = benchmark.reindex(gross.index)
    before_cost = gross.assign(**{SP500_LABEL: benchmark}) if benchmark.notna().all() else gross
    result = {}
    for label, returns in [("비용 전", before_cost), ("비용 후", net)]:
        equity = _equity(returns)
        result[f"{label} CAGR"] = equity.iloc[-1].pow(12 / len(returns)) - 1
        result[f"{label} MDD"] = (equity / equity.cummax() - 1).min()
    return pd.DataFrame(result).reindex([*gross.columns, SP500_LABEL]).rename_axis("전략").reset_index()


def render_residual_backtest(master, default_cutoff, default_ranks):
    score_path = SCORE_FILE
    period_path = RESEARCH / f"{SCORE_CASE}__original_triple_monthly.csv"
    if not score_path.is_file() or not period_path.is_file():
        st.warning("잔차 백테스트 자료를 찾을 수 없습니다.")
        return
    available = pd.read_csv(period_path, usecols=["month"])["month"]
    months = sorted(set(available) & set(master["투자월"]))
    if not months:
        st.warning("잔차 점수와 월별 수익률이 함께 있는 투자월이 없습니다.")
        return

    st.caption(
        f"잔차 점수 제공 기간 {months[0]} – {months[-1]} · "
        "36개월 요인 회귀 · 직전 1개월을 건너뛴 11개월 잔차 점수"
    )
    with st.form("usa500_residual_backtest", border=False):
        period, cap, cost = st.columns([2, 1, 1])
        with period:
            start, end = st.select_slider("투자월 범위", options=months, value=(months[0], months[-1]))
        with cap:
            universe = st.slider("시총 상위 종목 수", 50, 500, 500, step=50)
        with cost:
            fee_pct = st.number_input("편도 거래비용 (%)", 0.0, 5.0, 0.25, step=0.05, format="%.2f")
        cutoff_col, original_col, residual_col = st.columns(3)
        with cutoff_col:
            cutoff = st.number_input("기존 교집합 상위 N위", 1, 500, default_cutoff)
        with original_col:
            original_ranks = st.slider("기존 매수 순위 (12-1M)", 1, 50, default_ranks)
        with residual_col:
            residual_ranks = st.slider("잔차 매수 순위", 1, 50, RESIDUAL_DEFAULT_RANKS)
        spy_col, ma_col, multi_col = st.columns(3)
        with spy_col:
            apply_timing = st.checkbox("시장 방어 적용", value=True)
        with ma_col:
            ma_months = st.slider("SPY 이동평균 (개월)", 1, 12, SPY_TIMING_MA_MONTHS)
        with multi_col:
            use_multi4 = st.checkbox("시장 방어에 멀티4 추가", value=True)
        submitted = st.form_submit_button("잔차 백테스트 실행", type="primary")

    if submitted:
        st.session_state.pop(RESULT_KEY, None)
        selected_months = [m for m in months if start <= m <= end]
        scoped = master.loc[master["투자월"].isin(selected_months)]
        with st.spinner("같은 투자월에서 배분 방식별 성과를 계산하는 중입니다."):
            scores = _load_scores(str(score_path))
            if not set(selected_months).issubset(scores.month):
                st.error("선택 기간에 잔차 점수가 누락된 달이 있습니다.")
                return
            sp500 = get_spx_history_cached()
            original, _ = run_backtest_triple_us_m4(
                scoped, int(start[:4]), int(end[:4]), ma_months, apply_timing, use_multi4,
                cutoff, *original_ranks, sp500 if apply_timing else pd.DataFrame(),
                universe,
            )
            invested = original.set_index("투자월")["invested"]
            result = run_residual_backtest(
                scoped, scores, invested, universe=universe, cutoff=cutoff,
                original_ranks=original_ranks, residual_ranks=residual_ranks, fee=fee_pct / 100,
            )
            result["benchmark"] = _sp500_monthly_returns(sp500, invested.index)
            st.session_state[RESULT_KEY] = (result, fee_pct, original_ranks, residual_ranks)

    saved = st.session_state.get(RESULT_KEY)
    if saved is None:
        return
    result, fee_pct, original_ranks, residual_ranks = saved
    gross, net = result["gross"], result["net"]
    st.caption(
        f"{net.index[0]} – {net.index[-1]} · {len(net)}개월 · "
        f"기존 {original_ranks[0]}–{original_ranks[1]}위 · 잔차 {residual_ranks[0]}–{residual_ranks[1]}위 · "
        f"매수·매도 각각 {fee_pct:.2f}% · 월말 MDD"
    )
    st.caption("50:50은 전략별로 자금을 반씩 나눕니다. 종목 균등 배분은 두 목록을 합쳐 겹치는 종목을 한 번만 셉니다.")
    benchmark = result.get("benchmark")
    if benchmark is None:
        benchmark = pd.Series(index=gross.index, dtype=float)
        st.caption("백테스트를 다시 실행하면 S&P 500 비교 결과가 표시됩니다.")
    elif benchmark.isna().any():
        st.caption("선택한 기간의 S&P 500 가격 이력이 일부 없어 지수 성과를 표시할 수 없습니다.")
    stats = _summary(gross, net, benchmark)
    st.dataframe(stats.style.format("{:.2%}", subset=stats.columns[1:], na_rep="—"), hide_index=True)
    st.caption("S&P 500은 같은 기간의 월말 가격 지수 수익률입니다. 배당과 거래비용은 제외합니다.")
    equity = _equity(net) * 100
    equity.index = pd.to_datetime(equity.index, format="%Y-%m")
    st.markdown("#### 누적 자산 · 비용 후 · 시작 100")
    st.line_chart(equity)

    st.markdown("#### 월별 수익률 히트맵")
    heatmap_cost = st.radio("히트맵 수익률 기준", ["비용 후", "비용 전"], horizontal=True)
    heatmap_returns = net if heatmap_cost == "비용 후" else gross
    heatmap_input = (heatmap_returns * 100).rename_axis("투자월").reset_index()
    for tab, strategy in zip(st.tabs(list(heatmap_returns.columns)), heatmap_returns.columns):
        with tab:
            st.dataframe(get_monthly_heatmap(heatmap_input, strategy), width="stretch")

    with st.expander("월별 수익률"):
        monthly = pd.concat({"비용 전": gross, "비용 후": net}, axis=1)
        monthly.columns = [f"{strategy} ({cost})" for cost, strategy in monthly.columns]
        monthly.index.name = "투자월"
        st.dataframe(monthly.style.format("{:.2%}"))
