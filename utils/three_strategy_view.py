"""3전략 조합 홈의 배분, 월중 보유 성과와 확정월 백테스트."""
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import three_strategy_live as live
from utils.snowball_allocation import portfolio_stats
from utils.three_strategy import (
    Allocation, DEFAULT_ALLOCATION, LEG_LABELS, LEGS, SNOW, VERIFIED_HISTORY_END,
    backtest_window, combine, current_month, ratio_part,
)
from utils.three_strategy_preferences import (
    HOME_ICON, HOME_TITLE, STRATEGY_PAGES, STRATEGY_TAB_PARAM, current_allocation, save_preferences, share_url,
)
from utils.three_strategy_store import load_history
from utils.ui_components import get_mdd_history, get_monthly_heatmap, inject_custom_css, render_daily_performance


OUTER_LABELS = ("코스피200", "스노우볼", "소형주 퀀트")
INNER_LABELS = tuple(LEG_LABELS[key] for key in SNOW)
PCT = st.column_config.NumberColumn(format="percent")


def _allocation_summary(allocation):
    with st.container(border=True):
        st.subheader("현재 투자비율")
        *metrics, edit = st.columns([1, 1, 1, 1.05], vertical_alignment="center")
        total = sum(allocation.outer)
        for column, label, part in zip(metrics, OUTER_LABELS, allocation.outer):
            column.metric(label, f"{part / total:.1%}", border=True)
        with edit:
            with st.popover("비율 수정", icon=":material/tune:", width="stretch"):
                with st.form(f"three_ratio_form_{allocation.encode()}"):
                    st.markdown("**3전략 비율**")
                    outer = tuple(st.number_input(label, min_value=0.0, value=float(part), step=1.0)
                                  for label, part in zip(OUTER_LABELS, allocation.outer))
                    st.markdown("**스노우볼 내부 비율**")
                    inner = tuple(st.number_input(label, min_value=0.0, value=float(part), step=1.0)
                                  for label, part in zip(INNER_LABELS, allocation.inner))
                    save, reset = st.columns(2)
                    submitted = save.form_submit_button("비율 저장", type="primary")
                    restored = reset.form_submit_button("기본값 복원")
                if submitted or restored:
                    try:
                        edited = DEFAULT_ALLOCATION if restored else Allocation(outer, inner)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        save_preferences(edited)
                        st.rerun()
                url = share_url(allocation)
                if url:
                    st.markdown(f"[현재 비율 공유 링크]({url})")
        if sum(allocation.inner):
            st.caption("스노우볼 내부 · " + "  /  ".join(
                f"{label} {ratio_part(part)}" for label, part in zip(INNER_LABELS, allocation.inner)
            ))


def _read_current(loader, month):
    try:
        return loader(month), False
    except Exception:
        return None, True


def _daily_panel(performance, key, labels, note, *, common_dates=False):
    if performance.empty:
        st.info(note)
        return
    st.metric("이번 달 누적", f"{performance['포트 누적'].iloc[-1]:+.2%}")
    first_row = " · 첫 행은 전월 말 대비" if common_dates else ""
    st.caption(f"{performance.index[-1]:%Y-%m-%d} 종가까지{first_row}")
    if common_dates:
        labels = labels | {"포트 일간": "직전 공통일 대비"}
    render_daily_performance(performance, key, labels, date_label="공통 종가일" if common_dates else "거래일")


def _strategy_panel(key, current, failed, labels):
    _, page, title = STRATEGY_PAGES[key]
    with st.container(key=f"three-strategy-detail-title-{key}"):
        st.page_link(page, label=title, icon=":material/arrow_outward:")
    if failed:
        st.warning("보유 자료를 불러오지 못했습니다.")
        return
    if current.note:
        st.warning(current.note)
    if current.holdings.empty:
        if current.note:
            return
        st.info("등록된 보유 종목이 없습니다." if key == "small" else "이번 달의 확정 보유 자료를 기다리고 있습니다.")
        return
    st.markdown("**현재 보유**")
    st.dataframe(current.holdings, hide_index=True, width="stretch", column_config={"보유 비중": PCT})
    if current.note:
        return
    if key == "small":
        st.caption("현재 등록 수량을 월초부터 보유했다고 가정한 가격 수익률입니다. 매매·입출금은 반영하지 않습니다.")
    _daily_panel(current.performance, key, labels, "전월 말과 이번 달의 보유 종목 종가가 준비되면 표시됩니다.",
                 common_dates=key == "snowball")


