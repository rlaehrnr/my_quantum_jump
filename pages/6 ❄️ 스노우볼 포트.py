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
    SIGNAL_ASSETS, OFFENSE_ASSETS, DEFENSE_ASSETS, BENCHMARK,
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
    'SLV':  '#71717A',   # 진한 회색 (은) — 흰 글씨 가독성 확보
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
        f"- ETF 11종: TIP, VWO, VEA, VIXY, TQQQ, USD, GLD, TLT, SQQQ, SLV, SPY (각각 `{{TICKER}}_과거_데이터.csv`)\n"
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
# 백테스트(bt)·성과(perf)는 거래비용 슬라이더 아래 '섹션 3'에서 계산한다.


# ==========================================
# 섹션 1: 공격/방어 자산 현황
# ==========================================
# 💡 데이터가 모두 갖춰져 보유 종목이 결정된(hold != None) 마지막 달을 "현재 신호월"로 사용.
#    일부 ETF CSV가 다른 파일보다 한 달 더 최신이면(예: 진행 중인 이번달 부분 데이터 포함)
#    prices.index[-1]에는 그 ETF만 값이 있고 나머지는 NaN이라 표가 전부 None으로 보인다.
#    유효 신호월로 보정하면 이런 정렬 어긋남에 영향받지 않는다.
valid_signal_months = signals.index[signals['hold'].notna()]
if len(valid_signal_months) == 0:
    st.error("유효한 신호월이 없습니다. (데이터 워밍업 부족 또는 ETF 파일 누락)")
    st.stop()
last_signal_month = valid_signal_months[-1]
last_signal = signals.loc[last_signal_month]
defensive_now = bool(last_signal['defensive'])

# 현재 모드 + 실제 보유(선택) 종목
if defensive_now:
    mode_text = "🛡️ 방어 모드"
    mode_color = "#EF4444"
else:
    mode_text = "⚔️ 공격 모드"
    mode_color = "#10B981"
selected_hold = last_signal['hold']  # 실제 선택된 종목

# 제목
st.markdown(
    f"<div style='font-size:1.5rem; font-weight:800; margin-bottom:8px;'>"
    f"공격 · 방어 자산 현황 "
    f"<span style='font-size:12px; color:#9CA3AF; font-weight:500;'>(기준: {last_signal_month} 월말)</span>"
    f"</div>",
    unsafe_allow_html=True
)

# 모드 뱃지 — 옆으로 길게 (full width)
st.markdown(
    f"<div style='width:100%; background:{mode_color}18; border:2px solid {mode_color}; "
    f"border-radius:10px; padding:12px 20px; margin-bottom:14px; text-align:center;'>"
    f"<span style='font-size:22px; font-weight:900; color:{mode_color}; letter-spacing:1px;'>{mode_text}</span>"
    f"<span style='font-size:14px; color:#6B7280; margin-left:12px;'>"
    f"현재 보유: <b style='color:{ASSET_COLORS.get(selected_hold, '#6B7280')};'>{selected_hold}</b>"
    f"</span>"
    f"</div>",
    unsafe_allow_html=True
)


def _style_asset_df(assets, ret_prefix, active, selected_ticker, value_label='수익률'):
    """
    자산 모멘텀 DataFrame을 만들고 Styler 반환.
    active=True면 선택 종목 행을 모드색으로 강조.
    active=False면 전체를 흐리게.
    value_label: 값 컬럼 표시명 (공격='수익률', 방어='이격도').
    """
    rows = []
    for t in assets:
        col = f'{ret_prefix}_{t}'
        v = last_signal[col] if col in last_signal else np.nan
        rows.append({'자산': t, value_label: v})
    df = pd.DataFrame(rows).sort_values(value_label, ascending=False, na_position='last').reset_index(drop=True)

    def _row_style(row):
        n = len(row)
        if active and row['자산'] == selected_ticker:
            a_color = ASSET_COLORS.get(selected_ticker, '#6B7280')
            # 선택 행: 반투명 배경 + 굵게 (글자색은 건드리지 않아 빨강/파랑 유지)
            return [f'background-color: {a_color}55; font-weight: 800;'] * n
        if not active:
            return ['color: #9CA3AF;'] * n  # 비활성: 흐리게
        return [''] * n

    def _fmt_ret(v):
        if pd.isna(v):
            return 'N/A'
        return f"{v*100:+.2f}%"

    def _color_ret(row):
        """값 컬럼 색상 — 항상 빨강(양수)/파랑(음수)."""
        v = row[value_label]
        if pd.isna(v):
            return 'color: #9CA3AF; font-weight: bold;'
        if v > 0:
            return 'color: #FF5252; font-weight: bold;'
        if v < 0:
            return 'color: #5C9DFF; font-weight: bold;'
        return ''

    def _apply_ret_color(df_inner):
        # 값 컬럼에만 색 적용
        styles = pd.DataFrame('', index=df_inner.index, columns=df_inner.columns)
        for idx in df_inner.index:
            styles.loc[idx, value_label] = _color_ret(df_inner.loc[idx])
        return styles

    styler = (df.style
              .apply(_row_style, axis=1)
              .apply(_apply_ret_color, axis=None)
              .format({value_label: _fmt_ret}))
    return styler, df


