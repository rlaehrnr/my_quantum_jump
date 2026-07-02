"""
6_❄️_스노우볼_포트.py
─────────────────────
동적 자산배분 전략 페이지 (탭 구성).

- 탭 1 "또 메리츠": 기존 스노우볼 전략 (조건1 모멘텀 + 조건2 밸류에이션).
- 탭 2 "맘 삼성":   레버리지 모멘텀 전략.
    · 필터: TIP·SPY 둘 다 11M MA 이격도 > 0 → 공격
    · 공격: FAS·SOXL·TQQQ·TMF 중 12M MA 이격도 > 0인 것 모두 동일가중
    · 방어: IEF·GLD·TBT 중 5M MA 이격도 1위 (미달 시 현금)

각 탭 구성은 동일: 공격/방어 현황 → 신호/필터 → 백테스트 성과 + 자산곡선 + 월별 로그.
새 탭을 추가하려면 render_* 함수를 만들어 아래 st.tabs에 연결하면 된다.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from utils.snowball import (
    load_monthly_prices, load_dividend_yield,
    # 또 메리츠
    compute_signals, run_backtest, compute_performance,
    SIGNAL_ASSETS, OFFENSE_ASSETS, DEFENSE_ASSETS, BENCHMARKS, VIXY_SPIKE,
    # 맘 삼성
    compute_signals_samsung, run_backtest_samsung,
    SS_FILTER_ASSETS, SS_OFFENSE_ASSETS, SS_DEFENSE_ASSETS, SS_CASH,
)
from utils.ui_components import inject_custom_css

st.set_page_config(page_title="스노우볼 포트", page_icon="❄️", layout="wide")
inject_custom_css()

# ==========================================
# 자산별 색상
# ==========================================
ASSET_COLORS = {
    # 또 메리츠
    'TQQQ': '#10B981', 'USD': '#F59E0B', 'GLD': '#FBBF24', 'TLT': '#3B82F6',
    'SQQQ': '#EF4444', 'SLV': '#71717A', 'CASH': '#6B7280',
    'SPY': '#8B5CF6', 'QQQ': '#8B5CF6', 'SOXX': '#EC4899',
    # 맘 삼성
    'FAS': '#F97316', 'SOXL': '#06B6D4', 'TMF': '#3B82F6',
    'IEF': '#22C55E', 'TBT': '#A855F7', 'TIP': '#EAB308',
}


# ==========================================
# 페이지 헤더
# ==========================================
st.markdown('''
    <div style="margin-bottom: 20px;">
        <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
            <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">❄️ 스노우볼 포트</h1>
        </div>
    </div>
''', unsafe_allow_html=True)


# ==========================================
# 데이터 로딩 (탭 공유)
# ==========================================
MONTHLY_DIR = 'data/snowball/monthly'

with st.spinner("데이터 로딩 중..."):
    prices = load_monthly_prices(MONTHLY_DIR)
    div_yield = load_dividend_yield(MONTHLY_DIR)

if prices.empty:
    st.error(
        f"📁 데이터 파일이 없습니다. `{MONTHLY_DIR}/` 폴더에 각 티커의 "
        f"`{{TICKER}}_과거_데이터.csv`(날짜/종가)와 `SP500_DIV.csv`를 넣어주세요."
    )
    st.stop()


# ==========================================
# 공용 렌더 헬퍼
# ==========================================
def _style_asset_table(rows, active, selected_set, value_label):
    """자산 모멘텀 표 Styler. selected_set에 든 티커 행을 모드색으로 강조.

    rows: [{'자산': ticker, value_label: value(비율, 예 0.12=12%)}, ...]
    active=False면 표 전체를 흐리게.
    """
    df = (pd.DataFrame(rows)
          .sort_values(value_label, ascending=False, na_position='last')
          .reset_index(drop=True))

    def _row_style(row):
        n = len(row)
        if active and row['자산'] in selected_set:
            c = ASSET_COLORS.get(row['자산'], '#6B7280')
            return [f'background-color: {c}55; font-weight: 800;'] * n
        if not active:
            return ['color: #9CA3AF;'] * n
        return [''] * n

    def _fmt(v):
        return 'N/A' if pd.isna(v) else f"{v*100:+.2f}%"

    def _color(row):
        v = row[value_label]
        if pd.isna(v):
            return 'color: #9CA3AF; font-weight: bold;'
        if v > 0:
            return 'color: #FF5252; font-weight: bold;'
        if v < 0:
            return 'color: #5C9DFF; font-weight: bold;'
        return ''

    def _apply_color(dfi):
        s = pd.DataFrame('', index=dfi.index, columns=dfi.columns)
        for i in dfi.index:
            s.loc[i, value_label] = _color(dfi.loc[i])
        return s

    return (df.style
            .apply(_row_style, axis=1)
            .apply(_apply_color, axis=None)
            .format({value_label: _fmt}))


def _mode_badge(defensive, hold_display):
    """공격/방어 모드 뱃지 (full width)."""
    if defensive:
        text, color = "🛡️ 방어 모드", "#EF4444"
    else:
        text, color = "⚔️ 공격 모드", "#10B981"
    st.markdown(
        f"<div style='width:100%; background:{color}18; border:2px solid {color}; "
        f"border-radius:10px; padding:12px 20px; margin-bottom:14px; text-align:center;'>"
        f"<span style='font-size:22px; font-weight:900; color:{color}; letter-spacing:1px;'>{text}</span>"
        f"<span style='font-size:14px; color:#6B7280; margin-left:12px;'>"
        f"현재 보유: <b style='color:#E5E7EB;'>{hold_display}</b></span></div>",
        unsafe_allow_html=True,
    )


def render_backtest_section(bt, perf, cost_rate, key_prefix, strat_color='#10B981', strat_name='전략'):
    """백테스트 카드 + 자산곡선 + 월별 로그 (탭 공용)."""
    bms = perf.get('benchmarks', {})
    qqq = bms.get('QQQ')

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CAGR", f"{perf['cagr']*100:.1f}%",
              delta=(f"vs QQQ {qqq['cagr']*100:.1f}%" if qqq else None))
    c2.metric("MDD", f"{perf['mdd']*100:.1f}%",
              delta=(f"vs QQQ {qqq['mdd']*100:.1f}%" if qqq else None), delta_color="inverse")
    c3.metric("샤프 비율", f"{perf['sharpe']:.2f}",
              delta=(f"vs QQQ {qqq['sharpe']:.2f}" if qqq else None))
    c4.metric("누적 수익", f"{perf['cum_return']*100:,.0f}%",
              delta=(f"비용 0% 시 {perf['cum_gross_return']*100:,.0f}%" if cost_rate > 0 else None),
              delta_color="off")
    c5.metric("공격 비중", f"{perf['offense_pct']*100:.0f}%",
              delta=f"{perf.get('offense_months', 0)}개월 / {perf['n_months']}개월")

    st.markdown("#### 📉 자산 곡선 (Log Scale)")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=bt['hold_month'], y=bt['cum_strategy'], mode='lines', name=strat_name,
        line=dict(color=strat_color, width=2.5),
    ))
    for b in BENCHMARKS:
        col = f'cum_{b}'
        if col in bt.columns and bt[f'ret_{b}'].notna().sum() > 0:
            fig.add_trace(go.Scatter(
                x=bt['hold_month'], y=bt[col], mode='lines', name=f'{b} (Buy & Hold)',
                line=dict(color=ASSET_COLORS.get(b, '#9CA3AF'), width=2, dash='dash'),
            ))
    fig.update_layout(
        yaxis_type='log', height=420, hovermode='x unified',
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    fig.update_yaxes(title='누적 (1=원금)')
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_curve")

    st.markdown("#### 📋 전체 월별 로그")
    log_df = bt.copy()
    log_df['ret_strategy_str'] = log_df['ret_strategy'].apply(lambda x: f"{x*100:+.2f}%")
    log_df['cum_strategy_str'] = log_df['cum_strategy'].apply(lambda x: f"{(x-1)*100:+.1f}%")
    log_df['mode'] = log_df['defensive'].apply(lambda d: "🛡️ 방어" if d else "⚔️ 공격")
    log_df['dd_str'] = log_df['dd_strategy'].apply(lambda x: f"{x*100:.1f}%")

    cols = ['hold_month', 'mode', 'hold', 'ret_strategy_str', 'cum_strategy_str']
    rename_map = {'hold_month': '보유월', 'mode': '국면', 'hold': '보유',
                  'ret_strategy_str': '전략 수익률', 'cum_strategy_str': '누적 수익률'}
    for b in BENCHMARKS:
        rcol = f'ret_{b}'
        if rcol in log_df.columns and log_df[rcol].notna().sum() > 0:
            scol = f'{b}_str'
            log_df[scol] = log_df[rcol].apply(lambda x: f"{x*100:+.2f}%" if pd.notna(x) else "-")
            cols.append(scol)
            rename_map[scol] = f'{b} 수익률'
    cols.append('dd_str')
    rename_map['dd_str'] = '낙폭'
    display_df = log_df[cols].rename(columns=rename_map)

    if bms:
        parts = [f"{b} · CAGR {v['cagr']*100:+.1f}% · MDD {v['mdd']*100:.1f}% · 누적 {v['cum_return']*100:,.0f}%"
                 for b, v in bms.items()]
        st.markdown(
            "<div style='color:#9CA3AF; font-size:13px; margin:0 0 2px 2px;'>"
            "📊 벤치마크 전기간 &nbsp;&nbsp;" + " &nbsp;|&nbsp; ".join(parts) + "</div>",
            unsafe_allow_html=True,
        )
    st.dataframe(display_df.iloc[::-1], hide_index=True, use_container_width=True, height=600,
                 key=f"{key_prefix}_log")


# ==========================================
# 탭 1: 또 메리츠 (기존 스노우볼)
# ==========================================
def render_meritz():
    missing_core = [t for t in SIGNAL_ASSETS + OFFENSE_ASSETS + DEFENSE_ASSETS if t not in prices.columns]
    if missing_core:
        st.warning(f"⚠️ 누락된 핵심 ETF: {', '.join(missing_core)}. 정상 동작을 위해 모두 필요합니다.")
    if div_yield.empty:
        st.info("ℹ️ 배당수익률 파일이 없어 조건2(밸류에이션)는 항상 False로 처리됩니다.")

    signals = compute_signals(prices, div_yield)

    valid = signals.index[signals['hold'].notna()]
    if len(valid) == 0:
        st.error("유효한 신호월이 없습니다. (데이터 워밍업 부족 또는 ETF 파일 누락)")
        return
    lm = valid[-1]
    last = signals.loc[lm]
    defensive_now = bool(last['defensive'])
    selected_hold = last['hold']

    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:800; margin-bottom:8px;'>공격 · 방어 자산 현황 "
        f"<span style='font-size:12px; color:#9CA3AF; font-weight:500;'>(기준: {lm} 월말)</span></div>",
        unsafe_allow_html=True)
    _mode_badge(defensive_now, f"<span style='color:{ASSET_COLORS.get(selected_hold,'#E5E7EB')};'>{selected_hold}</span>")

    col_off, col_def = st.columns(2)
    with col_off:
        is_active = not defensive_now
        label = "⚔️ 공격 자산 (12개월 수익률)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        rows = [{'자산': t, '수익률': last.get(f'ret12_{t}', np.nan)} for t in OFFENSE_ASSETS]
        sel = {selected_hold} if is_active else set()
        st.dataframe(_style_asset_table(rows, is_active, sel, '수익률'),
                     hide_index=True, use_container_width=True, key="meritz_off")
    with col_def:
        is_active = defensive_now
        label = "🛡️ 방어 자산 (12개월 MA 이격도)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        rows = [{'자산': t, '이격도': last.get(f'disp12_{t}', np.nan)} for t in DEFENSE_ASSETS]
        sel = {selected_hold} if is_active else set()
        st.dataframe(_style_asset_table(rows, is_active, sel, '이격도'),
                     hide_index=True, use_container_width=True, key="meritz_def")

    # 위험회피 옵션 (조건1 / 조건2)
    st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:18px 0 10px 0;'>위험회피 옵션</div>",
                unsafe_allow_html=True)
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        cond1_on = bool(last['cond1'])
        badge = (f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 발동</span>"
                 if cond1_on else
                 f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>미발동</span>")
        st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>조건1: 모멘텀 신호</b> "
                    f"<span style='font-size:12px; color:#9CA3AF;'>(TIP·VWO·VEA 6M &lt; 0 &amp; VIXY 6M &lt; 0 또는 ≥{VIXY_SPIKE*100:.0f}%)</span></div>",
                    unsafe_allow_html=True)
        data = []
        for t in SIGNAL_ASSETS:
            v = last.get(f'ret6_{t}', np.nan)
            if pd.notna(v):
                if t == 'VIXY':
                    ok = (v < 0) or (v >= VIXY_SPIKE); cond = f"<0 또는 ≥{VIXY_SPIKE*100:.0f}%"
                else:
                    ok = v < 0; cond = "<0"
                data.append({'자산': t, '6M 수익률': f"{v*100:+.2f}%", '조건': cond, '충족?': '✅' if ok else '❌'})
            else:
                data.append({'자산': t, '6M 수익률': 'N/A', '조건': '-', '충족?': '⚠️'})
        if data:
            st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True, key="meritz_c1")
    with col_c2:
        cond2_on = bool(last['cond2'])
        badge = (f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 발동</span>"
                 if cond2_on else
                 f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>미발동</span>")
        st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>조건2: 밸류에이션</b> "
                    f"<span style='font-size:12px; color:#9CA3AF;'>(배당 5Y 백분위 ≤ 10%)</span></div>",
                    unsafe_allow_html=True)
        div_pct = last['div_pct']
        div_val = last.get('div_value', np.nan)
        div_thr = last.get('div_threshold', np.nan)
        div_rank = last.get('div_rank', np.nan)
        div_total = last.get('div_total', np.nan)
        if pd.notna(div_pct):
            m1, m2 = st.columns(2)
            with m1:
                rank_str = (f"{int(div_rank)}등 / {int(div_total)}개월"
                            if pd.notna(div_rank) and pd.notna(div_total) else f"{div_pct:.1f}%")
                triggered = div_pct <= 10
                delta = f"{div_pct:.1f}% → 10% 이하 발동" if triggered else f"{div_pct:.1f}% → 안전 구간"
                st.metric("5Y 밸류 순위 (1등=가장 비쌈)", rank_str, delta=delta,
                          delta_color="inverse" if triggered else "off")
            with m2:
                if pd.notna(div_val):
                    if pd.notna(div_thr):
                        triggered = bool(div_pct <= 10)
                        cmp = f"{div_val:.2f}% {'≤' if triggered else '>'} 기준점 {div_thr:.2f}%"
                        st.metric("현재 배당수익률", f"{div_val:.2f}%", delta=cmp,
                                  delta_color="inverse" if triggered else "off")
                    else:
                        st.metric("현재 배당수익률", f"{div_val:.2f}%")
        else:
            st.info("배당 데이터 부족 (60개월 워밍업 또는 파일 없음)")

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
    with t_col:
        st.markdown("### 📈 백테스트 성과")
    with s_col:
        cost_pct = st.slider("거래비용 %/교체", 0.0, 1.0, 0.25, 0.05, format="%.2f%%",
                             key="meritz_cost",
                             help="종목 교체 시에만 차감(턴오버). 벤치마크는 매수 후 보유로 비용 없음.")
    cost_rate = cost_pct / 100.0
    bt = run_backtest(prices, signals, cost=cost_rate)
    if bt.empty:
        st.warning("백테스트 데이터가 충분하지 않습니다.")
        return
    perf = compute_performance(bt)
    render_backtest_section(bt, perf, cost_rate, key_prefix="meritz",
                            strat_color='#10B981', strat_name='또 메리츠 전략')


# ==========================================
# 탭 2: 맘 삼성 (레버리지 모멘텀)
# ==========================================
def render_samsung():
    need = SS_FILTER_ASSETS + SS_OFFENSE_ASSETS + SS_DEFENSE_ASSETS
    missing = [t for t in need if t not in prices.columns]
    if missing:
        st.warning(
            f"⚠️ 누락된 ETF: {', '.join(missing)}. 자동 업데이트(update_snowball.py)가 "
            f"이 종목들을 아직 생성하지 않았을 수 있습니다. Actions에서 워크플로우를 한 번 실행하세요."
        )

    signals = compute_signals_samsung(prices)
    valid = signals.index[signals['hold'].notna()]
    if len(valid) == 0:
        st.error("유효한 신호월이 없습니다. (데이터 워밍업 부족 또는 신규 ETF 파일 누락)")
        return
    lm = valid[-1]
    last = signals.loc[lm]
    defensive_now = bool(last['defensive'])
    holds = last['holds'] or []
    hold_set = set(holds)

    # 보유 표시 (공격이면 여러 종목 색칠)
    if holds == [SS_CASH]:
        hold_disp = "<span style='color:#6B7280;'>CASH</span>"
    else:
        hold_disp = " · ".join(
            f"<span style='color:{ASSET_COLORS.get(t,'#E5E7EB')};'>{t}</span>" for t in holds)

    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:800; margin-bottom:8px;'>공격 · 방어 자산 현황 "
        f"<span style='font-size:12px; color:#9CA3AF; font-weight:500;'>(기준: {lm} 월말)</span></div>",
        unsafe_allow_html=True)
    _mode_badge(defensive_now, hold_disp)

    col_off, col_def = st.columns(2)
    with col_off:
        is_active = not defensive_now
        label = "⚔️ 공격 자산 (12개월 MA 이격도)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>이격도 &gt; 0 인 종목 모두 동일가중</div>",
                    unsafe_allow_html=True)
        rows = [{'자산': t, '이격도': last.get(f'disp12_{t}', np.nan)} for t in SS_OFFENSE_ASSETS]
        sel = hold_set if is_active else set()
        st.dataframe(_style_asset_table(rows, is_active, sel, '이격도'),
                     hide_index=True, use_container_width=True, key="ss_off")
    with col_def:
        is_active = defensive_now
        label = "🛡️ 방어 자산 (5개월 MA 이격도)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>1위 1개 보유 (이격도 ≤ 0 이면 현금)</div>",
                    unsafe_allow_html=True)
        rows = [{'자산': t, '이격도': last.get(f'disp5_{t}', np.nan)} for t in SS_DEFENSE_ASSETS]
        sel = hold_set if (is_active and holds != [SS_CASH]) else set()
        st.dataframe(_style_asset_table(rows, is_active, sel, '이격도'),
                     hide_index=True, use_container_width=True, key="ss_def")

    # 진입 필터 (위험회피 옵션 대체)
    st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:18px 0 10px 0;'>진입 필터</div>",
                unsafe_allow_html=True)
    filt_pass = bool(last['filter_pass'])
    badge = (f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>✅ 통과 (공격 허용)</span>"
             if filt_pass else
             f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 미통과 (방어)</span>")
    st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>필터: 추세 확인</b> "
                f"<span style='font-size:12px; color:#9CA3AF;'>(TIP·SPY 둘 다 11M MA 이격도 &gt; 0)</span></div>",
                unsafe_allow_html=True)
    fdata = []
    for t in SS_FILTER_ASSETS:
        v = last.get(f'disp11_{t}', np.nan)
        if pd.notna(v):
            fdata.append({'자산': t, '11M 이격도': f"{v*100:+.2f}%", '조건': '>0', '충족?': '✅' if v > 0 else '❌'})
        else:
            fdata.append({'자산': t, '11M 이격도': 'N/A', '조건': '>0', '충족?': '⚠️'})
    st.dataframe(pd.DataFrame(fdata), hide_index=True, use_container_width=True, key="ss_filter")

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
    with t_col:
        st.markdown("### 📈 백테스트 성과")
    with s_col:
        cost_pct = st.slider("거래비용 %/교체", 0.0, 1.0, 0.25, 0.05, format="%.2f%%",
                             key="ss_cost",
                             help="새로 매수하는 비중만큼 차감(턴오버). 벤치마크는 매수 후 보유로 비용 없음.")
    cost_rate = cost_pct / 100.0
    bt = run_backtest_samsung(prices, signals, cost=cost_rate)
    if bt.empty:
        st.warning("백테스트 데이터가 충분하지 않습니다. (레버리지 ETF 상장 시점상 2011년 전후부터 시작)")
        return
    perf = compute_performance(bt)
    render_backtest_section(bt, perf, cost_rate, key_prefix="ss",
                            strat_color='#06B6D4', strat_name='맘 삼성 전략')


# ==========================================
# 탭 배치
# ==========================================
tab1, tab2 = st.tabs(["🌀 또 메리츠", "🏢 맘 삼성"])
with tab1:
    render_meritz()
with tab2:
    render_samsung()