@st.fragment(run_every="60s")
def _current_section(allocation, active_tab):
    month = pd.Period(current_month(), freq="M")
    kospi, kospi_failed = _read_current(live.kospi_current, month)
    snowball, snowball_failed = _read_current(live.snowball_current, month)
    small, small_failed = _read_current(live.smallcap_current, month)
    snow_curves, snow_holdings = snowball if snowball is not None else ({}, pd.DataFrame())
    snow_daily = live.combine_daily(snow_curves, dict(zip(SNOW, allocation.inner)))
    empty = live.CurrentHoldings(pd.DataFrame(), pd.DataFrame())
    kospi = kospi if kospi is not None else empty
    small = small if small is not None else empty
    snapshots = {"kospi": kospi.performance, "snowball": snow_daily, "small": small.performance}
    curves = {key: table["포트 누적"] for key, table in snapshots.items() if not table.empty}
    amounts = dict(zip(STRATEGY_PAGES, allocation.outer))

    st.subheader(f"📈 {month.month}월 일별 수익률")
    st.caption("월초 투자비율로 합산 · 공통 종가일의 원화 기준 · 거래비용 제외")
    labels = {f"{key} 누적": f"{title} 누적" for key, title in zip(STRATEGY_PAGES, OUTER_LABELS)}
    unavailable = [STRATEGY_PAGES[key][0] for key, amount in amounts.items() if amount > 0 and key not in curves]
    note = ("수익률 대기 · " + ", ".join(unavailable) if unavailable else
            "비중이 있는 전략의 공통 종가일 자료가 준비되면 표시됩니다.")
    combined = live.combine_daily(curves, amounts)
    if not combined.empty and amounts["small"] > 0:
        st.caption("소형주는 현재 수량을 월초부터 보유한 것으로 계산 · 월중 매매·입출금 제외")
    _daily_panel(combined, "three", labels, note, common_dates=True)

    st.subheader("전략별 보유 현황")
    tabs = st.tabs([label for label, *_ in STRATEGY_PAGES.values()], default=active_tab,
                   key="three_strategy_tabs", on_change="rerun")
    snow_labels = {f"{key} 누적": f"{LEG_LABELS[key]} 누적" for key in SNOW}
    panels = (
        ("kospi", kospi, kospi_failed, {}),
        ("snowball", live.CurrentHoldings(snow_holdings, snow_daily), snowball_failed, snow_labels),
        ("small", small, small_failed, {}),
    )
    for tab, arguments in zip(tabs, panels):
        if tab.open:
            with tab:
                _strategy_panel(*arguments)


@st.cache_data(show_spinner=False)
def _backtest_result(history, last_closed, allocation):
    window = backtest_window(history, LEGS, last_closed, common=False, verified_end=VERIFIED_HISTORY_END)
    return portfolio_stats(combine(window, allocation.weights())) if not window.empty else None


def _backtest(allocation):
    st.subheader("📈 백테스트 성과")
    last = str(pd.Period(current_month(), freq="M") - 1)
    try:
        history = live.extend_history(load_history(), last)
    except ValueError as exc:
        st.warning(str(exc))
        return
    except Exception:
        st.warning("확정 월수익률 원장을 불러오지 못했습니다.")
        return
    result = _backtest_result(history, last, allocation)
    if result is None:
        st.info("확정 월수익률 자료가 필요합니다.")
        return

    returns, equity = result["ret"], result["equity"]
    st.caption(f"보유월 {returns.index[0]}~{returns.index[-1]} · {result['n']}개월")
    metrics = (
        ("CAGR", f"{result['cagr']:.1%}" if result["n"] >= 12 else "—"),
        ("MDD", f"{result['mdd']:.1%}"),
        ("샤프 비율", f"{result['sharpe']:.2f}" if math.isfinite(result["sharpe"]) else "—"),
        ("Sortino", f"{result['sortino']:.2f}" if math.isfinite(result["sortino"]) else "—"),
        ("누적 수익", f"{result['cum']:,.0%}"),
        ("월 승률", f"{result['win']:.1%}"),
    )
    for column, (label, value) in zip(st.columns(6), metrics):
        column.metric(label, value)
    st.caption("확정 월수익률 · 매월 현재 비율 적용 · 초기 이력 미가용 비중은 현금으로 가정")

    st.markdown("#### 🗓️ 월별 수익률 히트맵 & MDD TOP 10")
    heatmap, drawdown = st.columns([7.2, 2.8])
    heatmap_frame = pd.DataFrame({"투자월": returns.index, HOME_TITLE: returns.values * 100})
    heatmap.dataframe(get_monthly_heatmap(heatmap_frame, HOME_TITLE), width="stretch")
    initial = pd.Series([1.0], index=[str(pd.Period(equity.index[0], freq="M") - 1)])
    mdd = get_mdd_history(pd.concat([initial, equity]))
    if mdd.empty:
        drawdown.info("낙폭 구간 없음")
    else:
        drawdown.dataframe(mdd, hide_index=True, width="stretch")

    st.markdown("#### 📋 월별 상세")
    details = pd.DataFrame({"월 수익률": returns, "월말 낙폭": result["dd"], "누적 수익률": equity - 1})
    details.index.name = "보유월"
    st.dataframe(details.iloc[::-1], width="stretch", height=310,
                 column_config={column: PCT for column in details})

    with st.expander("📉 자산 곡선 (로그) 보기"):
        fig = go.Figure(go.Scatter(x=equity.index, y=equity, mode="lines", name=HOME_TITLE,
                                   line=dict(color="#3B82F6", width=2.5)))
        fig.update_layout(yaxis_type="log", height=420, hovermode="x unified",
                          margin=dict(l=10, r=10, t=10, b=10))
        fig.update_yaxes(title="누적 (1=원금)")
        st.plotly_chart(fig, width="stretch")


def render_combination():
    inject_custom_css()
    st.html("""
        <style>
        [class*="st-key-three-strategy-detail-title-"] [data-testid="stPageLink-NavLink"] p {
            font-size: 1.15rem; font-weight: 700;
        }
        </style>
    """)
    st.title(f"{HOME_ICON} {HOME_TITLE}")
    allocation = current_allocation()
    _allocation_summary(allocation)
    strategy = st.query_params.get(STRATEGY_TAB_PARAM, "kospi")
    active = STRATEGY_PAGES.get(strategy, STRATEGY_PAGES["kospi"])[0]
    _current_section(allocation, active)
    st.divider()
    _backtest(allocation)
