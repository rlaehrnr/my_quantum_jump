"""
6_❄️_스노우볼_포트.py
─────────────────────
명세서 기반 동적 자산배분 전략 페이지.

구성:
- 공격/방어 자산 현황 (현재 모드 + 후보 자산 모멘텀, 선택 자산 강조)
- 위험회피 옵션 (조건1 모멘텀 / 조건2 밸류에이션)
- 백테스트 성과 요약 + 자산곡선
- 전체 월별 로그
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from utils.snowball import (
    load_monthly_prices, load_dividend_yield,
    compute_signals, run_backtest, compute_performance,
    SIGNAL_ASSETS, OFFENSE_ASSETS, DEFENSE_ASSETS, BENCHMARK, CASH,
)
from utils.ui_components import inject_custom_css

st.set_page_config(page_title="스노우볼 포트", page_icon="❄️", layout="wide")
inject_custom_css()

# ==========================================
# 자산별 색상 (요청대로 직접 지정)
# ==========================================
ASSET_COLORS = {
    'TQQQ': '#10B981',   # 그린 (공격 대표)
    'USD':  '#F59E0B',   # 앰버 (공격 보조 — 반도체 2배)
    'GLD':  '#FBBF24',   # 금
    'TLT':  '#3B82F6',   # 채권 파랑
    'SQQQ': '#EF4444',   # 빨강 (인버스)
    'SLV':  '#9CA3AF',   # 은
    'CASH': '#6B7280',   # 회색
    'SPY':  '#8B5CF6',   # 보라 (벤치마크)
}


# ==========================================
# 페이지 헤더 (다른 페이지와 동일한 h1 스타일)
# ==========================================
st.markdown('''
    <div style="margin-bottom: 20px;">
        <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
            <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">❄️ 스노우볼 포트</h1>
        </div>
    </div>
''', unsafe_allow_html=True)


# ==========================================
# 데이터 로딩
# ==========================================
MONTHLY_DIR = 'data/snowball/monthly'

with st.spinner("데이터 로딩 중..."):
    prices = load_monthly_prices(MONTHLY_DIR)
    div_yield = load_dividend_yield(MONTHLY_DIR)

# 데이터 누락 안내
if prices.empty:
    st.error(
        f"📁 데이터 파일이 없습니다.\n\n"
        f"`{MONTHLY_DIR}/` 폴더에 다음 파일들을 넣어주세요:\n"
        f"- ETF 11종: TIP, VWO, EFA, VIXY, TQQQ, USD, GLD, TLT, SQQQ, SLV, SPY (각각 `{{TICKER}}_과거_데이터.csv`)\n"
        f"- 배당수익률: `SP500_DIV.csv`\n\n"
        f"형식: investing.com KR 다운로드 형식 (월봉)"
    )
    st.stop()

# 누락 티커 체크
missing_tickers = [t for t in SIGNAL_ASSETS + OFFENSE_ASSETS + DEFENSE_ASSETS + [BENCHMARK] if t not in prices.columns]
if missing_tickers:
    st.warning(f"⚠️ 누락된 ETF 파일: {', '.join(missing_tickers)}. 정상 동작을 위해 모두 필요합니다.")

if div_yield.empty:
    st.info("ℹ️ 배당수익률 파일(SP500_DIV.csv)이 없거나 비어있어 조건2(밸류에이션)는 항상 False로 처리됩니다.")


# ==========================================
# 신호 계산 + 백테스트
# ==========================================
signals = compute_signals(prices, div_yield)
bt = run_backtest(prices, signals)
perf = compute_performance(bt) if not bt.empty else {}


# ==========================================
# 섹션 1: 공격/방어 자산 현황
# ==========================================
last_signal_month = prices.index[-1]
last_signal = signals.loc[last_signal_month]
defensive_now = bool(last_signal['defensive'])

# 현재 모드 + 실제 보유(선택) 종목
if defensive_now:
    mode_text = "🛡️ 방어 모드"
    mode_color = "#EF4444"
else:
    mode_text = "⚔️ 공격 모드"
    mode_color = "#10B981"
selected_hold = last_signal['hold']  # 실제 선택된 종목 (또는 CASH)

# 제목 + 모드 뱃지 (한 줄)
st.markdown(
    f"<div style='display:flex; align-items:center; gap:14px; margin-bottom:10px;'>"
    f"<span style='font-size:1.5rem; font-weight:800;'>공격 · 방어 자산 현황</span>"
    f"<span style='font-size:15px; font-weight:900; color:{mode_color}; background:{mode_color}18; "
    f"padding:5px 14px; border-radius:8px; border:1.5px solid {mode_color};'>{mode_text}</span>"
    f"<span style='font-size:12px; color:#9CA3AF;'>(기준: {last_signal_month} 월말)</span>"
    f"</div>",
    unsafe_allow_html=True
)


def _build_asset_table(title, assets, ret_prefix, period_label,
                       highlight_outer, selected_ticker):
    """
    자산 모멘텀 표를 HTML로 생성.
    highlight_outer=True면 표 외곽선을 모드 색으로, 선택 종목 행을 색칠.
    """
    # 데이터 수집
    rows = []
    for t in assets:
        col = f'{ret_prefix}_{t}'
        v = last_signal[col] if col in last_signal else np.nan
        rows.append((t, v))
    # 수익률 내림차순 정렬
    rows.sort(key=lambda x: (x[1] if pd.notna(x[1]) else -np.inf), reverse=True)

    outer_color = mode_color if highlight_outer else "#E5E7EB"
    outer_width = "3px" if highlight_outer else "1px"

    html = (
        f"<div style='border:{outer_width} solid {outer_color}; border-radius:10px; "
        f"overflow:hidden; margin-bottom:6px;'>"
        f"<div style='background:{outer_color}15; padding:8px 12px; font-weight:800; font-size:14px;'>{title}</div>"
        f"<table style='width:100%; border-collapse:collapse; font-size:14px;'>"
    )
    for t, v in rows:
        is_selected = highlight_outer and (t == selected_ticker)
        a_color = ASSET_COLORS.get(t, '#6B7280')
        row_bg = f"{a_color}22" if is_selected else "transparent"
        weight = "900" if is_selected else "500"
        check = " ✅" if is_selected else ""
        if pd.notna(v):
            v_pct = v * 100
            v_color = "#D32F2F" if v_pct > 0 else ("#1976D2" if v_pct < 0 else "#6B7280")
            v_str = f"{v_pct:+.2f}%"
        else:
            v_color = "#9CA3AF"
            v_str = "N/A"
        html += (
            f"<tr style='background:{row_bg}; border-top:1px solid #F0F0F0;'>"
            f"<td style='padding:8px 12px; font-weight:{weight}; color:{a_color};'>{t}{check}</td>"
            f"<td style='padding:8px 12px; text-align:right; font-weight:{weight}; color:{v_color};'>{v_str}</td>"
            f"</tr>"
        )
    html += "</table></div>"
    return html


col_off, col_def = st.columns(2)

with col_off:
    # 공격모드일 때만 외곽선+선택 강조
    off_selected = selected_hold if (not defensive_now) else None
    st.markdown(
        _build_asset_table(
            "⚔️ 공격 자산 (12개월 수익률)", OFFENSE_ASSETS, 'ret12', '12M',
            highlight_outer=(not defensive_now), selected_ticker=off_selected
        ),
        unsafe_allow_html=True
    )

with col_def:
    # 방어모드일 때만 외곽선+선택 강조
    def_selected = selected_hold if defensive_now else None
    st.markdown(
        _build_asset_table(
            "🛡️ 방어 자산 (11개월 수익률)", DEFENSE_ASSETS, 'ret11', '11M',
            highlight_outer=defensive_now, selected_ticker=def_selected
        ),
        unsafe_allow_html=True
    )

# 방어모드 & 현금 보유 시 안내
if defensive_now and selected_hold == CASH:
    st.info("🛡️ 방어 모드 + 방어자산 4종 11M 수익률 모두 0 이하 → **현금 보유** (수익률 0%)")


# ==========================================
# 섹션 2: 위험회피 옵션 (조건1 / 조건2)
# ==========================================
st.markdown(
    "<div style='font-size:1.5rem; font-weight:800; margin:18px 0 10px 0;'>위험회피 옵션</div>",
    unsafe_allow_html=True
)

col_c1, col_c2 = st.columns(2)

with col_c1:
    cond1_on = bool(last_signal['cond1'])
    badge1 = (
        f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; "
        f"padding:3px 10px; border-radius:6px;'>🛑 발동</span>"
        if cond1_on else
        f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; "
        f"padding:3px 10px; border-radius:6px;'>미발동</span>"
    )
    st.markdown(
        f"<div style='margin-bottom:6px;'>{badge1} "
        f"<b>조건1: 모멘텀 신호</b> <span style='font-size:12px; color:#9CA3AF;'>(4종 6M 수익률 모두 &lt; 0)</span></div>",
        unsafe_allow_html=True
    )
    cond1_data = []
    for t in SIGNAL_ASSETS:
        col_name = f'ret6_{t}'
        if col_name in last_signal:
            v = last_signal[col_name]
            if pd.notna(v):
                cond1_data.append({
                    '자산': t,
                    '6M 수익률': f"{v*100:+.2f}%",
                    '음수?': '✅' if v < 0 else '❌',
                })
            else:
                cond1_data.append({'자산': t, '6M 수익률': 'N/A', '음수?': '⚠️'})
    if cond1_data:
        st.dataframe(pd.DataFrame(cond1_data), hide_index=True, use_container_width=True)

with col_c2:
    cond2_on = bool(last_signal['cond2'])
    badge2 = (
        f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; "
        f"padding:3px 10px; border-radius:6px;'>🛑 발동</span>"
        if cond2_on else
        f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; "
        f"padding:3px 10px; border-radius:6px;'>미발동</span>"
    )
    st.markdown(
        f"<div style='margin-bottom:6px;'>{badge2} "
        f"<b>조건2: 밸류에이션</b> <span style='font-size:12px; color:#9CA3AF;'>(배당 5Y 백분위 ≤ 10%)</span></div>",
        unsafe_allow_html=True
    )
    div_pct_val = last_signal['div_pct']
    if pd.notna(div_pct_val):
        st.metric(
            "현재 배당 백분위 (5Y 롤링)",
            f"{div_pct_val:.1f}%",
            delta=f"{'10% 이하 ⚠️' if div_pct_val <= 10 else '안전 구간'}",
            delta_color="inverse" if div_pct_val <= 10 else "off"
        )
    else:
        st.info("배당 데이터 부족 (60개월 워밍업 또는 파일 없음)")


# ==========================================
# 섹션 3: 백테스트 성과 요약 + 자산곡선
# ==========================================
if bt.empty:
    st.warning("백테스트 데이터가 충분하지 않습니다.")
    st.stop()

st.markdown("---")
st.markdown("### 📈 백테스트 성과")

# 요약 카드
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("CAGR", f"{perf['cagr']*100:.1f}%", delta=f"vs SPY {perf['spy_cagr']*100:.1f}%")
c2.metric("MDD", f"{perf['mdd']*100:.1f}%", delta=f"vs SPY {perf['spy_mdd']*100:.1f}%", delta_color="inverse")
c3.metric("샤프 비율", f"{perf['sharpe']:.2f}", delta=f"vs SPY {perf['spy_sharpe']:.2f}")
c4.metric("누적 수익", f"{perf['cum_return']*100:,.0f}%")
c5.metric("공격 비중", f"{perf['offense_pct']*100:.0f}%", delta=f"{perf['n_months']}개월")

# 자산 곡선 (log scale)
st.markdown("#### 📉 자산 곡선 (Log Scale)")
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=bt['hold_month'], y=bt['cum_strategy'],
    mode='lines', name='스노우볼 전략',
    line=dict(color='#10B981', width=2.5),
))
fig.add_trace(go.Scatter(
    x=bt['hold_month'], y=bt['cum_spy'],
    mode='lines', name='SPY (Buy & Hold)',
    line=dict(color=ASSET_COLORS['SPY'], width=2, dash='dash'),
))
fig.update_layout(
    yaxis_type='log', height=420,
    hovermode='x unified', margin=dict(l=10, r=10, t=10, b=10),
    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
)
fig.update_yaxes(title='누적 (1=원금)')
st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 섹션 4: 전체 월별 로그
# ==========================================
st.markdown("#### 📋 전체 월별 로그")
log_df = bt.copy()
log_df['ret_strategy_str'] = log_df['ret_strategy'].apply(lambda x: f"{x*100:+.2f}%")
log_df['ret_spy_str'] = log_df['ret_spy'].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
log_df['mode'] = log_df['defensive'].apply(lambda d: "🛡️ 방어" if d else "⚔️ 공격")
log_df['dd_str'] = log_df['dd_strategy'].apply(lambda x: f"{x*100:.1f}%")

display_df = log_df[['hold_month', 'mode', 'hold', 'ret_strategy_str', 'ret_spy_str', 'dd_str']].rename(columns={
    'hold_month': '보유월',
    'mode': '국면',
    'hold': '보유',
    'ret_strategy_str': '전략 수익률',
    'ret_spy_str': 'SPY 수익률',
    'dd_str': '낙폭',
})
# 최신이 위로 오도록 역순
st.dataframe(display_df.iloc[::-1], hide_index=True, use_container_width=True, height=600)
