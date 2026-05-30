"""
6_❄️_스노우볼_포트.py
─────────────────────
명세서 기반 동적 자산배분 전략 페이지.

필수 기능 (1차):
- 이번 달 보유 종목 + 매일 진행률 (daily_snapshot 활용)
- 다음 달 신호 잠정 + 확정 (있으면)
- 현재 시점 cond1/cond2 상태 패널
- 자산 곡선 차트 (전략 vs SPY)
- 상단 요약 카드 (CAGR, MDD, 샤프, 누적, 공격비중)
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

from utils.snowball import (
    load_monthly_prices, load_dividend_yield, load_daily_snapshot,
    compute_signals, run_backtest, compute_performance, compute_current_month_progress,
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
# 페이지 헤더
# ==========================================
st.markdown("<h1 style='margin-bottom:4px;'>❄️ 스노우볼 포트</h1>", unsafe_allow_html=True)
st.caption("동적 자산배분 전략 (월 1회 리밸런싱) — 명세서 기반 구현")


# ==========================================
# 데이터 로딩
# ==========================================
MONTHLY_DIR = 'data/snowball/monthly'
DAILY_SNAPSHOT_PATH = 'data/snowball/daily_snapshot.csv'

with st.spinner("데이터 로딩 중..."):
    prices = load_monthly_prices(MONTHLY_DIR)
    div_yield = load_dividend_yield(MONTHLY_DIR)
    snapshot_prices, snapshot_date = load_daily_snapshot(DAILY_SNAPSHOT_PATH)

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
# 섹션 1: 이번 달 / 다음 달 신호 패널
# ==========================================
st.markdown("---")
st.markdown("### 🎯 지금 어떤 종목을 보유해야 하나?")

# 가장 최근 신호월 = prices.index[-1]
# 이 신호의 hold는 "다음 달"의 보유 종목
last_signal_month = prices.index[-1]
last_signal = signals.loc[last_signal_month]

# 이번 달 진행률
progress = compute_current_month_progress(prices, signals, snapshot_prices, snapshot_date)

# ── 2열 레이아웃: 좌측 = 이번 달 보유 / 우측 = 다음 달 잠정+확정
col_now, col_next = st.columns(2)

# ── 좌측: 이번 달 (마지막 신호 기준 보유 중)
with col_now:
    if progress and progress['hold']:
        hold = progress['hold']
        color = ASSET_COLORS.get(hold, '#6B7280')
        
        st.markdown(
            f"<div style='background:{color}15; border-left:6px solid {color}; padding:14px 16px; border-radius:8px;'>"
            f"<div style='font-size:12px; color:#6B7280; font-weight:bold;'>이번 달 ({progress['curr_month']}) 보유</div>"
            f"<div style='font-size:32px; font-weight:900; color:{color}; margin:2px 0;'>{hold}</div>"
            f"<div style='font-size:11px; color:#6B7280;'>{progress['reason']}</div>"
            f"</div>",
            unsafe_allow_html=True
        )
        
        # 진행률 표시
        if progress['mtd_return'] is not None:
            mtd_pct = progress['mtd_return'] * 100
            mtd_color = '#D32F2F' if mtd_pct > 0 else ('#1976D2' if mtd_pct < 0 else '#6B7280')
            sign = '+' if mtd_pct >= 0 else ''
            st.markdown(
                f"<div style='margin-top:10px; padding:10px 14px; background:#F9FAFB; border-radius:8px;'>"
                f"<div style='font-size:11px; color:#6B7280;'>이번 달 진행률 (오늘 / 전월말 - 1)</div>"
                f"<div style='font-size:24px; font-weight:900; color:{mtd_color};'>{sign}{mtd_pct:.2f}%</div>"
                f"<div style='font-size:10px; color:#9CA3AF;'>"
                f"전월말 {progress['prev_close']:.2f} → 오늘 {progress['today_price']:.2f}"
                f"{' · ' + progress['as_of'] if progress['as_of'] else ''}"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True
            )
        elif hold == CASH:
            st.markdown(
                f"<div style='margin-top:10px; padding:10px 14px; background:#F9FAFB; border-radius:8px;'>"
                f"<div style='font-size:11px; color:#6B7280;'>이번 달 진행률</div>"
                f"<div style='font-size:24px; font-weight:900; color:#6B7280;'>0.00% (현금)</div>"
                f"</div>",
                unsafe_allow_html=True
            )
        else:
            st.caption("ℹ️ 일별 진행률을 보려면 `data/snowball/daily_snapshot.csv` 파일이 필요합니다.")
    else:
        st.warning("이번 달 신호 계산 불가 (데이터 부족)")

# ── 우측: 다음 달 잠정 (지금까지 데이터로 미리보기)
with col_next:
    # "다음 달"의 정의: 이번 달이 끝나면 신호가 한 번 더 갱신될 것.
    # 그런데 명세서상 신호는 "월말 종가"로 판정.
    # 따라서 "다음 달 잠정"은 = 이번 달 중간 시점 종가로 계산한 시뮬레이션 신호
    # 그러나 우리는 일별 종가 데이터가 없으므로(snapshot은 가격뿐, 이력 없음),
    # 정확한 잠정 신호는 "현재까지 알려진 가장 최근 월말 종가 = prices.index[-1]"
    # 이게 곧 "이번 달 신호"가 됨. 즉:
    #   - prices.index[-1] = 직전 월말 → 이번 달 보유 종목 결정 (이미 좌측에 표시)
    #   - "다음 달 신호" = 이번 달 종료 시점에 비로소 확정됨
    #
    # 잠정으로 보여줄 수 있는 것: snapshot 가격을 prices.index[-1]의 "다음 달" 종가로 잠정 사용
    # 하지만 이는 cond1/cond2 계산에 필요한 시계열 변화이고, 단순 snapshot으로 잠정 신호 계산이 가능
    
    # 잠정 신호 계산: snapshot 가격을 다음 달 행으로 추가한 시뮬레이션
    tentative_sig = None
    if snapshot_prices:
        # snapshot 가격을 마지막 month + 1로 추가
        next_m = last_signal_month + 1
        sim_prices = prices.copy()
        # snapshot 가격으로 새 행 생성
        new_row = pd.Series({t: snapshot_prices.get(t, np.nan) for t in sim_prices.columns}, name=next_m)
        sim_prices = pd.concat([sim_prices, new_row.to_frame().T])
        sim_prices.index = pd.PeriodIndex(sim_prices.index, freq='M')
        
        # 배당은 잠정으로 마지막 값 유지
        sim_div = div_yield.copy()
        if not sim_div.empty and next_m not in sim_div.index:
            sim_div = pd.concat([sim_div, pd.Series([sim_div.iloc[-1]], index=[next_m])])
        
        sim_signals = compute_signals(sim_prices, sim_div)
        if next_m in sim_signals.index:
            tentative_sig = sim_signals.loc[next_m]
    
    if tentative_sig is not None and tentative_sig['hold']:
        hold_t = tentative_sig['hold']
        color_t = ASSET_COLORS.get(hold_t, '#6B7280')
        st.markdown(
            f"<div style='background:{color_t}15; border-left:6px solid {color_t}; padding:14px 16px; border-radius:8px;'>"
            f"<div style='font-size:12px; color:#6B7280; font-weight:bold;'>다음 달 잠정 신호 <span style='color:#9CA3AF;'>(오늘 종가 기준 미리보기)</span></div>"
            f"<div style='font-size:32px; font-weight:900; color:{color_t}; margin:2px 0;'>{hold_t}</div>"
            f"<div style='font-size:11px; color:#6B7280;'>{tentative_sig['reason']}</div>"
            f"</div>",
            unsafe_allow_html=True
        )
        
        # 월말까지 며칠 남았는지
        today = datetime.now()
        if today.month == 12:
            month_end = datetime(today.year + 1, 1, 1)
        else:
            month_end = datetime(today.year, today.month + 1, 1)
        days_to_end = (month_end - today).days
        st.markdown(
            f"<div style='margin-top:10px; padding:10px 14px; background:#FEF3C7; border-radius:8px; border:1px solid #FCD34D;'>"
            f"<div style='font-size:11px; color:#92400E; font-weight:bold;'>⏳ 확정까지 약 {days_to_end}일 (월말 종가 판정)</div>"
            f"<div style='font-size:10px; color:#92400E; margin-top:3px;'>잠정 신호는 시장 변동에 따라 바뀔 수 있습니다.</div>"
            f"</div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f"<div style='background:#F3F4F6; padding:14px 16px; border-radius:8px;'>"
            f"<div style='font-size:12px; color:#6B7280; font-weight:bold;'>다음 달 잠정 신호</div>"
            f"<div style='font-size:14px; color:#6B7280; margin-top:6px;'>"
            f"`daily_snapshot.csv` 파일이 없어 잠정 계산 불가.<br>"
            f"월말 데이터 갱신 시 자동으로 확정됩니다."
            f"</div>"
            f"</div>",
            unsafe_allow_html=True
        )


# ==========================================
# 섹션 2: 현재 신호 상세 (cond1/cond2 + 자산별 모멘텀)
# ==========================================
st.markdown("---")
st.markdown(f"### 📡 현재 신호 상세 (기준: {last_signal_month} 월말 데이터)")

col_c1, col_c2 = st.columns(2)

with col_c1:
    st.markdown("**🔻 조건1: 모멘텀 신호** (4종 6M 수익률 모두 < 0)")
    cond1_data = []
    for t in SIGNAL_ASSETS:
        col_name = f'ret6_{t}'
        if col_name in last_signal:
            v = last_signal[col_name]
            if pd.notna(v):
                v_pct = v * 100
                is_neg = v < 0
                cond1_data.append({
                    '자산': t,
                    '6M 수익률': f"{v_pct:+.2f}%",
                    '음수?': '✅' if is_neg else '❌',
                })
            else:
                cond1_data.append({'자산': t, '6M 수익률': 'N/A', '음수?': '⚠️'})
    if cond1_data:
        st.dataframe(pd.DataFrame(cond1_data), hide_index=True, use_container_width=True)
    cond1_result = "🛑 발동 (모두 음수)" if last_signal['cond1'] else "✅ 미발동"
    st.markdown(f"**결과**: {cond1_result}")

with col_c2:
    st.markdown("**💰 조건2: 밸류에이션** (배당 5Y 백분위 ≤ 10%)")
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
    cond2_result = "🛑 발동 (배당 백분위 ≤ 10%)" if last_signal['cond2'] else "✅ 미발동"
    st.markdown(f"**결과**: {cond2_result}")

# 모드 종합
defensive_now = bool(last_signal['defensive'])
mode_color = "#EF4444" if defensive_now else "#10B981"
mode_text = "🛡️ 방어 모드" if defensive_now else "⚔️ 공격 모드"
st.markdown(
    f"<div style='background:{mode_color}15; border:2px solid {mode_color}; padding:10px; border-radius:8px; text-align:center; margin-top:10px;'>"
    f"<span style='font-size:18px; font-weight:900; color:{mode_color};'>{mode_text}</span> "
    f"<span style='font-size:13px; color:#6B7280;'>(cond1 OR cond2)</span>"
    f"</div>",
    unsafe_allow_html=True
)

# 모드별 후보 자산 모멘텀 표시
st.markdown("")
if defensive_now:
    st.markdown("**🛡️ 방어 자산 11M 수익률 비교**")
    def_data = []
    for t in DEFENSE_ASSETS:
        col_name = f'ret11_{t}'
        if col_name in last_signal:
            v = last_signal[col_name]
            if pd.notna(v):
                def_data.append({'자산': t, '11M 수익률': f"{v*100:+.2f}%", '_v': v})
    if def_data:
        def_df = pd.DataFrame(def_data).sort_values('_v', ascending=False).drop(columns=['_v'])
        st.dataframe(def_df, hide_index=True, use_container_width=True)
else:
    st.markdown("**⚔️ 공격 자산 12M 수익률 비교**")
    off_data = []
    for t in OFFENSE_ASSETS:
        col_name = f'ret12_{t}'
        if col_name in last_signal:
            v = last_signal[col_name]
            if pd.notna(v):
                off_data.append({'자산': t, '12M 수익률': f"{v*100:+.2f}%", '_v': v})
    if off_data:
        off_df = pd.DataFrame(off_data).sort_values('_v', ascending=False).drop(columns=['_v'])
        st.dataframe(off_df, hide_index=True, use_container_width=True)


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
# 섹션 4: 최근 월별 로그 (간단)
# ==========================================
st.markdown("#### 📋 최근 24개월 로그")
recent = bt.tail(24).copy()
recent['ret_strategy_str'] = recent['ret_strategy'].apply(lambda x: f"{x*100:+.2f}%")
recent['ret_spy_str'] = recent['ret_spy'].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
recent['mode'] = recent['defensive'].apply(lambda d: "🛡️ 방어" if d else "⚔️ 공격")
recent['dd_str'] = recent['dd_strategy'].apply(lambda x: f"{x*100:.1f}%")

display_df = recent[['hold_month', 'mode', 'hold', 'ret_strategy_str', 'ret_spy_str', 'dd_str']].rename(columns={
    'hold_month': '보유월',
    'mode': '국면',
    'hold': '보유',
    'ret_strategy_str': '전략 수익률',
    'ret_spy_str': 'SPY 수익률',
    'dd_str': '낙폭',
})
st.dataframe(display_df.iloc[::-1], hide_index=True, use_container_width=True)


# ==========================================
# 한계 명시 (명세서 §10)
# ==========================================
st.markdown("---")
with st.expander("⚠️ 백테스트 한계 (반드시 확인)"):
    st.markdown("""
    - 분배금(배당)·거래비용·세금·슬리피지 미반영.
    - TQQQ/SQQQ 등 3배 레버리지 ETF의 운용보수·일일 리밸런싱 비용·변동성 끌림 미반영.
      → 실제 수익률은 백테스트보다 상당히 낮고, 실제 위험은 지표보다 큽니다.
    - 단일 역사 경로 기반. 미래 보장 아님. 특히 레버리지 ETF는 장기 횡보장에서 백테스트보다 크게 부진할 수 있습니다.
    - 투자 권유가 아니며 참고용 분석입니다.
    """)
