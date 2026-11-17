import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.static_allocation import MARKET_PLANS
from utils.static_allocation_history import (
    SESSION_PROXY, calculate_history, load_price_history, market_dates, target_weights,
)
from utils.ui_components import get_monthly_heatmap, render_daily_performance


@st.cache_data(ttl=3600, show_spinner=False)
def market_history(market, tickers, cutoff):
    return load_price_history(market, tickers, cutoff)


def render_static_performance(market, rows_by_plan):
    st.subheader("일별·월별 성과")
    basis = "원화 · 네이버 종가 · 분배금 미포함" if market == "kr" else (
        "달러 · Yahoo 수정종가 · 분배금 반영 · 환율 변동 미포함"
    )
    reserve = "현금" if market == "kr" else "현금·GRVT"
    st.caption(
        f"{basis} · 전월 마지막 거래일 종가에 현재 설정한 계절 비중으로 조정하고 월중 수량 유지. "
        f"{reserve} 수익률 0% 가정 · 거래비용·세금 미반영."
    )
    try:
        winter, summer = (target_weights(rows_by_plan[plan], market) for plan in MARKET_PLANS[market])
    except ValueError as exc:
        st.info(str(exc))
        return
    current_month, cutoff = market_dates(market)
    tickers = tuple(sorted(winter.keys() | summer.keys()))
    with st.spinner("ETF 일별 종가를 불러오는 중입니다."):
        prices = market_history(market, tickers, cutoff)
    proxy = SESSION_PROXY[market]
    if proxy not in prices or prices[proxy].dropna().empty:
        st.info("시장 거래일 자료를 불러오지 못했습니다. 시세 새로고침으로 다시 시도해 주세요.")
        return
    sessions = prices[proxy].dropna().index
    missing = [ticker for ticker in tickers if ticker not in prices or prices[ticker].isna().all()]
    if missing:
        st.caption("일별 시세 미확인 종목 · " + ", ".join(missing))
    performance = calculate_history(prices, sessions, winter, summer, current_month)
    daily = performance.daily
    st.markdown(f"#### {current_month.month}월 일별 수익률")
    if daily.empty:
        st.caption("전월 마지막 거래일과 이번 달의 ETF 종가가 갖춰지면 표시됩니다.")
    else:
        st.metric("이번 달 누적 수익률", f'{daily["포트 누적"].iloc[-1]:+.2%}')
        st.caption(f"{daily.index[-1]:%Y-%m-%d} 현지 거래일 종가 기준")
        render_daily_performance(daily, f"static_{market}", {
            "포트 일간": "일간 수익률", "포트 누적": "월 누적 수익률",
        })
    render_monthly_history(performance, market)


def render_monthly_history(performance, market):
    st.markdown("#### 월별 백테스트")
    monthly = performance.monthly
    if monthly.empty:
        st.caption("전월 마지막 종가부터 월말까지 시세가 갖춰진 달의 성과를 표시합니다.")
        return

    equity = performance.equity
    available = monthly.dropna()
    period = f"{available.index[0]} ~ {available.index[-1]}"
    st.caption(f"{period} · 확정 {len(available):,}개월. 필요한 종가가 없는 달은 공란으로 표시합니다.")
    curve_start = equity.index[1].to_period("M")
    curve_months = len(monthly.loc[curve_start:])
    if len(available) != len(monthly):
        st.caption(f"누적 수익률과 낙폭은 자료가 연속인 최근 구간({curve_start} 이후) 기준입니다.")

    total, average, drawdown, annual = st.columns(4)
    total.metric("누적 수익률", f"{equity.iloc[-1] - 1:+.2%}")
    average.metric("월평균 수익률", f"{available.mean():+.2%}")
    drawdown.metric("최대 낙폭", f"{(equity / equity.cummax() - 1).min():.2%}")
    annual.metric("연복리 수익률", f"{equity.iloc[-1] ** (12 / curve_months) - 1:+.2%}" if curve_months >= 12 else "—")

    fig = go.Figure(go.Scatter(
        x=equity.index, y=equity - 1, mode="lines",
        hovertemplate="%{x|%Y-%m-%d} %{y:+.2%}<extra></extra>",
    ))
    fig.update_layout(height=260, margin=dict(l=26, r=26, t=15, b=18), yaxis_tickformat=".1%")
    st.plotly_chart(fig, width="stretch", key=f"static_{market}_equity")

    months = pd.DataFrame({"투자월": monthly.index.astype(str), "수익률": monthly.to_numpy() * 100})
    st.dataframe(get_monthly_heatmap(months, "수익률"), width="stretch", key=f"static_{market}_heatmap")
    st.caption("연수익률은 각 연도에 자료가 확보된 월을 복리로 연결한 값입니다.")
    with st.expander("월별 상세"):
        detail = pd.DataFrame({
            "투자월": monthly.index.astype(str),
            "적용 비중": ["5월–10월" if 5 <= period.month <= 10 else "11월–4월" for period in monthly.index],
            "월 수익률": monthly.to_numpy(),
        })
        st.dataframe(
            detail.iloc[::-1], width="stretch", hide_index=True,
            column_config={"월 수익률": st.column_config.NumberColumn(format="percent")},
        )
