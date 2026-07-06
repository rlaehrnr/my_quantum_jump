"""
6_❄️_스노우볼_포트.py
─────────────────────
동적 자산배분 전략 페이지 (탭 구성).

- 탭 1 "또 메리츠": 기존 스노우볼 전략 (조건1 모멘텀 + 조건2 밸류에이션).
- 탭 2 "맘 삼성":   레버리지 모멘텀 전략 (백테스트로 확정).
    · 필터: TIP·SPY 둘 다 9M MA 이격도 > 0 → 공격 (제목 옆 토글/슬라이더로 조절)
    · 공격: FAS·SOXL·TQQQ·TMF 중 12M MA 이격도 > 0인 것 모두 동일가중
    · 방어: IEF50 · GLD50 고정

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
    SS_FILTER_ASSETS, SS_OFFENSE_ASSETS, SS_DEFENSE_ASSETS, SS_CASH, SS_FILTER_WIN,
    compute_signals_so, run_backtest_so,
    SO_FILTER_ASSET, SO_OFFENSE_ASSETS, SO_DEFENSE_ASSETS, SO_TOPK,
    SIGNAL_ASSETS, C1_RISK_ASSETS, VIXY_SPIKE,
    # 또 ISA (국내)
    load_ko_prices, compute_signals_ko, run_backtest_ko,
    KO_OFFENSE, KO_DEFENSE, KO_TICKER_NAMES, KO_FILTER_ASSET, KO_FILTER_WIN,
    KO_TOPK, KO_DEF_TOPK, KO_BENCHMARKS, KO_ABSMOM_WIN, KO_MOM_WINDOWS, KO_DEF_WIN,
    # 또 연금 (국내 듀얼모멘텀)
    load_pen_prices, compute_signals_pension, run_backtest_pension,
    PEN_NASDAQ, PEN_KOSPI, PEN_OFFENSE, PEN_DEFENSE, PEN_TICKER_NAMES,
    PEN_OFF_WIN, PEN_DEF_WIN, PEN_FILTER_WIN, PEN_BENCHMARKS,
    # 쏘 연금 (국내 나스닥 단일 + cond1 위험회피)
    load_ssopen_prices, compute_signals_ssopen, run_backtest_ssopen,
    SSOPEN_NASDAQ, SSOPEN_DEFENSE, SSOPEN_DEF_WINDOWS, SSOPEN_TICKER_NAMES, SSOPEN_BENCHMARKS,
    # 맘 비과세 (국내 글로벌 듀얼모멘텀 + cond1)
    load_mamtax_prices, compute_signals_mamtax, run_backtest_mamtax,
    MAMTAX_OFFENSE, MAMTAX_DEFENSE, MAMTAX_TICKER_NAMES, MAMTAX_BENCHMARKS,
    mamtax_live_ticker, mamtax_live_name,
)
from utils.ui_components import inject_custom_css, get_monthly_heatmap, get_mdd_history

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
    # 쏘 삼성 (SPY/QQQ/GLD/IEF는 위와 공유)
    'EWY': '#F59E0B', 'FDN': '#14B8A6', 'IBB': '#A855F7', 'LIT': '#84CC16',
    'SMH': '#06B6D4', 'XLE': '#EF4444', 'XLF': '#3B82F6',
    # 또 ISA (국내 ETF, 종목코드 키)
    '379810': '#10B981', '309230': '#8B5CF6', '360750': '#6366F1', '102110': '#F59E0B',
    '130730': '#94A3B8', '152380': '#3B82F6', '332620': '#0EA5E9', '411060': '#FBBF24',
    '137610': '#84CC16', '182480': '#14B8A6',
    '217770': '#EF4444', '225130': '#F97316', '455030': '#22C55E',
    # 또 연금 (133690 나스닥·102110 코스피는 offense, 방어 4종)
    '133690': '#10B981', '305080': '#3B82F6', '261220': '#EF4444', '329200': '#14B8A6',
    # 쏘 연금 (추가 방어: 국고채10년·SOL초단기채)
    '148070': '#0EA5E9', '469830': '#94A3B8',
    # 맘 비과세 (실운용 티커 기준)
    '379810': '#10B981', '278530': '#3B82F6', '192090': '#EF4444', '453870': '#F97316',
    '241180': '#14B8A6', '229200': '#A855F7', '360750': '#6366F1', '466940': '#F59E0B',
    '371160': '#EC4899', '144600': '#94A3B8', '455030': '#64748B',
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


def _pct(v):
    return round(v * 100, 2) if pd.notna(v) else np.nan


def build_stats_df(perf, cost_rate):
    """성과 dict → 통계 DataFrame (화면·엑셀 공용)."""
    rows = [
        ('CAGR', f"{perf['cagr']*100:.2f}%"),
        ('MDD', f"{perf['mdd']*100:.2f}%"),
        ('샤프 비율', f"{perf['sharpe']:.2f}"),
        ('Sortino', f"{perf.get('sortino', 0):.2f}"),
        ('변동성(연)', f"{perf['vol']*100:.2f}%"),
        ('누적 수익', f"{perf['cum_return']*100:,.1f}%"),
        ('승률', f"{perf.get('win_rate',0)*100:.1f}%"),
        ('공격 비중', f"{perf['offense_pct']*100:.0f}% ({perf.get('offense_months',0)}/{perf['n_months']}개월)"),
        ('종목 교체 횟수', f"{perf.get('n_switches',0)}회"),
        ('거래비용(누적)', f"{perf.get('total_cost',0)*100:.1f}%"),
        ('비용 0% 시 누적', f"{perf.get('cum_gross_return',0)*100:,.1f}%"),
    ]
    for b, v in perf.get('benchmarks', {}).items():
        rows.append((f'[벤치] {b} CAGR', f"{v['cagr']*100:.2f}%"))
        rows.append((f'[벤치] {b} MDD', f"{v['mdd']*100:.2f}%"))
    return pd.DataFrame(rows, columns=['지표', '값'])


def build_meritz_detail(signals, bt):
    """또 메리츠 월별 상세 근거표."""
    rows = []
    for _, r in bt.iterrows():
        m = pd.Period(r['signal_month'], 'M')
        s = signals.loc[m]
        rows.append({
            '보유월': r['hold_month'],
            '국면': '🛡️방어' if r['defensive'] else '⚔️공격',
            'TIP 6M': _pct(s.get('ret6_TIP')), 'VWO 6M': _pct(s.get('ret6_VWO')),
            'VEA 6M': _pct(s.get('ret6_VEA')), 'VIXY 6M': _pct(s.get('ret6_VIXY')),
            '조건1': '발동' if s.get('cond1') else '-',
            '배당(%)': round(s['div_value'], 2) if pd.notna(s.get('div_value')) else np.nan,
            '배당순위': (f"{int(s['div_rank'])}/{int(s['div_total'])}"
                       if pd.notna(s.get('div_rank')) and pd.notna(s.get('div_total')) else '-'),
            '조건2': '발동' if s.get('cond2') else '-',
            'TQQQ 12M': _pct(s.get('ret12_TQQQ')), 'USD 12M': _pct(s.get('ret12_USD')),
            'GLD 이격': _pct(s.get('disp12_GLD')), 'TLT 이격': _pct(s.get('disp12_TLT')),
            'SQQQ 이격': _pct(s.get('disp12_SQQQ')), 'SLV 이격': _pct(s.get('disp12_SLV')),
            '보유': r['hold'],
            '전략수익률(%)': round(r['ret_strategy']*100, 2),
            '누적(%)': round((r['cum_strategy']-1)*100, 1),
            '낙폭(%)': round(r['dd_strategy']*100, 1),
        })
    return pd.DataFrame(rows)


def build_samsung_detail(signals, bt):
    """맘 삼성 월별 상세 근거표 (필터 → 공격/방어 후보 → 보유 → 결과)."""
    rows = []
    for _, r in bt.iterrows():
        m = pd.Period(r['signal_month'], 'M')
        s = signals.loc[m]
        rows.append({
            '보유월': r['hold_month'],
            '국면': '🛡️방어' if r['defensive'] else '⚔️공격',
            'TIP 필터': _pct(s.get('dispF_TIP')), 'SPY 필터': _pct(s.get('dispF_SPY')),
            '필터': '통과' if s.get('filter_pass') else '이탈',
            'FAS 12M': _pct(s.get('disp12_FAS')), 'SOXL 12M': _pct(s.get('disp12_SOXL')),
            'TQQQ 12M': _pct(s.get('disp12_TQQQ')), 'TMF 12M': _pct(s.get('disp12_TMF')),
            'IEF 5M': _pct(s.get('disp_IEF')), 'GLD 5M': _pct(s.get('disp_GLD')),
            '보유': r['hold'],
            '전략수익률(%)': round(r['ret_strategy']*100, 2),
            '누적(%)': round((r['cum_strategy']-1)*100, 1),
            '낙폭(%)': round(r['dd_strategy']*100, 1),
        })
    return pd.DataFrame(rows)


def build_so_detail(signals, bt):
    """쏘 삼성 월별 상세 근거표 (SPY 필터 → 모멘텀 점수 → 보유 → 결과)."""
    rows = []
    for _, r in bt.iterrows():
        m = pd.Period(r['signal_month'], 'M')
        s = signals.loc[m]
        row = {
            '보유월': r['hold_month'],
            '국면': '🛡️방어' if r['defensive'] else '⚔️공격',
            'SPY 필터점수': _pct(s.get('score_SPY_filter')),
            '필터': '통과' if s.get('filter_pass') else '이탈',
            '리스크오프': 'ON' if s.get('riskoff') else '-',
        }
        for t in SO_OFFENSE_ASSETS:
            sc = s.get(f'score_{t}')
            ab = s.get(f'abs_{t}')
            # 모멘텀 점수 (4M MA 이격도) 병기 — 4M<0이면 공격 제외 대상
            row[t] = f"{_pct(sc)} ({_pct(ab)})"
        row['보유'] = r['hold']
        row['전략수익률(%)'] = round(r['ret_strategy']*100, 2)
        row['누적(%)'] = round((r['cum_strategy']-1)*100, 1)
        row['낙폭(%)'] = round(r['dd_strategy']*100, 1)
        rows.append(row)
    return pd.DataFrame(rows)


def _heatmap_pivot_for_excel(df_res, col):
    """엑셀용 연×월 수익률 피벗 (스타일 없는 순수 DataFrame)."""
    t = df_res.copy()
    t['Y'] = t['투자월'].str[:4]
    t['M'] = t['투자월'].str[5:7].astype(int)
    p = t.pivot(index='Y', columns='M', values=col)
    for mm in range(1, 13):
        if mm not in p.columns:
            p[mm] = np.nan
    p = p[list(range(1, 13))]
    p.columns = [f'{mm}월' for mm in range(1, 13)]
    p['연수익률'] = p.apply(
        lambda row: ((1 + row.dropna()/100).prod() - 1) * 100 if len(row.dropna()) else np.nan, axis=1)
    return p.round(2)


def build_report_excel(settings_dict, stats_df, detail_df, df_res, cum_df, mdd_df, strat_name):
    """월별 상세근거 + 히트맵 + MDD TOP10 + 누적 다중 시트 엑셀 바이트."""
    import io
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as w:
        set_df = pd.DataFrame(list(settings_dict.items()), columns=['설정 항목', '값'])
        set_df.to_excel(w, sheet_name='요약_통계', index=False, startrow=0)
        stats_df.to_excel(w, sheet_name='요약_통계', index=False, startrow=len(set_df) + 2)
        detail_df.to_excel(w, sheet_name='월별_상세근거', index=False)
        _heatmap_pivot_for_excel(df_res, strat_name).reset_index().to_excel(
            w, sheet_name='월별_히트맵', index=False)
        if not mdd_df.empty:
            mdd_df.to_excel(w, sheet_name='MDD_TOP10', index=False)
        cum_df.reset_index().to_excel(w, sheet_name='누적_수익', index=False)
    return out.getvalue()


def render_backtest_section(bt, perf, cost_rate, key_prefix, strat_color, strat_name,
                           detail_df, settings_dict):
    """백테스트 카드 + 자산곡선 + 월별 로그 (탭 공용)."""
    bms = perf.get('benchmarks', {})
    qqq = bms.get('QQQ')

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("CAGR", f"{perf['cagr']*100:.1f}%",
              delta=(f"vs QQQ {qqq['cagr']*100:.1f}%" if qqq else None))
    c2.metric("MDD", f"{perf['mdd']*100:.1f}%",
              delta=(f"vs QQQ {qqq['mdd']*100:.1f}%" if qqq else None), delta_color="inverse")
    c3.metric("샤프 비율", f"{perf['sharpe']:.2f}",
              delta=(f"vs QQQ {qqq['sharpe']:.2f}" if qqq else None))
    c4.metric("Sortino", f"{perf.get('sortino', 0):.2f}",
              delta=(f"vs QQQ {qqq.get('sortino', 0):.2f}" if qqq else None),
              help="하락 변동성만 위험으로 보는 지표(상승 급등은 벌주지 않음). 레버리지 전략에 더 공정.")
    c5.metric("누적 수익", f"{perf['cum_return']*100:,.0f}%",
              delta=(f"비용 0% 시 {perf['cum_gross_return']*100:,.0f}%" if cost_rate > 0 else None),
              delta_color="off")
    c6.metric("공격 비중", f"{perf['offense_pct']*100:.0f}%",
              delta=f"{perf.get('offense_months', 0)}개월 / {perf['n_months']}개월")

    # 히트맵 + MDD TOP10
    df_res = pd.DataFrame({'투자월': bt['hold_month'].values,
                           strat_name: (bt['ret_strategy'] * 100).values})
    equity = pd.Series(bt['cum_strategy'].values, index=bt['hold_month'].values)
    mdd_df = get_mdd_history(equity)

    st.markdown("#### 🗓️ 월별 수익률 히트맵 & MDD TOP 10")
    col_hm, col_mdd = st.columns([7.2, 2.8])
    with col_hm:
        st.dataframe(get_monthly_heatmap(df_res, strat_name), use_container_width=True,
                     key=f"{key_prefix}_heatmap")
    with col_mdd:
        if not mdd_df.empty:
            st.dataframe(mdd_df, use_container_width=True, hide_index=True, key=f"{key_prefix}_mdd")
        else:
            st.info("낙폭 구간 없음")

    # 월별 상세 근거 + 엑셀
    stats_df = build_stats_df(perf, cost_rate)
    cum_cols = {strat_name: bt['cum_strategy'].values}
    for b in BENCHMARKS:
        if f'cum_{b}' in bt.columns and bt[f'ret_{b}'].notna().sum() > 0:
            cum_cols[b] = bt[f'cum_{b}'].values
    cum_df = pd.DataFrame(cum_cols, index=bt['hold_month'].values)
    cum_df.index.name = '보유월'

    hdr, dl = st.columns([7.5, 2.5])
    with hdr:
        st.markdown("#### 📋 월별 상세 근거")
    with dl:
        xls = build_report_excel(settings_dict, stats_df, detail_df, df_res, cum_df, mdd_df, strat_name)
        st.download_button(
            "📥 종합 엑셀 리포트", data=xls,
            file_name=f"스노우볼_{strat_name}_리포트.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True, key=f"{key_prefix}_xls")

    bms = perf.get('benchmarks', {})
    if bms:
        parts = [f"{b} · CAGR {v['cagr']*100:+.1f}% · MDD {v['mdd']*100:.1f}% · 누적 {v['cum_return']*100:,.0f}%"
                 for b, v in bms.items()]
        st.markdown(
            "<div style='color:#9CA3AF; font-size:13px; margin:0 0 2px 2px;'>"
            "📊 벤치마크 전기간 &nbsp;&nbsp;" + " &nbsp;|&nbsp; ".join(parts) + "</div>",
            unsafe_allow_html=True)
    # 최신이 위로
    st.dataframe(detail_df.iloc[::-1], hide_index=True, use_container_width=True,
                 height=560, key=f"{key_prefix}_detail")

    # 자산 곡선 — 맨 아래 접이식 (기본 접힘)
    with st.expander("📉 자산 곡선 (Log Scale) 보기", expanded=False):
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
    detail_df = build_meritz_detail(signals, bt)
    settings_dict = {
        '전략': '또 메리츠',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '공격 자산': ', '.join(OFFENSE_ASSETS),
        '방어 자산': ', '.join(DEFENSE_ASSETS),
        '벤치마크': ', '.join(BENCHMARKS),
    }
    render_backtest_section(bt, perf, cost_rate, key_prefix="meritz",
                            strat_color='#10B981', strat_name='또 메리츠 전략',
                            detail_df=detail_df, settings_dict=settings_dict)


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

    # 컨트롤 상태(토글·슬라이더)는 아래 '진입 필터' 줄에 배치하지만,
    # 값은 상단 현황 카드에도 반영돼야 하므로 session_state에서 먼저 읽어 신호를 계산한다.
    st.session_state.setdefault('ss_use_filter', True)
    st.session_state.setdefault('ss_filter_win', SS_FILTER_WIN)
    use_filter = bool(st.session_state['ss_use_filter'])
    filter_win = int(st.session_state['ss_filter_win'])

    signals = compute_signals_samsung(prices, use_filter=use_filter, filter_win=filter_win)
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
        label = "⚔️ 공격 자산 (12개월 MA · 공격 전용)" + ("" if is_active else "  · 비활성")
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
        label = "🛡️ 방어 자산 (IEF50 · GLD50 고정)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>국채+금 반반 고정 (참고: 5M 이격도)</div>",
                    unsafe_allow_html=True)
        rows = [{'자산': t, '이격도': last.get(f'disp_{t}', np.nan)} for t in SS_DEFENSE_ASSETS]
        sel = hold_set if is_active else set()
        st.dataframe(_style_asset_table(rows, is_active, sel, '이격도'),
                     hide_index=True, use_container_width=True, key="ss_def")

    # 진입 필터 — 제목 줄 오른쪽에 토글 + N 슬라이더 (새 줄 없이 한 줄 배치)
    ft_col, tog_col, sld_col = st.columns([2.0, 1.1, 1.6])
    with ft_col:
        st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:10px 0 0 0;'>진입 필터</div>",
                    unsafe_allow_html=True)
    with tog_col:
        st.toggle("필터 사용", key="ss_use_filter",
                  help="끄면 필터를 무시하고 공격 후보가 있으면 항상 공격 → 필터 효과를 바로 비교.")
    with sld_col:
        st.slider("필터 MA(개월)", 5, 14, key="ss_filter_win",
                  help="TIP·SPY 이동평균 개월. 짧을수록 하락 전환에 빠르게 반응(백테스트 기본 9).")

    filt_pass = bool(last['filter_pass'])
    badge = (f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>✅ 통과 (공격 허용)</span>"
             if filt_pass else
             f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 미통과 (방어)</span>")
    off_note = (" &nbsp; <span style='color:#F59E0B;'>· 필터 OFF: 판단엔 미적용(표는 실제 상태)</span>"
                if not use_filter else "")
    st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>필터: 추세 확인</b> "
                f"<span style='font-size:12px; color:#9CA3AF;'>(TIP·SPY 둘 다 {filter_win}M MA 이격도 &gt; 0){off_note}</span></div>",
                unsafe_allow_html=True)
    fdata = []
    for t in SS_FILTER_ASSETS:
        v = last.get(f'dispF_{t}', np.nan)
        if pd.notna(v):
            fdata.append({'자산': t, f'{filter_win}M 이격도': f"{v*100:+.2f}%", '조건': '>0', '충족?': '✅' if v > 0 else '❌'})
        else:
            fdata.append({'자산': t, f'{filter_win}M 이격도': 'N/A', '조건': '>0', '충족?': '⚠️'})
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
    detail_df = build_samsung_detail(signals, bt)
    settings_dict = {
        '전략': '맘 삼성',
        '진입 필터': f"{'사용' if use_filter else '미사용(OFF)'} · TIP·SPY {filter_win}M MA",
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '공격': ', '.join(SS_OFFENSE_ASSETS) + ' (12M MA 이격도 > 0, 동일가중)',
        '방어': 'IEF 50% · GLD 50% 고정',
        '벤치마크': ', '.join(BENCHMARKS),
    }
    render_backtest_section(bt, perf, cost_rate, key_prefix="ss",
                            strat_color='#06B6D4', strat_name='맘 삼성 전략',
                            detail_df=detail_df, settings_dict=settings_dict)


def render_so():
    need = [SO_FILTER_ASSET] + SO_OFFENSE_ASSETS + SO_DEFENSE_ASSETS
    missing = [t for t in need if t not in prices.columns]
    if missing:
        st.warning(
            f"⚠️ 누락된 ETF: {', '.join(missing)}. 자동 업데이트(update_snowball.py)가 "
            f"이 종목들을 아직 생성하지 않았을 수 있습니다. Actions에서 워크플로우를 한 번 실행하세요."
        )

    st.session_state.setdefault('so_use_riskoff', True)
    use_riskoff = bool(st.session_state['so_use_riskoff'])
    signals = compute_signals_so(prices, use_riskoff=use_riskoff)
    valid = signals.index[signals['hold'].notna()]
    if len(valid) == 0:
        st.error("유효한 신호월이 없습니다. (데이터 워밍업 부족 또는 신규 ETF 파일 누락)")
        return
    lm = valid[-1]
    last = signals.loc[lm]
    defensive_now = bool(last['defensive'])
    holds = last['holds'] or []
    hold_set = set(holds)
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
        label = "⚔️ 공격 자산 (1·3·6·12M 모멘텀 점수)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>점수 상위 2등 중 4M MA 이격도 &gt; 0 인 것만 50:50 (둘 다 아래면 방어)</div>",
                    unsafe_allow_html=True)
        def _fmt_ab(v):
            return 'N/A' if pd.isna(v) else f"{v*100:+.1f}%"
        rows = [{'자산': t,
                 '모멘텀': last.get(f'score_{t}', np.nan),
                 '4M MA': _fmt_ab(last.get(f'abs_{t}', np.nan))} for t in SO_OFFENSE_ASSETS]
        sel = hold_set if is_active else set()
        st.dataframe(_style_asset_table(rows, is_active, sel, '모멘텀'),
                     hide_index=True, use_container_width=True, key="so_off")
    with col_def:
        is_active = defensive_now
        label = "🛡️ 방어 자산 (GLD50 · IEF50 고정)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>금+국채 반반 고정 (모멘텀 무관, 항상 50:50)</div>",
                    unsafe_allow_html=True)
        def_rows = [{'자산': t, '비중': '50%'} for t in SO_DEFENSE_ASSETS]
        ddf = pd.DataFrame(def_rows)
        if is_active:
            def _def_style(row):
                c = ASSET_COLORS.get(row['자산'], '#6B7280')
                return [f'background-color: {c}55; font-weight: 800;'] * len(row)
            sty = ddf.style.apply(_def_style, axis=1)
        else:
            sty = ddf.style.apply(lambda row: ['color: #9CA3AF;'] * len(row), axis=1)
        st.dataframe(sty, hide_index=True, use_container_width=True, key="so_def")

    # 회피 필터 (SPY 모멘텀 점수) — 제목 옆에 리스크오프 토글
    rf_col, ro_col = st.columns([2.6, 1.4])
    with rf_col:
        st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:16px 0 0 0;'>회피 필터</div>",
                    unsafe_allow_html=True)
    with ro_col:
        st.toggle("리스크오프(cond1) 사용", key="so_use_riskoff",
                  help="또 메리츠의 매크로 리스크오프 신호(TIP·VWO·VEA 6M 동반하락 + VIXY)를 "
                       "추가 방어 트리거로 사용. 백테스트상 CAGR·MDD·샤프·Sortino 모두 개선.")
    filt_pass = bool(last['filter_pass'])
    riskoff_now = bool(last.get('riskoff', False))
    badge = (f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>✅ 통과 (공격 허용)</span>"
             if filt_pass else
             f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 미통과 (방어)</span>")
    ro_badge = (" &nbsp; <span style='font-size:12px; font-weight:800; color:#F59E0B; background:#F59E0B18; padding:3px 8px; border-radius:6px;'>⚠️ 리스크오프 발동 → 방어</span>"
                if (use_riskoff and riskoff_now) else "")
    st.markdown(f"<div style='margin-bottom:6px;'>{badge}{ro_badge} <b>필터: SPY 추세</b> "
                f"<span style='font-size:12px; color:#9CA3AF;'>(SPY 1+3+6+12개월 수익률 합 &gt; 0 이면 공격)</span></div>",
                unsafe_allow_html=True)
    sv = last.get('score_SPY_filter', np.nan)
    fdata = [{'자산': 'SPY',
              '모멘텀 점수(1+3+6+12M)': (f"{sv*100:+.2f}%" if pd.notna(sv) else 'N/A'),
              '조건': '>0', '충족?': ('✅' if (pd.notna(sv) and sv > 0) else '❌')}]
    st.dataframe(pd.DataFrame(fdata), hide_index=True, use_container_width=True, key="so_filter")

    # 리스크오프(cond1) 4개 구성요소 상세 — 켜져 있을 때만 표시
    if use_riskoff:
        base_neg = all((pd.notna(last.get(f'ro6_{t}')) and last.get(f'ro6_{t}') < 0) for t in C1_RISK_ASSETS)
        vixy6 = last.get('ro6_VIXY', np.nan)
        vixy_trig = pd.notna(vixy6) and (vixy6 < 0 or vixy6 >= VIXY_SPIKE)
        cond1_on = bool(last.get('riskoff', False))
        st.markdown(
            "<div style='font-weight:800; font-size:14px; margin:10px 0 4px 0;'>🛡️ 리스크오프 (cond1) 판정</div>"
            "<div style='font-size:11px; color:#9CA3AF; margin-bottom:4px;'>"
            "TIP·VWO·VEA 6M 수익률이 <b>모두 음수</b>이고, 그와 동시에 VIXY 6M이 "
            f"<b>음수이거나 +{VIXY_SPIKE*100:.0f}% 이상</b>이면 발동 → 방어</div>",
            unsafe_allow_html=True)
        ro_rows = []
        for t in C1_RISK_ASSETS:   # TIP, VWO, VEA
            v = last.get(f'ro6_{t}', np.nan)
            ro_rows.append({'자산': t, '6M 수익률': (f"{v*100:+.2f}%" if pd.notna(v) else 'N/A'),
                            '조건': '< 0 (하락)', '충족?': ('✅' if (pd.notna(v) and v < 0) else '❌')})
        ro_rows.append({'자산': 'VIXY',
                        '6M 수익률': (f"{vixy6*100:+.2f}%" if pd.notna(vixy6) else 'N/A'),
                        '조건': f'< 0 또는 ≥ +{VIXY_SPIKE*100:.0f}%',
                        '충족?': ('✅' if vixy_trig else '❌')})
        st.dataframe(pd.DataFrame(ro_rows), hide_index=True, use_container_width=True, key="so_ro")
        status = ("🛑 발동 → 방어 전환" if cond1_on else "✅ 미발동 (공격 허용)")
        color = '#EF4444' if cond1_on else '#10B981'
        detail = ("TIP·VWO·VEA 모두 하락 + VIXY 조건 동시 충족" if cond1_on
                  else ("TIP·VWO·VEA가 모두 하락은 아님" if not base_neg else "VIXY 조건 미충족"))
        st.markdown(f"<div style='margin:4px 0 2px 0;'><span style='font-weight:900; color:{color};'>{status}</span> "
                    f"<span style='font-size:12px; color:#9CA3AF;'>— {detail}</span></div>",
                    unsafe_allow_html=True)

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
    with t_col:
        st.markdown("### 📈 백테스트 성과")
    with s_col:
        cost_pct = st.slider("거래비용 %/교체", 0.0, 1.0, 0.25, 0.05, format="%.2f%%",
                             key="so_cost",
                             help="새로 매수하는 비중만큼 차감(턴오버). 벤치마크는 매수 후 보유로 비용 없음.")
    cost_rate = cost_pct / 100.0
    bt = run_backtest_so(prices, signals, cost=cost_rate)
    if bt.empty:
        st.warning("백테스트 데이터가 충분하지 않습니다. (LIT 상장 시점상 2011년 전후부터 시작)")
        return
    perf = compute_performance(bt)
    detail_df = build_so_detail(signals, bt)
    settings_dict = {
        '전략': '쏘 삼성',
        '회피 필터': 'SPY 1+3+6+12M 수익률 합 > 0 → 공격'
                    + (' · 리스크오프(cond1) ON' if use_riskoff else ' · 리스크오프 OFF'),
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '공격': ', '.join(SO_OFFENSE_ASSETS) + f' 중 모멘텀 상위 {SO_TOPK} (4M MA>0인 것만, 50:50)',
        '방어': 'GLD 50% · IEF 50% 고정',
        '벤치마크': ', '.join(BENCHMARKS),
    }
    render_backtest_section(bt, perf, cost_rate, key_prefix="so",
                            strat_color='#F59E0B', strat_name='쏘 삼성 전략',
                            detail_df=detail_df, settings_dict=settings_dict)


# ==========================================
# 또 ISA (탭 4) 렌더
# ==========================================
def build_ko_detail(signals, bt):
    """또 ISA 월별 상세 근거 DataFrame."""
    sig_by_month = {str(r['signal_month']): r for _, r in signals.iterrows()}
    rows = []
    for _, b in bt.iterrows():
        s = sig_by_month.get(b['signal_month'], {})
        td = s.get('tip_disp', np.nan)
        rows.append({
            '보유월': b['hold_month'],
            '국면': '🛡️방어' if b['defensive'] else '⚔️공격',
            '보유': b['hold'],
            'TIP 이격도': (f"{td*100:+.2f}%" if pd.notna(td) else 'N/A'),
            '필터': '통과' if s.get('filter_pass') else '이탈',
            '월수익률': f"{b['ret_strategy']*100:+.2f}%",
            '누적': f"{b['cum_strategy']:.2f}",
        })
    return pd.DataFrame(rows)


def render_ko():
    with st.spinner("국내 ETF 데이터 로딩 중..."):
        ko_prices = load_ko_prices()

    if ko_prices.empty:
        st.error(
            "📁 국내 ETF 데이터가 없습니다. `data/snowball_kr/monthly/` 폴더가 비어있거나 "
            "아직 수집되지 않았습니다. GitHub Actions에서 **Snowball KR Monthly Update** "
            "워크플로우를 한 번 실행하세요."
        )
        return

    need = KO_OFFENSE + KO_DEFENSE + [KO_FILTER_ASSET]
    missing = [t for t in need if t not in ko_prices.columns]
    if missing:
        miss_disp = ', '.join(f"{t}({KO_TICKER_NAMES.get(t, t)})" if t in KO_TICKER_NAMES else t
                              for t in missing)
        st.warning(f"⚠️ 누락된 종목: {miss_disp}. 해당 파일이 아직 없을 수 있습니다.")

    signals = compute_signals_ko(ko_prices)
    valid = signals.index[signals['holds'].notna()]
    if len(valid) == 0:
        st.error("유효한 신호월이 없습니다. (데이터 워밍업 부족 또는 파일 누락)")
        return
    lm = valid[-1]
    last = signals.loc[lm]
    defensive_now = bool(last['defensive'])
    holds = last['holds'] or []
    hold_set = set(holds)
    hold_disp = " · ".join(
        f"<span style='color:{ASSET_COLORS.get(t, '#E5E7EB')};'>{KO_TICKER_NAMES.get(t, t)}</span>" for t in holds)

    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:800; margin-bottom:8px;'>공격 · 방어 자산 현황 "
        f"<span style='font-size:12px; color:#9CA3AF; font-weight:500;'>(기준: {lm} 월말 · ISA/연금 매매용)</span></div>",
        unsafe_allow_html=True)
    _mode_badge(defensive_now, hold_disp)

    off_scores = last.get('offense_scores', {}) or {}
    def_scores = last.get('defense_scores', {}) or {}
    off_ranked = sorted(off_scores, key=off_scores.get, reverse=True)

    col_off, col_def = st.columns(2)
    with col_off:
        is_active = not defensive_now
        win_label = '+'.join(str(w) for w in KO_MOM_WINDOWS)
        label = f"⚔️ 공격 후보 ({win_label}M 모멘텀 점수 합)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>점수 상위 {KO_TOPK}종 중 "
                    f"<b>최근 {KO_ABSMOM_WIN}M MA 이격도 ≥ 0</b>인 것만 동일가중 매수 (음수면 제외, 다 음수면 방어)</div>",
                    unsafe_allow_html=True)
        oabs = last.get('offense_absmom', {}) or {}
        top_set = set(last.get('offense_top', []) or [])
        rows = []
        for code in off_ranked:
            v = off_scores[code]
            am = oabs.get(code, np.nan)
            in_top = code in top_set
            # 상위3 안인데 이격도<0라 빠진 경우 표시
            am_mark = ''
            if in_top and pd.notna(am):
                am_mark = ' ✅' if am >= 0 else ' ❌제외'
            rows.append({'티커': code, '종목명': KO_TICKER_NAMES.get(code, code),
                         '모멘텀 점수': (f"{v*100:+.1f}%" if pd.notna(v) else 'N/A'),
                         f'{KO_ABSMOM_WIN}M 이격도': ((f"{am*100:+.1f}%" if pd.notna(am) else 'N/A') + am_mark)})
        odf = pd.DataFrame(rows)
        def _off_style(row):
            if is_active and row['티커'] in hold_set:
                c = ASSET_COLORS.get(row['티커'], '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="ko_off")
    with col_def:
        is_active = defensive_now
        label = "🛡️ 방어 후보 (1개월 수익률)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>3종 중 {KO_DEF_WIN}M MA 이격도 상위 {KO_DEF_TOPK}종 동일가중(50:50)</div>",
                    unsafe_allow_html=True)
        def_ranked = sorted(def_scores, key=def_scores.get, reverse=True)
        rows = []
        for code in def_ranked:
            v = def_scores[code]
            rows.append({'티커': code, '종목명': KO_TICKER_NAMES.get(code, code),
                         f'{KO_DEF_WIN}M 이격도': (f"{v*100:+.1f}%" if pd.notna(v) else 'N/A')})
        ddf = pd.DataFrame(rows)
        def _def_style(row):
            if is_active and row['티커'] in hold_set:
                c = ASSET_COLORS.get(row['티커'], '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="ko_def")

    # 위험회피 필터 (TIP 10M MA 이격도)
    st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:16px 0 8px 0;'>위험회피 필터</div>",
                unsafe_allow_html=True)
    td = last.get('tip_disp', np.nan)
    filt_pass = bool(last['filter_pass'])
    badge = (f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>✅ 통과 (공격 허용)</span>"
             if filt_pass else
             f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 미통과 (방어 전환)</span>")
    st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>필터: TIP 추세</b> "
                f"<span style='font-size:12px; color:#9CA3AF;'>(미국 물가연동채 TIP의 {KO_FILTER_WIN}개월 이동평균 이격도 &gt; 0 이면 공격)</span></div>",
                unsafe_allow_html=True)
    fdata = [{'자산': f'{KO_FILTER_ASSET} (미국 물가연동채)',
              f'{KO_FILTER_WIN}M MA 이격도': (f"{td*100:+.2f}%" if pd.notna(td) else 'N/A'),
              '조건': '> 0', '충족?': ('✅' if filt_pass else '❌')}]
    st.dataframe(pd.DataFrame(fdata), hide_index=True, use_container_width=True, key="ko_filter")

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
    with t_col:
        st.markdown("### 📈 백테스트 성과")
    with s_col:
        cost_pct = st.slider("거래비용 %/교체", 0.0, 1.0, 0.25, 0.05, format="%.2f%%",
                             key="ko_cost",
                             help="새로 매수하는 비중만큼 차감(턴오버). 벤치마크는 매수 후 보유로 비용 없음.")
    cost_rate = cost_pct / 100.0
    bt = run_backtest_ko(ko_prices, signals, cost=cost_rate)
    if bt.empty:
        st.warning("백테스트 데이터가 충분하지 않습니다.")
        return
    perf = compute_performance(bt)

    # KOSPI200(102110) 벤치마크 비교 라인
    bench_code = KO_BENCHMARKS[0]
    if f'cum_{bench_code}' in bt.columns and bt[f'ret_{bench_code}'].notna().sum() > 0:
        bcum = bt[f'cum_{bench_code}']
        b_cum = bcum.iloc[-1]
        b_n = len(bt)
        b_cagr = b_cum ** (12.0 / b_n) - 1.0 if b_cum > 0 else -1.0
        b_peak = bcum.cummax().clip(lower=1.0)
        b_mdd = (bcum / b_peak - 1.0).min()
        st.caption(f"📊 참고 벤치마크 — {bench_code} {KO_TICKER_NAMES.get(bench_code,'')} "
                   f"매수후보유 ({bt['hold_month'].iloc[0]}~): 누적 {(b_cum-1)*100:,.0f}% · "
                   f"CAGR {b_cagr*100:.1f}% · MDD {b_mdd*100:.1f}%  "
                   f"→ 전략이 수익↑·낙폭↓")

    detail_df = build_ko_detail(signals, bt)
    off_list = ', '.join(f"{c}" for c in KO_OFFENSE)
    def_list = ', '.join(f"{c}" for c in KO_DEFENSE)
    settings_dict = {
        '전략': '또 ISA (국내 ETF)',
        '위험회피 필터': f'TIP {KO_FILTER_WIN}M MA 이격도 > 0 → 공격',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '공격': f'[{off_list}] 중 {"+".join(str(w) for w in KO_MOM_WINDOWS)}M 수익률 합 상위 {KO_TOPK}종 '
                f'(최근 {KO_ABSMOM_WIN}M 수익률 ≥ 0인 것만) 동일가중',
        '방어': f'[{def_list}] 중 {KO_DEF_WIN}M MA 이격도 상위 {KO_DEF_TOPK}종 동일가중(50:50)',
        '벤치마크': f"{bench_code}({KO_TICKER_NAMES.get(bench_code,'')})",
        '주의': '종목별 상장시점이 달라 초기 구간은 가용 종목만으로 순위(동적 유니버스). ISA/연금 매매용.',
    }
    render_backtest_section(bt, perf, cost_rate, key_prefix="ko",
                            strat_color='#0EA5E9', strat_name='또 ISA 전략',
                            detail_df=detail_df, settings_dict=settings_dict)


# ==========================================
# 또 연금 (탭 5) 렌더
# ==========================================
def build_pen_detail(signals, bt):
    """또 연금 월별 상세 근거."""
    sig_by_month = {str(r['signal_month']): r for _, r in signals.iterrows()}
    rows = []
    for _, b in bt.iterrows():
        s = sig_by_month.get(b['signal_month'], {})
        fn = s.get('filt_nasdaq', np.nan)
        fk = s.get('filt_kospi', np.nan)
        rows.append({
            '보유월': b['hold_month'],
            '국면': '🛡️방어' if b['defensive'] else '⚔️공격',
            '보유': b['hold'],
            '나스닥 6M이격도': (f"{fn*100:+.1f}%" if pd.notna(fn) else 'N/A'),
            'KOSPI 6M이격도': (f"{fk*100:+.1f}%" if pd.notna(fk) else 'N/A'),
            '월수익률': f"{b['ret_strategy']*100:+.2f}%",
            '누적': f"{b['cum_strategy']:.2f}",
        })
    return pd.DataFrame(rows)


def render_pension():
    with st.spinner("국내 ETF 데이터 로딩 중..."):
        pen_prices = load_pen_prices()

    if pen_prices.empty:
        st.error("📁 또 연금 데이터가 없습니다. `data/snowball_kr/monthly/`에 133690·305080·"
                 "261220·329200 등이 수집됐는지 확인하세요.")
        return
    missing = [t for t in (PEN_OFFENSE + PEN_DEFENSE) if t not in pen_prices.columns]
    if missing:
        st.warning(f"⚠️ 누락: {', '.join(f'{t}({PEN_TICKER_NAMES.get(t,t)})' for t in missing)}")

    signals = compute_signals_pension(pen_prices)
    valid = signals.index[signals['holds'].notna()]
    if len(valid) == 0:
        st.error("유효한 신호월이 없습니다.")
        return
    last = signals.loc[valid[-1]]
    defensive_now = bool(last['defensive'])
    holds = last['holds'] or []
    hold_set = set(holds)
    hold_disp = " · ".join(
        f"<span style='color:{ASSET_COLORS.get(t, '#E5E7EB')};'>{PEN_TICKER_NAMES.get(t, t)}</span>"
        for t in holds)

    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:800; margin-bottom:8px;'>공격 · 방어 자산 현황 "
        f"<span style='font-size:12px; color:#9CA3AF; font-weight:500;'>(기준: {valid[-1]} 월말 · 연금/ISA 매매용)</span></div>",
        unsafe_allow_html=True)
    _mode_badge(defensive_now, hold_disp)

    off_scores = last.get('offense_scores', {}) or {}
    def_scores = last.get('defense_scores', {}) or {}

    col_off, col_def = st.columns(2)
    with col_off:
        is_active = not defensive_now
        label = f"⚔️ 공격 후보 ({PEN_OFF_WIN}M 수익률 높은 1종)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>나스닥100 vs KOSPI200 중 {PEN_OFF_WIN}개월 수익률 우위 종목 100%</div>",
                    unsafe_allow_html=True)
        off_ranked = sorted(off_scores, key=off_scores.get, reverse=True)
        rows = [{'티커': c, '종목명': PEN_TICKER_NAMES.get(c, c),
                 f'{PEN_OFF_WIN}M 수익률': (f"{off_scores[c]*100:+.1f}%" if pd.notna(off_scores[c]) else 'N/A')}
                for c in off_ranked]
        odf = pd.DataFrame(rows)
        def _off_style(row):
            if is_active and row['티커'] in hold_set:
                c = ASSET_COLORS.get(row['티커'], '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="pen_off")
    with col_def:
        is_active = defensive_now
        label = f"🛡️ 방어 후보 ({PEN_DEF_WIN}M MA 이격도 1위)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>미국채·금·원유·리츠 중 {PEN_DEF_WIN}개월 MA 이격도 1위 종목 100%</div>",
                    unsafe_allow_html=True)
        def_ranked = sorted(def_scores, key=def_scores.get, reverse=True)
        rows = [{'티커': c, '종목명': PEN_TICKER_NAMES.get(c, c),
                 f'{PEN_DEF_WIN}M 이격도': (f"{def_scores[c]*100:+.1f}%" if pd.notna(def_scores[c]) else 'N/A')}
                for c in def_ranked]
        ddf = pd.DataFrame(rows)
        def _def_style(row):
            if is_active and row['티커'] in hold_set:
                c = ASSET_COLORS.get(row['티커'], '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="pen_def")

    # 위험회피 필터
    st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:16px 0 8px 0;'>위험회피 필터</div>",
                unsafe_allow_html=True)
    fn = last.get('filt_nasdaq', np.nan)
    fk = last.get('filt_kospi', np.nan)
    risk_off = bool(last.get('risk_off', False))
    badge = (f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 발동 (방어 전환)</span>"
             if risk_off else
             f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>✅ 통과 (공격 허용)</span>")
    st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>나스닥·KOSPI {PEN_FILTER_WIN}M MA 이격도</b> "
                f"<span style='font-size:12px; color:#9CA3AF;'>(둘 중 하나라도 음수면 방어 전환)</span></div>",
                unsafe_allow_html=True)
    fdata = [
        {'자산': f'{PEN_NASDAQ} 나스닥100', f'{PEN_FILTER_WIN}M MA 이격도': (f"{fn*100:+.2f}%" if pd.notna(fn) else 'N/A'),
         '조건': '≥ 0', '충족?': ('✅' if (pd.notna(fn) and fn >= 0) else '❌')},
        {'자산': f'{PEN_KOSPI} KOSPI200', f'{PEN_FILTER_WIN}M MA 이격도': (f"{fk*100:+.2f}%" if pd.notna(fk) else 'N/A'),
         '조건': '≥ 0', '충족?': ('✅' if (pd.notna(fk) and fk >= 0) else '❌')},
    ]
    st.dataframe(pd.DataFrame(fdata), hide_index=True, use_container_width=True, key="pen_filter")

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
    with t_col:
        st.markdown("### 📈 백테스트 성과")
    with s_col:
        cost_pct = st.slider("거래비용 %/교체", 0.0, 1.0, 0.25, 0.05, format="%.2f%%",
                             key="pen_cost", help="새로 매수하는 비중만큼 차감(턴오버).")
    cost_rate = cost_pct / 100.0
    bt = run_backtest_pension(pen_prices, signals, cost=cost_rate)
    if bt.empty:
        st.warning("백테스트 데이터가 충분하지 않습니다.")
        return
    perf = compute_performance(bt)

    # 벤치마크 (나스닥·코스피 매수후보유)
    bench_bits = []
    for bc in PEN_BENCHMARKS:
        col = f'cum_{bc}'
        if col in bt.columns and bt[f'ret_{bc}'].notna().sum() > 0:
            bcum = bt[col]
            b_cagr = bcum.iloc[-1] ** (12.0 / len(bt)) - 1.0 if bcum.iloc[-1] > 0 else -1.0
            b_mdd = (bcum / bcum.cummax().clip(lower=1.0) - 1.0).min()
            bench_bits.append(f"{PEN_TICKER_NAMES.get(bc, bc)} 매수후보유 CAGR {b_cagr*100:.1f}%·MDD {b_mdd*100:.1f}%")
    if bench_bits:
        st.caption("📊 참고 벤치마크 — " + " / ".join(bench_bits) + "  → 전략이 수익↑·낙폭↓")

    detail_df = build_pen_detail(signals, bt)
    settings_dict = {
        '전략': '또 연금 (국내 듀얼모멘텀)',
        '위험회피 필터': f'나스닥·KOSPI {PEN_FILTER_WIN}M MA 이격도 하나라도 < 0 → 방어',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '공격': f'{PEN_NASDAQ}(나스닥100) vs {PEN_KOSPI}(KOSPI200) 중 {PEN_OFF_WIN}M 수익률 높은 1종',
        '방어': f'[{", ".join(PEN_DEFENSE)}] 중 {PEN_DEF_WIN}M MA 이격도 1위 1종',
        '벤치마크': '나스닥100 · KOSPI200 매수후보유',
        '주의': '단일 종목 보유(집중형). 방어자산 상장시점이 달라 초기는 가용분만 선택. 연금/ISA 매매용.',
    }
    render_backtest_section(bt, perf, cost_rate, key_prefix="pen",
                            strat_color='#8B5CF6', strat_name='또 연금 전략',
                            detail_df=detail_df, settings_dict=settings_dict)


# ==========================================
# 쏘 연금 (탭 6) 렌더 — 나스닥 단일 공격 + cond1 위험회피
# ==========================================
def build_ssopen_detail(signals, bt):
    """쏘 연금 월별 상세 근거."""
    sig_by_month = {str(r['signal_month']): r for _, r in signals.iterrows()}
    rows = []
    for _, b in bt.iterrows():
        s = sig_by_month.get(b['signal_month'], {})
        vixy = s.get('VIXY_6m', np.nan)
        rows.append({
            '보유월': b['hold_month'],
            '국면': '🛡️방어' if b['defensive'] else '⚔️공격',
            '보유': b['hold'],
            'cond1': '🛑발동' if s.get('risk_off') else '✅통과',
            'VIXY 6M': (f"{vixy*100:+.1f}%" if pd.notna(vixy) else 'N/A'),
            '월수익률': f"{b['ret_strategy']*100:+.2f}%",
            '누적': f"{b['cum_strategy']:.2f}",
        })
    return pd.DataFrame(rows)


def render_ssopen():
    with st.spinner("국내 ETF 데이터 로딩 중..."):
        ss_prices = load_ssopen_prices()
        us_prices = load_monthly_prices()  # cond1 신호자산(TIP/VWO/VEA/VIXY)

    if ss_prices.empty:
        st.error("📁 쏘 연금 데이터가 없습니다. `data/snowball_kr/monthly/`에 133690·305080·"
                 "148070·411060·469830이 수집됐는지 확인하세요.")
        return
    missing = [t for t in ([SSOPEN_NASDAQ] + SSOPEN_DEFENSE) if t not in ss_prices.columns]
    if missing:
        st.warning(f"⚠️ 누락: {', '.join(f'{t}({SSOPEN_TICKER_NAMES.get(t, t)})' for t in missing)}")

    signals = compute_signals_ssopen(ss_prices, us_prices)
    valid = signals.index[signals['holds'].notna()]
    if len(valid) == 0:
        st.error("유효한 신호월이 없습니다. (cond1 신호자산 TIP/VWO/VEA/VIXY가 로드됐는지 확인)")
        return
    last = signals.loc[valid[-1]]
    defensive_now = bool(last['defensive'])
    holds = last['holds'] or []
    hold_set = set(holds)
    hold_disp = " · ".join(
        f"<span style='color:{ASSET_COLORS.get(t, '#E5E7EB')};'>{SSOPEN_TICKER_NAMES.get(t, t)}</span>"
        for t in holds)

    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:800; margin-bottom:8px;'>공격 · 방어 자산 현황 "
        f"<span style='font-size:12px; color:#9CA3AF; font-weight:500;'>(기준: {valid[-1]} 월말 · 연금/ISA 매매용)</span></div>",
        unsafe_allow_html=True)
    _mode_badge(defensive_now, hold_disp)

    def_scores = last.get('defense_scores', {}) or {}

    col_off, col_def = st.columns(2)
    with col_off:
        is_active = not defensive_now
        label = "⚔️ 공격 (나스닥100 100%)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>cond1 미발동 시 미국나스닥100 단일 100% 보유</div>",
                    unsafe_allow_html=True)
        odf = pd.DataFrame([{'티커': SSOPEN_NASDAQ, '종목명': SSOPEN_TICKER_NAMES[SSOPEN_NASDAQ], '비중': '100%'}])

        def _off_style(row):
            if is_active:
                c = ASSET_COLORS.get(row['티커'], '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="ssopen_off")
    with col_def:
        is_active = defensive_now
        label = "🛡️ 방어 후보 (1+3+6+12M 수익률 합 1위)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>미국채10년·국고채10년·금현물·SOL초단기채 중 1+3+6+12M 수익률 합 1위 종목 100%</div>",
                    unsafe_allow_html=True)
        def_ranked = sorted(def_scores, key=def_scores.get, reverse=True)
        rows = [{'티커': c, '종목명': SSOPEN_TICKER_NAMES.get(c, c),
                 '1+3+6+12M 합': (f"{def_scores[c]*100:+.1f}%" if pd.notna(def_scores[c]) else 'N/A')}
                for c in def_ranked]
        ddf = pd.DataFrame(rows)

        def _def_style(row):
            if is_active and row['티커'] in hold_set:
                c = ASSET_COLORS.get(row['티커'], '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="ssopen_def")

    # 위험회피 필터 (cond1)
    st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:16px 0 8px 0;'>위험회피 필터 (cond1)</div>",
                unsafe_allow_html=True)
    risk_off = bool(last.get('risk_off', False))
    badge = (f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 발동 (방어 전환)</span>"
             if risk_off else
             f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>✅ 통과 (공격 허용)</span>")
    st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>또 메리츠와 동일 신호</b> "
                f"<span style='font-size:12px; color:#9CA3AF;'>(TIP·VWO·VEA 6M 모두 음수 <b>AND</b> (VIXY 6M 음수 또는 ≥ +{int(VIXY_SPIKE*100)}%) → 방어)</span></div>",
                unsafe_allow_html=True)
    tip6 = last.get('TIP_6m', np.nan)
    vwo6 = last.get('VWO_6m', np.nan)
    vea6 = last.get('VEA_6m', np.nan)
    vixy6 = last.get('VIXY_6m', np.nan)
    fdata = [
        {'자산': 'TIP', '6M 수익률': (f"{tip6*100:+.2f}%" if pd.notna(tip6) else 'N/A'),
         '발동조건': '< 0', '충족?': ('✅' if (pd.notna(tip6) and tip6 < 0) else '❌')},
        {'자산': 'VWO', '6M 수익률': (f"{vwo6*100:+.2f}%" if pd.notna(vwo6) else 'N/A'),
         '발동조건': '< 0', '충족?': ('✅' if (pd.notna(vwo6) and vwo6 < 0) else '❌')},
        {'자산': 'VEA', '6M 수익률': (f"{vea6*100:+.2f}%" if pd.notna(vea6) else 'N/A'),
         '발동조건': '< 0', '충족?': ('✅' if (pd.notna(vea6) and vea6 < 0) else '❌')},
        {'자산': 'VIXY', '6M 수익률': (f"{vixy6*100:+.2f}%" if pd.notna(vixy6) else 'N/A'),
         '발동조건': f'< 0 또는 ≥ +{int(VIXY_SPIKE*100)}%',
         '충족?': ('✅' if (pd.notna(vixy6) and (vixy6 < 0 or vixy6 >= VIXY_SPIKE)) else '❌')},
    ]
    st.dataframe(pd.DataFrame(fdata), hide_index=True, use_container_width=True, key="ssopen_filter")

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
    with t_col:
        st.markdown("### 📈 백테스트 성과")
    with s_col:
        cost_pct = st.slider("거래비용 %/교체", 0.0, 1.0, 0.25, 0.05, format="%.2f%%",
                             key="ssopen_cost", help="새로 매수하는 비중만큼 차감(턴오버).")
    cost_rate = cost_pct / 100.0
    bt = run_backtest_ssopen(ss_prices, signals, cost=cost_rate)
    if bt.empty:
        st.warning("백테스트 데이터가 충분하지 않습니다.")
        return
    perf = compute_performance(bt)

    # 벤치마크 (나스닥100 매수후보유)
    bench_bits = []
    for bc in SSOPEN_BENCHMARKS:
        col = f'cum_{bc}'
        if col in bt.columns and bt[f'ret_{bc}'].notna().sum() > 0:
            bcum = bt[col]
            b_cagr = bcum.iloc[-1] ** (12.0 / len(bt)) - 1.0 if bcum.iloc[-1] > 0 else -1.0
            b_mdd = (bcum / bcum.cummax().clip(lower=1.0) - 1.0).min()
            bench_bits.append(f"{SSOPEN_TICKER_NAMES.get(bc, bc)} 매수후보유 CAGR {b_cagr*100:.1f}%·MDD {b_mdd*100:.1f}%")
    if bench_bits:
        st.caption("📊 참고 벤치마크 — " + " / ".join(bench_bits) + "  → 전략이 수익↑·낙폭↓")

    detail_df = build_ssopen_detail(signals, bt)
    settings_dict = {
        '전략': '쏘 연금 (국내 나스닥 단일 + cond1)',
        '위험회피 필터': f'cond1: TIP·VWO·VEA 6M 음수 AND (VIXY 6M 음수 또는 ≥ +{int(VIXY_SPIKE*100)}%) → 방어',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '공격': f'{SSOPEN_NASDAQ}(미국나스닥100) 단일 100%',
        '방어': f'[{", ".join(SSOPEN_DEFENSE)}] 중 1+3+6+12M 수익률 합 1위 1종',
        '벤치마크': '나스닥100 매수후보유',
        '주의': '단일 종목 보유(집중형). 방어자산 상장시점이 달라 초기는 가용분만 선택. 연금/ISA 매매용.',
    }
    render_backtest_section(bt, perf, cost_rate, key_prefix="ssopen",
                            strat_color='#EC4899', strat_name='쏘 연금 전략',
                            detail_df=detail_df, settings_dict=settings_dict)


# ==========================================
# 맘 비과세 (탭 7) 렌더 — 글로벌 듀얼모멘텀 + cond1
# ==========================================
def build_mamtax_detail(signals, bt):
    """맘 비과세 월별 상세 근거."""
    sig_by_month = {str(r['signal_month']): r for _, r in signals.iterrows()}
    rows = []
    for _, b in bt.iterrows():
        s = sig_by_month.get(b['signal_month'], {})
        vixy = s.get('VIXY_6m', np.nan)
        rows.append({
            '보유월': b['hold_month'],
            '국면': '🛡️방어' if b['defensive'] else '⚔️공격',
            '보유(실운용)': b['hold'],
            'cond1': '🛑발동' if s.get('risk_off') else '✅통과',
            'VIXY 6M': (f"{vixy*100:+.1f}%" if pd.notna(vixy) else 'N/A'),
            '월수익률': f"{b['ret_strategy']*100:+.2f}%",
            '누적': f"{b['cum_strategy']:.2f}",
        })
    return pd.DataFrame(rows)


def render_mamtax():
    with st.spinner("국내 ETF 데이터 로딩 중..."):
        mp = load_mamtax_prices()
        us_prices = load_monthly_prices()  # cond1 신호자산(TIP/VWO/VEA/VIXY)

    if mp.empty:
        st.error("📁 맘 비과세 데이터가 없습니다. `data/snowball_kr/monthly/`에 공격 10종·방어 6종이 "
                 "수집됐는지 확인하세요.")
        return
    missing = [t for t in (MAMTAX_OFFENSE + MAMTAX_DEFENSE) if t not in mp.columns]
    if missing:
        st.warning(f"⚠️ 누락: {', '.join(f'{t}({MAMTAX_TICKER_NAMES.get(t, t)})' for t in missing)}")

    signals = compute_signals_mamtax(mp, us_prices)
    valid = signals.index[signals['holds'].notna()]
    if len(valid) == 0:
        st.error("유효한 신호월이 없습니다. (cond1 자산 TIP/VWO/VEA/VIXY 로드 및 공격 12M 4종 확인)")
        return
    last = signals.loc[valid[-1]]
    defensive_now = bool(last['defensive'])
    holds = last['holds'] or {}
    hold_set = set(holds)
    held_live = {mamtax_live_ticker(t) for t in hold_set}
    hold_disp = " · ".join(
        f"<span style='color:{ASSET_COLORS.get(mamtax_live_ticker(t), '#E5E7EB')};'>"
        f"{mamtax_live_name(t)} {holds[t]*100:.0f}%</span>"
        for t in holds)

    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:800; margin-bottom:8px;'>공격 · 방어 자산 현황 "
        f"<span style='font-size:12px; color:#9CA3AF; font-weight:500;'>(기준: {valid[-1]} 월말 · 비과세계좌 매매용)</span></div>",
        unsafe_allow_html=True)
    _mode_badge(defensive_now, hold_disp)
    st.caption("ℹ️ 신호·백테스트는 장수 종목(133690·102110)으로 계산하고, 표시·매매는 실운용 종목"
               "(379810 KODEX 미국나스닥100·278530 KODEX 200TR)으로 안내합니다. CSI300은 192090 동일.")

    off_scores = last.get('off_scores', {}) or {}
    def_scores = last.get('def_scores', {}) or {}

    col_off, col_def = st.columns(2)
    with col_off:
        is_active = not defensive_now
        label = "⚔️ 공격 (12M 수익률 상위4·양수 균등)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>10종 중 12M 수익률 상위 4위 → "
                    "12M 음수 제외 → 남은 승자 균등(듀얼모멘텀)</div>", unsafe_allow_html=True)
        ranked = sorted(off_scores, key=off_scores.get, reverse=True)
        rows = []
        for rk, t in enumerate(ranked, 1):
            lt = mamtax_live_ticker(t)
            rows.append({'순위': rk, '실운용': lt, '종목명': mamtax_live_name(t),
                         '12M수익률': f"{off_scores[t]*100:+.1f}%",
                         '보유': (f"{holds[t]*100:.0f}%" if t in hold_set else '—')})
        odf = pd.DataFrame(rows)

        def _off_style(row):
            if is_active and row['실운용'] in held_live:
                c = ASSET_COLORS.get(row['실운용'], '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="mamtax_off")
    with col_def:
        is_active = defensive_now
        label = "🛡️ 방어 후보 (3M MA이격도 상위2)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>원유인버스·금현물·은선물·"
                    "미국SOFR·미국채10년·국고채10년 중 3M MA이격도 상위 2종, 각 50% (cond1 발동 시)</div>",
                    unsafe_allow_html=True)
        def_ranked = sorted(def_scores, key=def_scores.get, reverse=True)
        rows = [{'티커': c, '종목명': MAMTAX_TICKER_NAMES.get(c, c),
                 '3M MA이격도': (f"{def_scores[c]*100:+.1f}%" if pd.notna(def_scores[c]) else 'N/A'),
                 '보유': (f"{holds[c]*100:.0f}%" if c in hold_set else '—')}
                for c in def_ranked]
        ddf = pd.DataFrame(rows)

        def _def_style(row):
            if is_active and row['티커'] in hold_set:
                c = ASSET_COLORS.get(row['티커'], '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="mamtax_def")

    # 위험회피 필터 (cond1)
    st.markdown("<div style='font-size:1.5rem; font-weight:800; margin:16px 0 8px 0;'>위험회피 필터 (cond1)</div>",
                unsafe_allow_html=True)
    risk_off = bool(last.get('risk_off', False))
    badge = (f"<span style='font-size:13px; font-weight:900; color:#EF4444; background:#EF444418; padding:3px 10px; border-radius:6px;'>🛑 발동 (방어 전환)</span>"
             if risk_off else
             f"<span style='font-size:13px; font-weight:900; color:#10B981; background:#10B98118; padding:3px 10px; border-radius:6px;'>✅ 통과 (공격 허용)</span>")
    st.markdown(f"<div style='margin-bottom:6px;'>{badge} <b>쏘 연금·또 메리츠와 동일 신호</b> "
                f"<span style='font-size:12px; color:#9CA3AF;'>(TIP·VWO·VEA 6M 모두 음수 <b>AND</b> (VIXY 6M 음수 또는 ≥ +{int(VIXY_SPIKE*100)}%) → 방어)</span></div>",
                unsafe_allow_html=True)
    tip6 = last.get('TIP_6m', np.nan)
    vwo6 = last.get('VWO_6m', np.nan)
    vea6 = last.get('VEA_6m', np.nan)
    vixy6 = last.get('VIXY_6m', np.nan)
    fdata = [
        {'자산': 'TIP', '6M 수익률': (f"{tip6*100:+.2f}%" if pd.notna(tip6) else 'N/A'),
         '발동조건': '< 0', '충족?': ('✅' if (pd.notna(tip6) and tip6 < 0) else '❌')},
        {'자산': 'VWO', '6M 수익률': (f"{vwo6*100:+.2f}%" if pd.notna(vwo6) else 'N/A'),
         '발동조건': '< 0', '충족?': ('✅' if (pd.notna(vwo6) and vwo6 < 0) else '❌')},
        {'자산': 'VEA', '6M 수익률': (f"{vea6*100:+.2f}%" if pd.notna(vea6) else 'N/A'),
         '발동조건': '< 0', '충족?': ('✅' if (pd.notna(vea6) and vea6 < 0) else '❌')},
        {'자산': 'VIXY', '6M 수익률': (f"{vixy6*100:+.2f}%" if pd.notna(vixy6) else 'N/A'),
         '발동조건': f'< 0 또는 ≥ +{int(VIXY_SPIKE*100)}%',
         '충족?': ('✅' if (pd.notna(vixy6) and (vixy6 < 0 or vixy6 >= VIXY_SPIKE)) else '❌')},
    ]
    st.dataframe(pd.DataFrame(fdata), hide_index=True, use_container_width=True, key="mamtax_filter")

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
    with t_col:
        st.markdown("### 📈 백테스트 성과")
    with s_col:
        cost_pct = st.slider("거래비용 %/교체", 0.0, 1.0, 0.25, 0.05, format="%.2f%%",
                             key="mamtax_cost", help="새로 매수하는 비중만큼 차감(턴오버).")
    cost_rate = cost_pct / 100.0
    bt = run_backtest_mamtax(mp, signals, cost=cost_rate)
    if bt.empty:
        st.warning("백테스트 데이터가 충분하지 않습니다.")
        return
    perf = compute_performance(bt)

    bench_bits = []
    for bc in MAMTAX_BENCHMARKS:
        col = f'cum_{bc}'
        if col in bt.columns and bt[f'ret_{bc}'].notna().sum() > 0:
            bcum = bt[col]
            b_cagr = bcum.iloc[-1] ** (12.0 / len(bt)) - 1.0 if bcum.iloc[-1] > 0 else -1.0
            b_mdd = (bcum / bcum.cummax().clip(lower=1.0) - 1.0).min()
            bench_bits.append(f"{mamtax_live_name(bc)} 매수후보유 CAGR {b_cagr*100:.1f}%·MDD {b_mdd*100:.1f}%")
    if bench_bits:
        st.caption("📊 참고 벤치마크 — " + " / ".join(bench_bits) + "  → 전략이 수익↑·낙폭↓")

    detail_df = build_mamtax_detail(signals, bt)
    settings_dict = {
        '전략': '맘 비과세 (글로벌 듀얼모멘텀 + cond1)',
        '공격': '10종 중 12M 수익률 상위4 → 12M 음수 제외 → 승자 균등(듀얼모멘텀)',
        '방어': '6종 중 3M MA이격도 상위2, 각 50% (cond1 발동 시)',
        '위험회피 필터': f'cond1: TIP·VWO·VEA 6M 음수 AND (VIXY 6M 음수 또는 ≥ +{int(VIXY_SPIKE*100)}%)',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '벤치마크': '나스닥100·KOSPI200 매수후보유',
        '티커': '신호·백테스트=133690·102110·192090(장수), 실운용=379810·278530·192090',
        '주의': '공격 자산 상장시점이 달라 초기는 부분 유니버스(4→10종). 비과세계좌 매매용.',
    }
    render_backtest_section(bt, perf, cost_rate, key_prefix="mamtax",
                            strat_color='#F97316', strat_name='맘 비과세 전략',
                            detail_df=detail_df, settings_dict=settings_dict)


# ==========================================
# 탭 배치
# ==========================================
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["🇺🇸 또 메리츠", "🇺🇸 맘 삼성", "🇺🇸 쏘 삼성", "🇰🇷 또 ISA", "🇰🇷 또 연금", "🇰🇷 쏘 연금", "🇰🇷 맘 비과세"])
with tab1:
    render_meritz()
with tab2:
    render_samsung()
with tab3:
    render_so()
with tab4:
    render_ko()
with tab5:
    render_pension()
with tab6:
    render_ssopen()
with tab7:
    render_mamtax()