col_off, col_def = st.columns(2)

with col_off:
    is_active = (not defensive_now)
    label = "⚔️ 공격 자산 (12개월 수익률)" + ("" if is_active else "  · 비활성")
    title_color = "#10B981" if is_active else "#9CA3AF"  # 활성: 초록, 비활성: 회색
    st.markdown(
        f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
        f"color:{title_color};'>{label}</div>",
        unsafe_allow_html=True
    )
    off_styler, _ = _style_asset_df(OFFENSE_ASSETS, 'ret12', is_active,
                                    selected_hold if is_active else None)
    st.dataframe(off_styler, hide_index=True, use_container_width=True)

with col_def:
    is_active = defensive_now
    label = "🛡️ 방어 자산 (12개월 MA 이격도)" + ("" if is_active else "  · 비활성")
    title_color = "#EF4444" if is_active else "#9CA3AF"  # 활성: 빨강, 비활성: 회색
    st.markdown(
        f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
        f"color:{title_color};'>{label}</div>",
        unsafe_allow_html=True
    )
    def_styler, _ = _style_asset_df(DEFENSE_ASSETS, 'disp12', is_active,
                                    selected_hold if is_active else None,
                                    value_label='이격도')
    st.dataframe(def_styler, hide_index=True, use_container_width=True)


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
    div_val = last_signal['div_value'] if 'div_value' in last_signal else np.nan
    div_thr = last_signal['div_threshold'] if 'div_threshold' in last_signal else np.nan
    div_rank_val = last_signal['div_rank'] if 'div_rank' in last_signal else np.nan
    div_total_val = last_signal['div_total'] if 'div_total' in last_signal else np.nan
    if pd.notna(div_pct_val):
        mcol1, mcol2 = st.columns(2)
        with mcol1:
            # 큰 숫자: "N등 / M개월" (순위 데이터 없으면 백분위로 폴백)
            if pd.notna(div_rank_val) and pd.notna(div_total_val):
                rank_str = f"{int(div_rank_val)}등 / {int(div_total_val)}개월"
            else:
                rank_str = f"{div_pct_val:.1f}%"
            # 하단: 원래 백분위 값 + 발동/안전 표시
            triggered = div_pct_val <= 10
            delta_str = (
                f"{div_pct_val:.1f}% → 10% 이하 발동" if triggered
                else f"{div_pct_val:.1f}% → 안전 구간"
            )
            st.metric(
                "5Y 밸류 순위 (1등=가장 비쌈)",
                rank_str,
                delta=delta_str,
                delta_color="inverse" if triggered else "off"
            )
        with mcol2:
            if pd.notna(div_val):
                help_txt = (
                    f"하위 10% 기준점 = 지난 {int(div_total_val)}개월 중 '이 값 이하면 발동'이 성립하는 "
                    f"가장 높은 배당수익률 ({div_thr:.2f}%). 현재 배당({div_val:.2f}%)이 이 값 이하면 "
                    f"역사적으로 비싼 구간 → 조건2 발동."
                ) if (pd.notna(div_thr) and pd.notna(div_total_val)) else None
                # 발동 여부는 실제 신호와 동일하게 백분위(div_pct<=10)로 판정 → 좌측·실제 신호와 항상 일치.
                # 기준점은 개수 규칙과 정확히 일치하도록 계산돼 있어 부등호도 이 판정과 어긋나지 않는다.
                if pd.notna(div_thr):
                    triggered = bool(div_pct_val <= 10)  # 단일 진실원천 (cond2와 동일)
                    cmp_sign = "≤" if triggered else ">"
                    cmp_delta = f"{div_val:.2f}% {cmp_sign} 기준점 {div_thr:.2f}%"
                    st.metric(
                        "현재 배당수익률",
                        f"{div_val:.2f}%",
                        delta=cmp_delta,
                        delta_color="inverse" if triggered else "off",
                        help=help_txt
                    )
                else:
                    st.metric("현재 배당수익률", f"{div_val:.2f}%", help=help_txt)
    else:
        st.info("배당 데이터 부족 (60개월 워밍업 또는 파일 없음)")


