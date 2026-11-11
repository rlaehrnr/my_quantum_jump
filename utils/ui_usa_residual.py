from pathlib import Path

import pandas as pd
import streamlit as st

from utils.us_helpers import SPY_TIMING_MA_MONTHS, get_spx_history_cached, run_backtest_triple_us_m4
from utils.us_residual_backtest import run_residual_backtest


RESEARCH = Path(__file__).resolve().parents[1] / "기록" / "2026-11-10-USA500-잔차모멘텀"
SCORE_CASE = "supplemented_lag2"
RESULT_KEY = "usa500_residual_result"


@st.cache_data(max_entries=2, show_spinner=False)
def _load_scores(path):
    scores = pd.read_csv(path, usecols=["case", "month", "ticker", "score"],
                         dtype={"ticker": str, "month": str})
    return scores.loc[scores.case.eq(SCORE_CASE), ["month", "ticker", "score"]].copy()


def _equity(returns):
    equity = (1 + returns).cumprod()
    initial = pd.DataFrame(1.0, columns=returns.columns,
                           index=[str(pd.Period(returns.index[0], freq="M") - 1)])
    return pd.concat([initial, equity])


def _summary(gross, net):
    result = {}
    for label, returns in [("비용 전", gross), ("비용 후", net)]:
        equity = _equity(returns)
        result[f"{label} CAGR"] = equity.iloc[-1].pow(12 / len(returns)) - 1
        result[f"{label} MDD"] = (equity / equity.cummax() - 1).min()
    return pd.DataFrame(result).rename_axis("전략").reset_index()


def render_residual_backtest(master, default_cutoff, default_ranks):
    score_path = RESEARCH / "signal_scores.csv.gz"
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
        f"잔차 점수 제공 기간 {months[0]} ~ {months[-1]} · "
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
            residual_ranks = st.slider("잔차 매수 순위", 1, 50, (1, 6))
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
        with st.spinner("같은 투자월에서 세 전략을 비교하는 중입니다."):
            scores = _load_scores(str(score_path))
            if not set(selected_months).issubset(scores.month):
                st.error("선택 기간에 잔차 점수가 누락된 달이 있습니다.")
                return
            original, _ = run_backtest_triple_us_m4(
                scoped, int(start[:4]), int(end[:4]), ma_months, apply_timing, use_multi4,
                cutoff, *original_ranks, get_spx_history_cached() if apply_timing else pd.DataFrame(),
                universe,
            )
            invested = original.set_index("투자월")["invested"]
            result = run_residual_backtest(
                scoped, scores, invested, universe=universe, cutoff=cutoff,
                original_ranks=original_ranks, residual_ranks=residual_ranks, fee=fee_pct / 100,
            )
            st.session_state[RESULT_KEY] = (result, fee_pct, original_ranks, residual_ranks)

    saved = st.session_state.get(RESULT_KEY)
    if saved is None:
        return
    result, fee_pct, original_ranks, residual_ranks = saved
    gross, net = result["gross"], result["net"]
    st.caption(
        f"{net.index[0]} ~ {net.index[-1]} · {len(net)}개월 · "
        f"기존 {original_ranks[0]}~{original_ranks[1]}위 · 잔차 {residual_ranks[0]}~{residual_ranks[1]}위 · "
        f"매수·매도 각각 {fee_pct:.2f}% · 월말 MDD"
    )
    stats = _summary(gross, net)
    st.dataframe(stats.style.format("{:.2%}", subset=stats.columns[1:]), hide_index=True)
    equity = _equity(net) * 100
    equity.index = pd.to_datetime(equity.index, format="%Y-%m")
    st.markdown("#### 누적 자산 · 비용 후 · 시작 100")
    st.line_chart(equity)
    with st.expander("월별 수익률"):
        monthly = pd.concat({"비용 전": gross, "비용 후": net}, axis=1)
        monthly.columns = [f"{strategy} ({cost})" for cost, strategy in monthly.columns]
        monthly.index.name = "투자월"
        st.dataframe(monthly.style.format("{:.2%}"))
