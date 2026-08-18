"""
6_❄️_스노우볼_포트.py
─────────────────────
동적 자산배분 전략 페이지 (탭 구성).

탭 7개: 또 메리츠 · 맘·쏘 삼성 · 또 ISA · 또 연금 · 쏘 연금 · 맘 비과세 · 통합 포트.
- 탭 1 "또 메리츠":  기존 스노우볼 전략 (조건1 모멘텀 + 조건2 밸류에이션).
- 탭 2 "맘·쏘 삼성": 모멘텀 상위 2종 동일가중 + 또 메리츠 리스크오프 동반 방어.
    · 삼성증권 계좌를 하나로 합쳐 운용한다 (레버리지 '맘 삼성'은 2026-08 폐지)

각 탭 구성은 동일: 공격/방어 현황 → 신호/필터 → 백테스트 성과 + 자산곡선 + 월별 로그.
새 탭을 추가하려면 render_* 함수를 만들어 아래 st.tabs에 연결하면 된다.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import re

from utils.snowball import (
    load_monthly_prices, load_dividend_yield,
    # 또 메리츠
    compute_signals, run_backtest, compute_performance, rule_active_note,
    SIGNAL_ASSETS, OFFENSE_ASSETS, DEFENSE_ASSETS, BENCHMARKS, VIXY_SPIKE,
    # 맘·쏘 삼성
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
    MAMTAX_OFFENSE, MAMTAX_DEFENSE, MAMTAX_TICKER_NAMES, MAMTAX_BENCHMARKS, MAMTAX_TOP_OFF,
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
st.markdown('''<style>
[data-testid="stPageLink-NavLink"] { padding:0 !important; margin:4px 0 20px 0 !important; }
[data-testid="stPageLink-NavLink"] p { font-size:2.2rem !important; font-weight:800 !important; line-height:1.2 !important; margin:0 !important; word-break:keep-all; }
[data-testid="stPageLink-NavLink"]:hover p { color:#93C5FD !important; }
</style>''', unsafe_allow_html=True)
st.page_link("app.py", label="❄️ 스노우볼 포트")


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
# 네이버 차트 링크 헬퍼
# ==========================================
# 미국 ETF 네이버 해외주식 거래소 접미사 (기본 'O'=나스닥). NYSE 등 안 열리면 여기만 수정.
NAVER_US_EXCH = {}


def naver_kr_url(code):
    return f"https://m.stock.naver.com/domestic/stock/{code}/total"


def naver_us_url(ticker):
    return f"https://m.stock.naver.com/worldstock/stock/{ticker}.{NAVER_US_EXCH.get(ticker, 'O')}/total"


def naver_code(url):
    """네이버 URL에서 코드/티커 추출 (스타일러 매칭용). URL이 아니면 원본 반환."""
    if not isinstance(url, str):
        return url
    m = re.search(r'/stock/([A-Za-z0-9]+)[./]', url)
    return m.group(1) if m else url


def naver_linkcol(df, col, us=False):
    """df[col]의 코드/티커를 네이버 URL로 바꾸고, 그 컬럼용 LinkColumn 설정을 반환."""
    df[col] = df[col].map(naver_us_url if us else naver_kr_url)
    disp = r'stock/([A-Za-z0-9]+)\.' if us else r'stock/([A-Za-z0-9]+)/'
    return {col: st.column_config.LinkColumn(col, display_text=disp)}


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
    df['자산'] = df['자산'].map(naver_us_url)   # 네이버 차트 링크용 URL화

    def _row_style(row):
        n = len(row)
        _code = naver_code(row['자산'])
        if active and _code in selected_set:
            c = ASSET_COLORS.get(_code, '#6B7280')
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


def build_meritz_detail_excel(signals, bt, prices):
    """엑셀 전용 상세표: build_meritz_detail + '방어가 아니었다면?' 반사실 컬럼.

    방어월마다 '공격이었다면 무엇을(TQQQ/USD) 보유하고 그 달 수익률이 얼마였을지'와,
    실제 방어 수익률과의 차이(방어−공격)를 덧붙인다. 공격월은 '-'.
    """
    base = build_meritz_detail(signals, bt)
    cf_hold, cf_ret, cf_diff = [], [], []
    for _, r in bt.iterrows():
        if not r['defensive']:
            cf_hold.append('-'); cf_ret.append(np.nan); cf_diff.append(np.nan)
            continue
        m = pd.Period(r['signal_month'], 'M'); nm = pd.Period(r['hold_month'], 'M')
        s = signals.loc[m]
        tqqq_v = s.get('ret12_TQQQ', np.nan); usd_v = s.get('ret12_USD', np.nan)
        pick = 'TQQQ' if (pd.notna(tqqq_v) and (pd.isna(usd_v) or tqqq_v >= usd_v)) else 'USD'
        cr = np.nan
        try:
            p0 = prices.loc[m, pick]; p1 = prices.loc[nm, pick]
            if pd.notna(p0) and pd.notna(p1) and p0 != 0:
                cr = p1 / p0 - 1.0
        except Exception:
            cr = np.nan
        cf_hold.append(pick)
        cf_ret.append(round(cr*100, 2) if pd.notna(cr) else np.nan)
        cf_diff.append(round((cr - r['ret_strategy'])*100, 2) if pd.notna(cr) else np.nan)
    base['방어대신_공격보유'] = cf_hold
    base['공격시_수익률(%)'] = cf_ret
    base['공격−방어_차이(%)'] = cf_diff   # +면 공격이 나았음(방어가 그만큼 손해), −면 방어가 이득(손실 회피)
    return base


# ──────────────────────────────────────────────────────────
# 방어월 반사실: '공격이었다면 무엇을·수익률' — 전 전략 공용 (엑셀 전용)
# ──────────────────────────────────────────────────────────
def _cf_so(s):
    scores = {t: s.get(f'score_{t}') for t in SO_OFFENSE_ASSETS if pd.notna(s.get(f'score_{t}'))}
    if not scores:
        return {}
    top = sorted(scores, key=scores.get, reverse=True)[:SO_TOPK]
    picks = [t for t in top if pd.notna(s.get(f'abs_{t}')) and s.get(f'abs_{t}') > 0]
    return {t: 1.0/len(picks) for t in picks} if picks else {}


def _cf_ko(s):
    ovalid = s.get('offense_scores') or {}
    oabs = s.get('offense_absmom') or {}
    if not ovalid:
        return {}
    top = sorted(ovalid, key=ovalid.get, reverse=True)[:KO_TOPK]
    picks = [t for t in top if oabs.get(t, -1) >= 0]
    return {t: 1.0/len(picks) for t in picks} if picks else {}


def _cf_pension(s):
    ovalid = s.get('offense_scores') or {}
    return {max(ovalid, key=ovalid.get): 1.0} if ovalid else {}


def _cf_ssopen(s):
    return {SSOPEN_NASDAQ: 1.0}


def _cf_mamtax(s):
    offv = s.get('off_scores') or {}
    if not offv:
        return {}
    ranked = sorted(offv, key=offv.get, reverse=True)[:MAMTAX_TOP_OFF]
    keep = [t for t in ranked if offv[t] >= 0]
    return {t: 1.0/len(keep) for t in keep} if keep else {}


def _build_cf_excel(base_df, signals, bt, prices, cf_fn, name_fn):
    """엑셀 전용: 방어월마다 '공격이었다면 보유(비중)·그 수익률·공격−방어 차이' 3열 추가.

    각 전략 signals에 저장된 점수로 '공격이었다면의 보유'를 재구성하고,
    해당 월→다음 달 수익률을 그 전략의 prices에서 계산한다. 공격월은 '-'.
    """
    sig_by = {str(idx): row for idx, row in signals.iterrows()}
    cf_hold, cf_ret, cf_diff = [], [], []
    for _, r in bt.iterrows():
        if not r['defensive']:
            cf_hold.append('-'); cf_ret.append(np.nan); cf_diff.append(np.nan)
            continue
        s = sig_by.get(str(r['signal_month']))
        cfo = cf_fn(s) if s is not None else {}
        if not cfo:
            cf_hold.append('공격후보없음'); cf_ret.append(np.nan); cf_diff.append(np.nan)
            continue
        m = pd.Period(r['signal_month'], 'M'); nm = pd.Period(r['hold_month'], 'M')
        cr = 0.0; ok = True
        for t, w in cfo.items():
            try:
                p0 = prices.loc[m, t]; p1 = prices.loc[nm, t]
            except Exception:
                ok = False; break
            if pd.isna(p0) or pd.isna(p1) or p0 == 0:
                ok = False; break
            cr += w * (p1 / p0 - 1.0)
        if not ok:
            cf_hold.append('데이터부족'); cf_ret.append(np.nan); cf_diff.append(np.nan)
            continue
        cf_hold.append(', '.join(f"{name_fn(t)} {w*100:.0f}%" for t, w in cfo.items()))
        cf_ret.append(round(cr*100, 2))
        cf_diff.append(round((cr - r['ret_strategy'])*100, 2))
    out = base_df.copy()
    out['방어대신_공격보유'] = cf_hold
    out['공격시_수익률(%)'] = cf_ret
    out['공격−방어_차이(%)'] = cf_diff
    return out


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


def render_bt_title(col, rule_active):
    """'📈 백테스트 성과' 제목 + 가동기간 주석을 같은 줄에 렌더.

    bt가 있어야 개월 수를 알 수 있으므로, 호출부는 컬럼을 먼저 만들어 두고
    백테스트를 돌린 뒤 이 함수로 제목을 채운다(Streamlit 컬럼은 나중에 써도 된다).
    """
    with col:
        note = ''
        if rule_active:
            _, n_active, n_total = rule_active
            note = (f" <span style='font-size:12px; font-weight:500; color:#9CA3AF;'>"
                    f"(실제가동 {n_active}개월 / 표시 {n_total}개월)</span>")
        st.markdown(f"### 📈 백테스트 성과{note}", unsafe_allow_html=True)


def render_backtest_section(bt, perf, cost_rate, key_prefix, strat_color, strat_name,
                           detail_df, settings_dict, excel_detail_df=None,
                           rule_active=None):
    """백테스트 카드 + 자산곡선 + 월별 로그 (탭 공용).

    rule_active: snowball.rule_active_note() 반환값 (note, n_active, n_total) 또는 None.
                 후보 자산 상장이 늦어 앞 구간이 '더 작은 유니버스'였던 전략에만 붙는다.
    """
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
        _xl_detail = detail_df if excel_detail_df is None else excel_detail_df
        xls = build_report_excel(settings_dict, stats_df, _xl_detail, df_res, cum_df, mdd_df, strat_name)
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
                     hide_index=True, use_container_width=True, key="meritz_off",
                     column_config={'자산': st.column_config.LinkColumn('자산', display_text=r'stock/([A-Za-z0-9]+)\.')})
    with col_def:
        is_active = defensive_now
        label = "🛡️ 방어 자산 (12개월 MA 이격도)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        rows = [{'자산': t, '이격도': last.get(f'disp12_{t}', np.nan)} for t in DEFENSE_ASSETS]
        sel = {selected_hold} if is_active else set()
        st.dataframe(_style_asset_table(rows, is_active, sel, '이격도'),
                     hide_index=True, use_container_width=True, key="meritz_def",
                     column_config={'자산': st.column_config.LinkColumn('자산', display_text=r'stock/([A-Za-z0-9]+)\.')})

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
                    f"<span style='font-size:12px; color:#9CA3AF;'>(배당 5Y 백분위 ≤ 10% → 방어 · 단 1등=최고가는 공격)</span></div>",
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
                is_rank1 = pd.notna(div_rank) and int(div_rank) == 1
                cond2_trig = bool(div_pct <= 10) and not is_rank1   # 실제 방어 발동(1등 제외)
                if is_rank1:
                    delta = f"{div_pct:.1f}% · 1등(최고가) → 공격 전환"
                elif cond2_trig:
                    delta = f"{div_pct:.1f}% → 10% 이하 방어"
                else:
                    delta = f"{div_pct:.1f}% → 안전 구간"
                st.metric("5Y 밸류 순위 (1등=최고가→공격)", rank_str, delta=delta,
                          delta_color="inverse" if cond2_trig else "off")
            with m2:
                if pd.notna(div_val):
                    if pd.notna(div_thr):
                        cmp = f"{div_val:.2f}% {'≤' if div_pct <= 10 else '>'} 기준점 {div_thr:.2f}%"
                        if is_rank1:
                            cmp += " · 1등→공격"
                        st.metric("현재 배당수익률", f"{div_val:.2f}%", delta=cmp,
                                  delta_color="inverse" if cond2_trig else "off")
                    else:
                        st.metric("현재 배당수익률", f"{div_val:.2f}%")
        else:
            st.info("배당 데이터 부족 (60개월 워밍업 또는 파일 없음)")

    # 배당수익률 출처 (밸류에이션 아래 · 구분선 위, 우측 정렬)
    st.markdown(
        "<div style='text-align:right; font-size:11px; color:#9CA3AF; margin:2px 0 0 0;'>"
        "배당수익률 출처: "
        "<a href='https://www.multpl.com/s-p-500-dividend-yield' target='_blank'>multpl.com</a> · "
        "<a href='https://dqydj.com/sp-500-dividend-yield/' target='_blank'>dqydj.com</a></div>",
        unsafe_allow_html=True)

    # 백테스트
    st.markdown("---")
    t_col, s_col = st.columns([2.2, 1])
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
    rule_act = rule_active_note(bt, prices,
                                SIGNAL_ASSETS + OFFENSE_ASSETS + DEFENSE_ASSETS)
    settings_dict = {
        '전략': '또 메리츠',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '규칙 실제 가동': f"{rule_act[1]}개월" if rule_act else "전 기간 (후보 전종목 상장 완료 상태로 시작)",
        '공격 자산': ', '.join(OFFENSE_ASSETS),
        '방어 자산': ', '.join(DEFENSE_ASSETS),
        '벤치마크': ', '.join(BENCHMARKS),
    }
    render_bt_title(t_col, rule_act)
    render_backtest_section(bt, perf, cost_rate, key_prefix="meritz",
                            strat_color='#10B981', strat_name='또 메리츠 전략',
                            detail_df=detail_df, settings_dict=settings_dict,
                            excel_detail_df=build_meritz_detail_excel(signals, bt, prices),
                            rule_active=rule_act)


# ==========================================
# [폐지] 맘 삼성 (레버리지 모멘텀) — 2026-08 운용 중단
# ==========================================
# 탭에서 내렸고 통합 포트 후보에서도 뺐다.
# 화면 코드(render_samsung 등)는 2026-08-14에 제거했다 — 되돌리려면 git 히스토리에서
# 이 커밋 직전 판을 꺼내면 된다. 이 메모는 같은 발상을 다시 시도하지 않도록 남긴다.
#
# 폐지 사유 — 레버리지 ETF를 보유 자산으로 쓰는 발상 자체가 문제였다.
#   · 같은 기간 같은 CAGR(36.77%)로 맞추면 쏘 삼성 × 1.28배가 MDD -25.51%인데
#     맘 삼성은 -38.60%였다. 수익은 같고 낙폭만 13%p 큰, 지배당하는 전략.
#   · 일일 재조정의 변동성 끌림 때문에 배수가 올라갈수록 Sharpe가 떨어진다.
#     나스닥100 1x/2x/3x = 1.08/0.95/0.89, 반도체 1x/2x/3x = 1.00/0.93/0.80.
#     반도체는 3배(SOXL)가 2배(USD)보다 변동성 1.6배인데 CAGR이 오히려 낮았다.
#   · 7개 균등 통합 포트에서 이 전략만 빼면 CAGR 45.15%→45.49%,
#     MDD -17.28%→-13.72%, Sharpe 2.01→2.19로 전 지표가 좋아진다.
# 실제 운용은 삼성증권 계좌를 쏘 삼성 하나로 합쳐 '맘·쏘 삼성'으로 굴린다.
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
                     hide_index=True, use_container_width=True, key="so_off",
                     column_config={'자산': st.column_config.LinkColumn('자산', display_text=r'stock/([A-Za-z0-9]+)\.')})
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
                c = ASSET_COLORS.get(naver_code(row['자산']), '#6B7280')
                return [f'background-color: {c}55; font-weight: 800;'] * len(row)
            sty = ddf.style.apply(_def_style, axis=1)
        else:
            sty = ddf.style.apply(lambda row: ['color: #9CA3AF;'] * len(row), axis=1)
        st.dataframe(sty, hide_index=True, use_container_width=True, key="so_def",
                     column_config=naver_linkcol(ddf, '자산', us=True))

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
    rule_act = rule_active_note(bt, prices,
                                [SO_FILTER_ASSET] + SO_OFFENSE_ASSETS + SO_DEFENSE_ASSETS)
    settings_dict = {
        '전략': '맘·쏘 삼성 (맘 삼성 폐지 후 삼성증권 계좌 통합 운용)',
        '회피 필터': 'SPY 1+3+6+12M 수익률 합 > 0 → 공격'
                    + (' · 리스크오프(cond1) ON' if use_riskoff else ' · 리스크오프 OFF'),
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '규칙 실제 가동': f"{rule_act[1]}개월" if rule_act else "전 기간 (후보 전종목 상장 완료 상태로 시작)",
        '공격': ', '.join(SO_OFFENSE_ASSETS) + f' 중 모멘텀 상위 {SO_TOPK} (4M MA>0인 것만, 50:50)',
        '방어': 'GLD 50% · IEF 50% 고정',
        '벤치마크': ', '.join(BENCHMARKS),
    }
    render_bt_title(t_col, rule_act)
    render_backtest_section(bt, perf, cost_rate, key_prefix="so",
                            strat_color='#F59E0B', strat_name='맘·쏘 삼성 전략',
                            detail_df=detail_df, settings_dict=settings_dict,
                            excel_detail_df=_build_cf_excel(detail_df, signals, bt, prices, _cf_so, lambda t: t),
                            rule_active=rule_act)


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
        _ot = last.get('offense_top', [])
        top_set = set(_ot) if isinstance(_ot, (list, tuple, set)) else set()
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
            if is_active and naver_code(row['티커']) in hold_set:
                c = ASSET_COLORS.get(naver_code(row['티커']), '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="ko_off",
                     column_config=naver_linkcol(odf, '티커'))
    with col_def:
        is_active = defensive_now
        label = f"🛡️ 방어 후보 ({KO_DEF_WIN}M MA 이격도)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#EF4444' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>{len(KO_DEFENSE)}종 중 {KO_DEF_WIN}M MA 이격도 상위 {KO_DEF_TOPK}종 동일가중(50:50)</div>",
                    unsafe_allow_html=True)
        def_ranked = sorted(def_scores, key=def_scores.get, reverse=True)
        rows = []
        for code in def_ranked:
            v = def_scores[code]
            rows.append({'티커': code, '종목명': KO_TICKER_NAMES.get(code, code),
                         f'{KO_DEF_WIN}M 이격도': (f"{v*100:+.1f}%" if pd.notna(v) else 'N/A')})
        ddf = pd.DataFrame(rows)
        def _def_style(row):
            if is_active and naver_code(row['티커']) in hold_set:
                c = ASSET_COLORS.get(naver_code(row['티커']), '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="ko_def",
                     column_config=naver_linkcol(ddf, '티커'))

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
    rule_act = rule_active_note(bt, ko_prices, KO_OFFENSE + KO_DEFENSE)
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
        '규칙 실제 가동': f"{rule_act[1]}개월" if rule_act else "전 기간 (후보 전종목 상장 완료 상태로 시작)",
        '벤치마크': f"{bench_code}({KO_TICKER_NAMES.get(bench_code,'')})",
        '주의': '종목별 상장시점이 달라 초기 구간은 가용 종목만으로 순위(동적 유니버스). ISA/연금 매매용.',
    }
    render_bt_title(t_col, rule_act)
    render_backtest_section(bt, perf, cost_rate, key_prefix="ko",
                            strat_color='#0EA5E9', strat_name='또 ISA 전략',
                            detail_df=detail_df, settings_dict=settings_dict,
                            excel_detail_df=_build_cf_excel(detail_df, signals, bt, ko_prices, _cf_ko, lambda t: KO_TICKER_NAMES.get(t, t)),
                            rule_active=rule_act)


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
            if is_active and naver_code(row['티커']) in hold_set:
                c = ASSET_COLORS.get(naver_code(row['티커']), '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="pen_off",
                     column_config=naver_linkcol(odf, '티커'))
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
            if is_active and naver_code(row['티커']) in hold_set:
                c = ASSET_COLORS.get(naver_code(row['티커']), '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="pen_def",
                     column_config=naver_linkcol(ddf, '티커'))

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
    rule_act = rule_active_note(bt, pen_prices, PEN_OFFENSE + PEN_DEFENSE)
    settings_dict = {
        '전략': '또 연금 (국내 듀얼모멘텀)',
        '위험회피 필터': f'나스닥·KOSPI {PEN_FILTER_WIN}M MA 이격도 하나라도 < 0 → 방어',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '규칙 실제 가동': f"{rule_act[1]}개월" if rule_act else "전 기간 (후보 전종목 상장 완료 상태로 시작)",
        '공격': f'{PEN_NASDAQ}(나스닥100) vs {PEN_KOSPI}(KOSPI200) 중 {PEN_OFF_WIN}M 수익률 높은 1종',
        '방어': f'[{", ".join(PEN_DEFENSE)}] 중 {PEN_DEF_WIN}M MA 이격도 1위 1종',
        '벤치마크': '나스닥100 · KOSPI200 매수후보유',
        '주의': '단일 종목 보유(집중형). 방어자산 상장시점이 달라 초기는 가용분만 선택. 연금/ISA 매매용.',
    }
    render_bt_title(t_col, rule_act)
    render_backtest_section(bt, perf, cost_rate, key_prefix="pen",
                            strat_color='#8B5CF6', strat_name='또 연금 전략',
                            detail_df=detail_df, settings_dict=settings_dict,
                            excel_detail_df=_build_cf_excel(detail_df, signals, bt, pen_prices, _cf_pension, lambda t: PEN_TICKER_NAMES.get(t, t)),
                            rule_active=rule_act)


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
                c = ASSET_COLORS.get(naver_code(row['티커']), '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="ssopen_off",
                     column_config=naver_linkcol(odf, '티커'))
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
            if is_active and naver_code(row['티커']) in hold_set:
                c = ASSET_COLORS.get(naver_code(row['티커']), '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="ssopen_def",
                     column_config=naver_linkcol(ddf, '티커'))

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
    rule_act = rule_active_note(bt, ss_prices, [SSOPEN_NASDAQ] + SSOPEN_DEFENSE)
    settings_dict = {
        '전략': '쏘 연금 (국내 나스닥 단일 + cond1)',
        '위험회피 필터': f'cond1: TIP·VWO·VEA 6M 음수 AND (VIXY 6M 음수 또는 ≥ +{int(VIXY_SPIKE*100)}%) → 방어',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '규칙 실제 가동': f"{rule_act[1]}개월" if rule_act else "전 기간 (후보 전종목 상장 완료 상태로 시작)",
        '공격': f'{SSOPEN_NASDAQ}(미국나스닥100) 단일 100%',
        '방어': f'[{", ".join(SSOPEN_DEFENSE)}] 중 1+3+6+12M 수익률 합 1위 1종',
        '벤치마크': '나스닥100 매수후보유',
        '주의': '단일 종목 보유(집중형). 방어자산 상장시점이 달라 초기는 가용분만 선택. 연금/ISA 매매용.',
    }
    render_bt_title(t_col, rule_act)
    render_backtest_section(bt, perf, cost_rate, key_prefix="ssopen",
                            strat_color='#EC4899', strat_name='쏘 연금 전략',
                            detail_df=detail_df, settings_dict=settings_dict,
                            excel_detail_df=_build_cf_excel(detail_df, signals, bt, ss_prices, _cf_ssopen, lambda t: SSOPEN_TICKER_NAMES.get(t, t)),
                            rule_active=rule_act)


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
        label = f"⚔️ 공격 (12M 수익률 상위{MAMTAX_TOP_OFF}·양수 균등)" + ("" if is_active else "  · 비활성")
        st.markdown(f"<div style='font-weight:800; font-size:15px; margin-bottom:4px; "
                    f"color:{'#10B981' if is_active else '#9CA3AF'};'>{label}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px; color:#9CA3AF; margin-bottom:2px;'>10종 중 12M 수익률 "
                    f"상위 {MAMTAX_TOP_OFF}위 → 12M 음수 제외 → 남은 승자 균등(듀얼모멘텀)</div>",
                    unsafe_allow_html=True)
        ranked = sorted(off_scores, key=off_scores.get, reverse=True)
        rows = []
        for rk, t in enumerate(ranked, 1):
            lt = mamtax_live_ticker(t)
            rows.append({'순위': rk, '실운용': lt, '종목명': mamtax_live_name(t),
                         '12M수익률': f"{off_scores[t]*100:+.1f}%",
                         '보유': (f"{holds[t]*100:.0f}%" if t in hold_set else '—')})
        odf = pd.DataFrame(rows)

        def _off_style(row):
            if is_active and naver_code(row['실운용']) in held_live:
                c = ASSET_COLORS.get(naver_code(row['실운용']), '#10B981')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row]
        st.dataframe(odf.style.apply(_off_style, axis=1), hide_index=True,
                     use_container_width=True, key="mamtax_off",
                     column_config=naver_linkcol(odf, '실운용'))
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
            if is_active and naver_code(row['티커']) in hold_set:
                c = ASSET_COLORS.get(naver_code(row['티커']), '#EF4444')
                return [f'background-color: {c}44; font-weight: 800;' for _ in row]
            return ['color: #9CA3AF;' for _ in row] if not is_active else ['' for _ in row]
        st.dataframe(ddf.style.apply(_def_style, axis=1), hide_index=True,
                     use_container_width=True, key="mamtax_def",
                     column_config=naver_linkcol(ddf, '티커'))

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
    rule_act = rule_active_note(bt, mp, MAMTAX_OFFENSE + MAMTAX_DEFENSE)
    settings_dict = {
        '전략': '맘 비과세 (글로벌 듀얼모멘텀 + cond1)',
        '공격': f'10종 중 12M 수익률 상위{MAMTAX_TOP_OFF} → 12M 음수 제외 → 승자 균등(듀얼모멘텀)',
        '방어': '6종 중 3M MA이격도 상위2, 각 50% (cond1 발동 시)',
        '위험회피 필터': f'cond1: TIP·VWO·VEA 6M 음수 AND (VIXY 6M 음수 또는 ≥ +{int(VIXY_SPIKE*100)}%)',
        '거래비용/교체': f"{cost_pct:.2f}%",
        '기간': f"{perf['n_months']}개월 ({bt['hold_month'].iloc[0]} ~ {bt['hold_month'].iloc[-1]})",
        '규칙 실제 가동': f"{rule_act[1]}개월" if rule_act else "전 기간 (후보 전종목 상장 완료 상태로 시작)",
        '벤치마크': '나스닥100·KOSPI200 매수후보유',
        '티커': '신호·백테스트=133690·102110·192090(장수), 실운용=379810·278530·192090',
        '주의': '공격 자산 상장시점이 달라 초기는 부분 유니버스(4→10종). 비과세계좌 매매용.',
    }
    render_bt_title(t_col, rule_act)
    render_backtest_section(bt, perf, cost_rate, key_prefix="mamtax",
                            strat_color='#F97316', strat_name='맘 비과세 전략',
                            detail_df=detail_df, settings_dict=settings_dict,
                            excel_detail_df=_build_cf_excel(detail_df, signals, bt, mp, _cf_mamtax, mamtax_live_name),
                            rule_active=rule_act)


# ==========================================
# 통합 포트 (탭 8) — 7개 전략을 실제 비중으로 합산
# ==========================================
#
# 탭을 하나씩 보면 그달 제일 아픈 숫자만 눈에 들어온다. 실제 자산은 7개 계좌에
# 나뉘어 있으므로, 전체가 얼마나 흔들렸는지는 비중을 넣어 합쳐야 보인다.
# (예: 2026-07은 맘 삼성 탭에 -38.6%가 찍히지만 균등 배분이면 전체는 -17.9%다.)

STRAT_META = [
    # (키, 표시명, 색)  ※ 맘 삼성은 2026-08 폐지 (아래 사유)
    ('meritz',  '또 메리츠',   '#10B981'),
    ('so',      '맘·쏘 삼성', '#F59E0B'),
    ('ko',      '또 ISA',    '#0EA5E9'),
    ('pen',     '또 연금',    '#8B5CF6'),
    ('ssopen',  '쏘 연금',    '#EC4899'),
    ('mamtax',  '맘 비과세',  '#F97316'),
]


@st.cache_data(ttl="1h", show_spinner=False)
def build_all_strategy_returns(cost_rate):
    """7개 전략의 월별 순수익률을 한 프레임으로 (index=보유월 문자열).

    각 탭이 쓰는 것과 동일한 신호·백테스트 함수를 그대로 호출한다.
    비어 있는 달(전략마다 시작 시점이 다름)은 NaN.
    """
    ko_p = load_ko_prices()
    pen_p = load_pen_prices()
    ss_p = load_ssopen_prices()
    mp = load_mamtax_prices()
    out = {}

    def _put(key, bt):
        if bt is not None and not bt.empty:
            out[key] = bt.set_index('hold_month')['ret_strategy']

    _put('meritz',  run_backtest(prices, compute_signals(prices, div_yield), cost=cost_rate))
    _put('so',      run_backtest_so(prices, compute_signals_so(prices), cost=cost_rate))
    if not ko_p.empty:
        _put('ko', run_backtest_ko(ko_p, compute_signals_ko(ko_p), cost=cost_rate))
    if not pen_p.empty:
        _put('pen', run_backtest_pension(pen_p, compute_signals_pension(pen_p), cost=cost_rate))
    if not ss_p.empty:
        _put('ssopen', run_backtest_ssopen(ss_p, compute_signals_ssopen(ss_p, prices), cost=cost_rate))
    if not mp.empty:
        _put('mamtax', run_backtest_mamtax(mp, compute_signals_mamtax(mp, prices), cost=cost_rate))

    return pd.DataFrame(out).sort_index()


@st.cache_data(ttl="1h", show_spinner=False)
def build_current_states():
    """전략별 '이번 달' 국면(공격/방어). 추천 비중의 국면 기울기에 쓴다."""
    ko_p = load_ko_prices(); pen_p = load_pen_prices()
    ss_p = load_ssopen_prices(); mp = load_mamtax_prices()
    out = {}

    def _last(key, sig):
        if sig is None or sig.empty or 'defensive' not in sig.columns:
            return
        s = sig[sig['defensive'].notna()]
        if len(s):
            out[key] = {'defensive': bool(s.iloc[-1]['defensive'])}

    _last('meritz', compute_signals(prices, div_yield))
    _last('so', compute_signals_so(prices))
    if not ko_p.empty:
        _last('ko', compute_signals_ko(ko_p))
    if not pen_p.empty:
        _last('pen', compute_signals_pension(pen_p))
    if not ss_p.empty:
        _last('ssopen', compute_signals_ssopen(ss_p, prices))
    if not mp.empty:
        _last('mamtax', compute_signals_mamtax(mp, prices))
    return out


def _shade_signed(v, cap):
    """음수=빨강 / 양수=초록 배경. matplotlib 없이 인라인 rgba로 처리.
    (Styler.background_gradient는 matplotlib을 요구하는데 이 레포엔 의존성이 없다.)"""
    if pd.isna(v) or cap <= 0:
        return ''
    a = min(abs(v) / cap, 1.0) * 0.55
    return f"background-color: rgba({'239,68,68' if v < 0 else '34,197,94'},{a:.3f})"


def _shade_corr(v):
    """상관계수 0~1 → 초록에서 빨강으로."""
    if pd.isna(v):
        return ''
    a = min(max(float(v), 0.0), 1.0) * 0.55
    return f"background-color: rgba(239,68,68,{a:.3f})"


def _port_stats(r):
    """월수익률 시리즈 → 성과지표."""
    r = r.dropna()
    if len(r) < 2:
        return None
    cum = (1 + r).cumprod()
    dd = cum / cum.cummax().clip(lower=1.0) - 1.0
    sd = r.std(ddof=0)
    # Sortino: 하락 편차만 위험으로 본다. 상승 급등(2026-05 +54% 같은 달)을
    # 벌주지 않아 비대칭 수익 분포를 가진 이 전략들에 Sharpe보다 공정하다.
    downside = np.sqrt((np.minimum(r, 0.0) ** 2).mean())
    n = len(r)
    return {
        'n': n, 'cum': cum.iloc[-1] - 1.0, 'cagr': cum.iloc[-1] ** (12.0 / n) - 1.0,
        'mdd': dd.min(), 'sharpe': (r.mean() / sd * np.sqrt(12)) if sd > 0 else 0.0,
        'sortino': (r.mean() / downside * np.sqrt(12)) if downside > 0 else 0.0,
        'win': (r > 0).mean(), 'equity': cum, 'dd': dd, 'ret': r,
    }


def _round_to_step(wdict, step=10):
    """비중(합=1)을 step% 단위로 반올림하되 합계를 정확히 100%로 맞춘다(최대잔여법)."""
    raw = {k: v * 100 for k, v in wdict.items()}
    base = {k: int(v // step) * step for k, v in raw.items()}
    left = 100 - sum(base.values())
    # 버림으로 잃은 양이 큰 순서대로 step씩 되돌려 준다
    order = sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)
    i = 0
    while left >= step and order:
        base[order[i % len(order)]] += step
        left -= step
        i += 1
    return base


def recommend_weights(R, states, step=10, wmax=40, aggr=0.5):
    """이번달 추천 비중과 그 근거표.

    두 극단을 기하평균으로 섞는다 (aggr = 수익 반영 강도, 0~1):
      · aggr=0 → 순수 역변동성(리스크 패리티). 수익률을 아예 안 보므로
                 과최적화 여지가 가장 적지만, 잘 버는 전략도 눌러 버린다.
      · aggr=1 → 순수 Sortino 비례. 잘 버는 쪽에 확실히 실어 준다.
    Sortino를 쓰는 이유: 하락 편차만 위험으로 봐서, 상승 급등(2026-05 +54%)을
    벌주지 않는다. 이 전략들처럼 수익 분포가 비대칭이면 Sharpe보다 공정하다.

    그 위에 완만한 기울기 둘을 더 얹는다:
      · 계절성 : 다음 보유월의 과거 같은 달 평균 (±15%, 표본이 얇아 약하게)
      · 국면   : 이번 달 방어 모드면 부담 위험이 작으므로 ×1.15

    ⚠️ 최적해가 아니라 출발점이다. 근거표와 '이 비중의 과거 성과'를 같이
       보여주는 이유 — 숫자를 그대로 믿지 말고 직접 비교하라는 뜻.
    """
    rows, score = [], {}
    nmap = dict((k, n) for k, n, _ in STRAT_META)
    hold_month = (int(str(R.index[-1])[-2:]) % 12) + 1     # 다음 보유월

    sor, vol, sea, sh = {}, {}, {}, {}
    for k in R.columns:
        r = R[k].dropna()
        if len(r) < 24:
            continue
        tail = r.tail(36)
        sd = tail.std(ddof=0)
        vol[k] = sd * np.sqrt(12) if sd > 0 else np.nan
        st_ = _port_stats(r)
        sor[k] = st_['sortino']
        sh[k] = st_['sharpe']
        same = r[[int(str(i)[-2:]) == hold_month for i in r.index]]
        sea[k] = same.mean() if len(same) >= 3 else 0.0

    keys = [k for k in R.columns if k in vol and pd.notna(vol[k]) and vol[k] > 0]
    if not keys:
        return {}, pd.DataFrame()

    def _norm(d):
        t = sum(d.values())
        return {k: v / t for k, v in d.items()} if t > 0 else {k: 1 / len(d) for k in d}

    def _tilt(vals, lam=0.15):
        """값 → 평균 대비 ±lam 배율. 표준편차가 0이면 전부 1.0."""
        a = pd.Series(vals, dtype=float)
        sd = a.std(ddof=0)
        if not np.isfinite(sd) or sd == 0:
            return {k: 1.0 for k in a.index}
        z = ((a - a.mean()) / sd).clip(-1.5, 1.5)
        return (1 + lam * z / 1.5).to_dict()

    w_risk = _norm({k: 1.0 / vol[k] for k in keys})            # 역변동성
    w_perf = _norm({k: max(sor[k], 0.05) for k in keys})       # Sortino 비례
    a = min(max(float(aggr), 0.0), 1.0)
    t_s = _tilt({k: sea[k] for k in keys})
    for k in keys:
        defensive = states.get(k, {}).get('defensive')
        t_r = 1.15 if defensive is True else 1.0
        # 기하평균 혼합 — 두 배분 사이를 매끄럽게 오가고 항상 양수를 유지한다
        score[k] = (w_risk[k] ** (1 - a)) * (w_perf[k] ** a) * t_s[k] * t_r
        rows.append({'전략': nmap.get(k, k),
                     '국면': ('🛡️ 방어' if defensive is True
                              else '⚔️ 공격' if defensive is False else '—'),
                     'CAGR': _port_stats(R[k])['cagr'] * 100,
                     '연변동성': vol[k] * 100,
                     'Sortino': sor[k], 'Sharpe': sh[k],
                     f'{hold_month}월 평균': sea[k] * 100,
                     'MDD': _port_stats(R[k])['mdd'] * 100})

    tot = sum(score.values())
    w = {k: v / tot for k, v in score.items()}
    # 한 전략이 과하게 커지지 않도록 상한을 걸고 나머지에 재분배
    for _ in range(6):
        over = {k: v for k, v in w.items() if v > wmax / 100}
        if not over:
            break
        spill = sum(v - wmax / 100 for v in over.values())
        rest = [k for k in w if k not in over]
        if not rest:
            break
        for k in over:
            w[k] = wmax / 100
        add = spill / len(rest)
        for k in rest:
            w[k] += add

    rec = _round_to_step(w, step)
    df = pd.DataFrame(rows)
    # 반올림 전 값도 같이 보여준다 — 10% 단위로 자르면 슬라이더를 움직여도
    # 추천이 그대로인 구간이 생기는데, 그때 실제로는 무엇이 움직였는지 보이게.
    df['계산값'] = [w.get(k, 0) * 100 for k in keys]
    df['추천'] = [rec.get(k, 0) for k in keys]
    return rec, df.sort_values('계산값', ascending=False)


def render_combined():
    st.markdown("### 📊 통합 포트 — 내 실제 비중으로 합산")
    st.caption("탭별로 보면 그달 제일 아픈 숫자만 보입니다. 계좌 비중을 넣으면 "
               "전체 자산이 실제로 얼마나 움직였는지 한 화면에서 보입니다.")

    cost_pct = st.number_input("거래비용 (%/교체)", 0.0, 1.0, 0.25, 0.05,
                               key="comb_cost", help="7개 전략에 동일 적용")
    cost_rate = cost_pct / 100.0

    with st.spinner("7개 전략 백테스트 중..."):
        R = build_all_strategy_returns(cost_rate)
    if R.empty:
        st.error("전략 수익률을 계산할 수 없습니다.")
        return

    # ---- 비중 입력 (금액 ↔ 비율 양방향) ----
    nmap = dict((k, n) for k, n, _ in STRAT_META)
    KEYS = [k for k, _, _ in STRAT_META if k in R.columns]

    # 금액(만원)을 원본으로 두고 비율은 파생값. 반대로 비율을 고치면 총액 기준으로
    # 금액을 되돌려 계산한다. on_change 콜백은 rerun '전에' 돌아 위젯 값을 갱신한다.
    def _sv(key):
        return float(st.session_state.get(key, 0) or 0)

    if 'comb_ready' not in st.session_state:
        for k in KEYS:
            st.session_state[f'amt_{k}'] = 1000.0
            st.session_state[f'pct_{k}'] = round(100.0 / len(KEYS), 1)
        # 반올림 오차는 마지막 항목이 흡수해 합계를 정확히 100%로
        st.session_state[f'pct_{KEYS[-1]}'] = round(
            100.0 - sum(_sv(f'pct_{k}') for k in KEYS[:-1]), 1)
        st.session_state['comb_total'] = 1000.0 * len(KEYS)
        st.session_state['comb_ready'] = True

    def _amt_from_pct():
        t = _sv('comb_total')
        s = sum(_sv(f'pct_{k}') for k in KEYS)
        for k in KEYS:
            st.session_state[f'amt_{k}'] = round(t * _sv(f'pct_{k}') / s, 1) if s > 0 else 0.0

    def _from_amt():
        """금액을 고치면 총액과 비율이 따라온다."""
        t = sum(_sv(f'amt_{k}') for k in KEYS)
        st.session_state['comb_total'] = t
        for k in KEYS:
            st.session_state[f'pct_{k}'] = round(_sv(f'amt_{k}') / t * 100, 1) if t > 0 else 0.0

    def _from_pct(changed=None):
        """비율을 고치면 나머지 비율이 비례로 밀려 합계 100%를 유지하고, 금액이 따라온다.

        직접 고친 항목은 입력값 그대로 둔다(정규화로 값이 바뀌면 놀라니까).
        총액 위젯에서 호출될 땐 changed=None — 비율은 그대로 두고 금액만 스케일한다.
        """
        if changed is not None:
            keep = min(max(_sv(f'pct_{changed}'), 0.0), 100.0)
            st.session_state[f'pct_{changed}'] = keep
            others = [k for k in KEYS if k != changed]
            room = 100.0 - keep
            s_o = sum(_sv(f'pct_{k}') for k in others)
            for k in others:
                st.session_state[f'pct_{k}'] = (
                    round(room * _sv(f'pct_{k}') / s_o, 1) if s_o > 0
                    else round(room / len(others), 1) if others else 0.0)
            if others:   # 반올림 오차 흡수
                st.session_state[f'pct_{others[-1]}'] = round(
                    100.0 - keep - sum(_sv(f'pct_{k}') for k in others[:-1]), 1)
        _amt_from_pct()

    def _apply_rec(rec):
        """추천 비중 적용. 위젯 생성 후에는 session_state를 못 바꾸므로
        반드시 on_click 콜백에서 처리한다 (콜백은 다음 실행 '전에' 돈다)."""
        for k in KEYS:
            st.session_state[f'pct_{k}'] = float(rec.get(k, 0))
        _amt_from_pct()

    st.markdown("#### 1️⃣ 계좌 금액 · 비중")
    st.caption("금액을 넣으면 비율이, 비율을 넣으면 금액이 자동으로 따라옵니다. "
               "총액을 바꾸면 비율을 유지한 채 금액만 스케일됩니다. 단위는 **만원**.")

    tcol, _sp = st.columns([1, 3])
    with tcol:
        st.number_input("총 투자금액 (만원)", min_value=0.0, step=100.0,
                        key='comb_total', on_change=_from_pct, format="%.0f")

    st.markdown("<div style='font-size:12px; color:#9CA3AF; margin:2px 0;'>금액 (만원)</div>",
                unsafe_allow_html=True)
    for c, k in zip(st.columns(len(KEYS)), KEYS):
        with c:
            st.number_input(nmap[k], min_value=0.0, step=100.0,
                            key=f'amt_{k}', on_change=_from_amt, format="%.0f")
    st.markdown("<div style='font-size:12px; color:#9CA3AF; margin:6px 0 2px;'>비중 (%)</div>",
                unsafe_allow_html=True)
    for c, k in zip(st.columns(len(KEYS)), KEYS):
        with c:
            st.number_input(nmap[k], min_value=0.0, max_value=100.0, step=1.0,
                            key=f'pct_{k}', on_change=_from_pct, args=(k,),
                            format="%.1f", label_visibility='collapsed')

    raw = {k: float(st.session_state.get(f'pct_{k}', 0) or 0) for k in KEYS}
    tot = sum(raw.values())
    if tot <= 0:
        st.warning("비중을 하나 이상 0보다 크게 넣어주세요.")
        return
    W = {k: v / tot for k, v in raw.items() if v > 0}
    st.caption(f"입력 비중 합계 {tot:.1f}%"
               + ("" if abs(tot - 100) < 0.05 else " — 100%가 아니어서 정규화해 계산합니다."))

    # ---- 이번달 추천 비중 ----
    with st.expander("🎯 이번달 추천 비중 (10% 단위)", expanded=True):
        states = build_current_states()
        aggr = st.slider(
            "수익 반영 강도", 0.0, 1.0, 0.5, 0.1, key="comb_aggr",
            help="0 = 순수 역변동성(위험 균등, 잘 버는 전략도 눌림) / "
                 "1 = 순수 Sortino 비례(잘 버는 쪽에 확실히 실음)")
        rec, rdf = recommend_weights(R, states, step=10, aggr=aggr)
        if rec:
            st.markdown("**추천 — " + " · ".join(
                f"{nmap.get(k, k)} {v}%" for k, v in
                sorted(rec.items(), key=lambda x: -x[1]) if v > 0) + "**")

            # 이 비중을 과거에 그대로 굴렸다면? — 강도를 바꿀 때마다 대가가 보이게
            def _apply(wmap):
                sub = R[[k for k in wmap if k in R.columns and wmap[k] > 0]]
                if sub.empty:
                    return None
                ws = pd.Series({k: v for k, v in wmap.items() if k in sub.columns},
                               dtype=float)
                m = sub.notna()
                den = m.mul(ws, axis=1).sum(axis=1)
                return _port_stats((sub.fillna(0).mul(ws, axis=1).sum(axis=1)
                                    / den.replace(0, np.nan)).dropna())

            cur = _apply(rec)
            eqw = _apply({k: 1.0 for k in rec})
            if cur:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("이 비중의 CAGR", f"{cur['cagr']*100:.1f}%",
                          delta=(f"균등 대비 {(cur['cagr']-eqw['cagr'])*100:+.1f}%p"
                                 if eqw else None))
                m2.metric("MDD", f"{cur['mdd']*100:.1f}%",
                          delta=(f"{(cur['mdd']-eqw['mdd'])*100:+.1f}%p" if eqw else None),
                          delta_color="inverse")
                m3.metric("Sortino", f"{cur['sortino']:.2f}",
                          delta=(f"{cur['sortino']-eqw['sortino']:+.2f}" if eqw else None))
                m4.metric("Sharpe", f"{cur['sharpe']:.2f}",
                          delta=(f"{cur['sharpe']-eqw['sharpe']:+.2f}" if eqw else None))
                st.caption("↑ 이 비중을 공통구간에 그대로 적용했을 때의 과거 성과입니다 "
                           "(비교 대상은 같은 전략들의 균등 배분). "
                           "슬라이더를 좌우로 움직여 수익과 낙폭이 어떻게 맞바뀌는지 보세요.")

            fmt = {'CAGR': '{:.1f}%', '연변동성': '{:.1f}%', 'Sortino': '{:.2f}',
                   'Sharpe': '{:.2f}', 'MDD': '{:.1f}%',
                   '계산값': '{:.1f}%', '추천': '{:.0f}%'}
            fmt.update({c: '{:+.2f}%' for c in rdf.columns if c.endswith('월 평균')})
            st.dataframe(rdf.style.format(fmt),
                         width="stretch", hide_index=True, key="comb_rec")
            st.button("이 비중으로 채우기", key="comb_apply",
                      on_click=_apply_rec, args=(rec,))
            st.caption(
                "**계산 방식** — 역변동성(위험 균등)과 Sortino 비례(수익 위주) 두 배분을 "
                "위 슬라이더 값으로 기하평균해 섞습니다. Sortino를 쓰는 건 하락 편차만 "
                "위험으로 봐서, 2026-05 +54% 같은 상승 급등을 벌주지 않기 때문입니다. "
                "여기에 다음 보유월의 과거 같은 달 평균(±15%)과 이번 달 방어 여부(×1.15)를 "
                "얹고, 한 전략이 40%를 넘지 않게 잘랐습니다.")
            st.caption(
                "⚠️ **최적해가 아니라 출발점입니다.** 계절성은 전략당 표본이 8~15개월뿐이고, "
                "Sortino·MDD는 과거를 보고 만든 규칙의 백테스트 값이라 실전보다 낙관적입니다. "
                "강도를 1.0까지 올리면 과거에 잘한 전략에 그만큼 몰리는데, 그게 앞으로도 "
                "잘한다는 보장은 없습니다.")
        else:
            st.info("추천을 계산할 만큼 이력이 충분하지 않습니다.")

    # ---- 합산 ----
    # 전략마다 시작월이 다르다. 그달 존재하는 전략들끼리 비중을 다시 정규화해
    # '없는 전략은 현금'이 아니라 '있는 것들에 비례 배분'으로 처리한다.
    sub = R[list(W)]
    wser = pd.Series(W)
    mask = sub.notna()
    wsum = mask.mul(wser, axis=1).sum(axis=1)
    port = sub.fillna(0).mul(wser, axis=1).sum(axis=1) / wsum.replace(0, np.nan)
    port = port.dropna()

    full = mask.all(axis=1)
    first_full = full[full].index[0] if full.any() else None

    s_all = _port_stats(port)
    s_full = _port_stats(port[port.index >= first_full]) if first_full else None

    st.markdown("#### 2️⃣ 통합 성과")
    if first_full:
        st.caption(f"⏳ 선택한 전략이 모두 존재하는 건 **{first_full}**부터입니다. "
                   f"그 이전은 당시 가용한 전략끼리 비중을 재정규화해 계산했습니다.")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    base = s_full or s_all
    c1.metric("CAGR", f"{base['cagr']*100:.1f}%")
    c2.metric("MDD", f"{base['mdd']*100:.1f}%", delta_color="inverse")
    c3.metric("Sortino", f"{base['sortino']:.2f}",
              help="하락 편차만 위험으로 보는 지표. 상승 급등을 벌주지 않아 "
                   "수익 분포가 비대칭인 이 전략들에는 Sharpe보다 공정하다.")
    c4.metric("Sharpe", f"{base['sharpe']:.2f}",
              help="상승·하락 변동성을 똑같이 위험으로 본다. 참고용.")
    c5.metric("누적 수익", f"{base['cum']*100:,.0f}%")
    c6.metric("승률", f"{base['win']*100:.0f}%", delta=f"{base['n']}개월")
    if first_full and s_all:
        st.caption(f"※ 위 지표는 전 전략 공통구간({first_full}~) 기준입니다. "
                   f"전체 구간({s_all['n']}개월) 기준으로는 "
                   f"CAGR {s_all['cagr']*100:.1f}% · MDD {s_all['mdd']*100:.1f}% · "
                   f"Sortino {s_all['sortino']:.2f} · Sharpe {s_all['sharpe']:.2f}.")

    # ---- 개별 vs 통합 비교표 ----
    st.markdown("#### 3️⃣ 개별 전략 vs 통합 (공통구간, 같은 자로 비교)")
    span = base['ret'].index
    rows = []
    nmap = dict((k, n) for k, n, _ in STRAT_META)
    for key in W:
        s = _port_stats(R.loc[span, key])
        if not s:
            continue
        rows.append({'전략': nmap[key], '비중': f"{W[key]*100:.1f}%",
                     'CAGR': s['cagr']*100, 'MDD': s['mdd']*100,
                     'Sortino': s['sortino'], 'Sharpe': s['sharpe'],
                     '2026-07': R.loc['2026-07', key]*100 if '2026-07' in R.index else np.nan})
    rows.append({'전략': '★ 통합 포트', '비중': '100%',
                 'CAGR': base['cagr']*100, 'MDD': base['mdd']*100,
                 'Sortino': base['sortino'], 'Sharpe': base['sharpe'],
                 '2026-07': port.get('2026-07', np.nan)*100})
    cmp_df = pd.DataFrame(rows)
    st.dataframe(
        cmp_df.style.format({'CAGR': '{:.2f}%', 'MDD': '{:.2f}%', 'Sortino': '{:.2f}',
                             'Sharpe': '{:.2f}', '2026-07': '{:.2f}%'})
        .apply(lambda s: ['font-weight:800; background-color:rgba(59,130,246,.15)'
                          if v == '★ 통합 포트' else '' for v in cmp_df['전략']], axis=0),
        width="stretch", hide_index=True, key="comb_cmp")
    best = cmp_df.iloc[:-1]['Sharpe'].max()
    if base['sharpe'] > best:
        st.success(f"✅ 통합 Sharpe {base['sharpe']:.2f} — 개별 최고({best:.2f})보다 높습니다. "
                   f"상관관계가 낮아 분산에서 생기는 이득입니다.")

    # ---- 자산곡선 ----
    st.markdown("#### 4️⃣ 자산곡선 & 낙폭")
    fig = go.Figure()
    for key in W:
        s = _port_stats(R.loc[span, key])
        if not s:
            continue
        col = dict((k, c) for k, _, c in STRAT_META)[key]
        fig.add_trace(go.Scatter(x=list(s['equity'].index), y=s['equity'].values,
                                 name=nmap[key], line=dict(width=1.2, color=col),
                                 opacity=0.45))
    fig.add_trace(go.Scatter(x=list(base['equity'].index), y=base['equity'].values,
                             name='★ 통합 포트', line=dict(width=3.4, color='#FFFFFF')))
    fig.update_layout(height=420, yaxis_type='log', template='plotly_dark',
                      yaxis_title='누적 (로그)', margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation='h', y=1.12))
    st.plotly_chart(fig, width="stretch", key="comb_eq")

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=list(base['dd'].index), y=base['dd'].values*100,
                              fill='tozeroy', name='통합 낙폭',
                              line=dict(color='#EF4444', width=1.5)))
    fig2.update_layout(height=240, template='plotly_dark', yaxis_title='낙폭 (%)',
                       margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    st.plotly_chart(fig2, width="stretch", key="comb_dd")

    # ---- 기여도 ----
    st.markdown("#### 5️⃣ 특정 달 기여도 — 그달 전체를 누가 끌어내렸나")
    months = list(base['ret'].index)[::-1]
    pick = st.selectbox("월 선택", months, index=0, key="comb_month")
    crows = []
    for key in W:
        r = R.loc[pick, key] if pick in R.index else np.nan
        if pd.isna(r):
            continue
        crows.append({'전략': nmap[key], '비중': W[key]*100,
                      '그달 수익률': r*100, '기여도(%p)': r*W[key]*100})
    cdf = pd.DataFrame(crows).sort_values('기여도(%p)')
    cap = cdf['기여도(%p)'].abs().max() if not cdf.empty else 0.0
    st.dataframe(cdf.style.format({'비중': '{:.1f}%', '그달 수익률': '{:.2f}%',
                                   '기여도(%p)': '{:+.2f}'})
                 .map(lambda v: _shade_signed(v, cap), subset=['기여도(%p)']),
                 width="stretch", hide_index=True, key="comb_contrib")
    st.caption(f"**{pick} 통합 수익률 = {port.get(pick, np.nan)*100:.2f}%** "
               f"(기여도 합계). 개별 탭의 큰 숫자와 전체 영향의 차이를 확인하세요.")

    # ---- 상관관계 ----
    st.markdown("#### 6️⃣ 전략 간 상관관계 (공통구간 월수익률)")
    st.caption("낮을수록 분산 효과가 큽니다. 다만 폭락장에서는 상관이 함께 올라가므로, "
               "분산은 구덩이를 얕게 만들 뿐 피하게 해주지는 않습니다.")
    corr = R.loc[span, list(W)].rename(columns=nmap).corr()
    st.dataframe(corr.style.format('{:.2f}').map(_shade_corr),
                 width="stretch", key="comb_corr")


# ==========================================
# 탭 배치
# ==========================================
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["🇺🇸 또 메리츠", "🇺🇸 맘·쏘 삼성", "🇰🇷 또 ISA", "🇰🇷 또 연금", "🇰🇷 쏘 연금",
     "🇰🇷 맘 비과세", "📊 통합 포트"])
with tab1:
    render_meritz()
with tab2:
    render_so()
with tab3:
    render_ko()
with tab4:
    render_pension()
with tab5:
    render_ssopen()
with tab6:
    render_mamtax()
with tab7:
    render_combined()