# ==========================================
# 섹션 3: 백테스트 성과 요약 + 자산곡선
# ==========================================
st.markdown("---")
st.markdown("### 📈 백테스트 성과")

# 거래비용 슬라이더 (턴오버 기반 — 종목 교체 시에만 차감)
cost_pct = st.slider(
    "거래비용 (종목 교체 1회당, %)",
    min_value=0.0, max_value=1.0, value=0.25, step=0.05, format="%.2f%%",
    help=(
        "보유 종목이 바뀌는 달(매매 발생)에만 차감하는 턴오버 기반 비용입니다. "
        "같은 종목을 이어 보유하면 비용 0, 첫 진입은 1회 차감. "
        "0%로 두면 비용 미반영 '이론 상한'이 됩니다. SPY 벤치마크는 매수 후 보유로 비용 미반영."
    ),
)
cost_rate = cost_pct / 100.0

bt = run_backtest(prices, signals, cost=cost_rate)
perf = compute_performance(bt) if not bt.empty else {}

if bt.empty:
    st.warning("백테스트 데이터가 충분하지 않습니다.")
    st.stop()

# 요약 카드
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("CAGR", f"{perf['cagr']*100:.1f}%", delta=f"vs SPY {perf['spy_cagr']*100:.1f}%")
c2.metric("MDD", f"{perf['mdd']*100:.1f}%", delta=f"vs SPY {perf['spy_mdd']*100:.1f}%", delta_color="inverse")
c3.metric("샤프 비율", f"{perf['sharpe']:.2f}", delta=f"vs SPY {perf['spy_sharpe']:.2f}")
c4.metric(
    "누적 수익",
    f"{perf['cum_return']*100:,.0f}%",
    delta=(f"비용 0% 시 {perf['cum_gross_return']*100:,.0f}%" if cost_rate > 0 else None),
    delta_color="off",
)
c5.metric(
    "공격 비중",
    f"{perf['offense_pct']*100:.0f}%",
    delta=f"{perf.get('offense_months', round(perf['offense_pct']*perf['n_months']))}개월 / {perf['n_months']}개월",
)

# 거래비용 반영 요약
if cost_rate > 0:
    st.caption(
        f"💸 거래비용 {cost_pct:.2f}%/교체 반영 · 종목 교체 {perf['n_switches']}회 / {perf['n_months']}개월 "
        f"· 누적 차감 약 {perf['total_cost']*100:.1f}%p "
        f"(비용 미반영 누적 {perf['cum_gross_return']*100:,.0f}% → 반영 {perf['cum_return']*100:,.0f}%)"
    )
else:
    st.caption("💸 거래비용 0% — 비용 미반영 '이론 상한' 기준입니다.")

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
# 종목 교체(거래비용 발생) 표시
log_df['switch_str'] = log_df.apply(
    lambda r: (f"🔁 -{r['cost']*100:.2f}%" if r.get('switched', False) and r.get('cost', 0) > 0
               else ("🔁" if r.get('switched', False) else "")),
    axis=1,
)

display_df = log_df[['hold_month', 'mode', 'hold', 'switch_str', 'ret_strategy_str', 'ret_spy_str', 'dd_str']].rename(columns={
    'hold_month': '보유월',
    'mode': '국면',
    'hold': '보유',
    'switch_str': '교체',
    'ret_strategy_str': '전략 수익률',
    'ret_spy_str': 'SPY 수익률',
    'dd_str': '낙폭',
})
# 최신이 위로 오도록 역순
st.dataframe(display_df.iloc[::-1], hide_index=True, use_container_width=True, height=600)
