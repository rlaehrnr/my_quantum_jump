import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="퀀트 종합 대시보드", layout="wide", page_icon="📊")

st.markdown("""
<style>
.block-container { padding-top: 3.2rem !important; padding-bottom: 1rem !important; }
.badge-on  { background:#10352422; color:#34D399; border:1px solid #34D39955;
             padding:3px 12px; border-radius:6px; font-weight:900; font-size:0.9rem; }
.badge-off { background:#3b101022; color:#F87171; border:1px solid #F8717155;
             padding:3px 12px; border-radius:6px; font-weight:900; font-size:0.9rem; }
.mini table { width:100%; border-collapse:collapse; font-size:0.83rem; }
.mini th { color:#9CA3AF; text-align:left; padding:5px 8px; font-weight:600; border-bottom:1px solid #2a3140; }
.mini td { padding:4px 8px; border-bottom:1px solid #1c212b; color:#D1D5DB; }
.pos { color:#F87171; font-weight:700; } .neg { color:#60A5FA; font-weight:700; }
.dim { color:#6B7280; }
.avg-chip { display:inline-block; background:#1c2430; border:1px solid #2a3547;
            border-radius:6px; padding:2px 10px; font-size:0.83rem; margin-left:8px; }
.sect-h { font-size:0.85rem; font-weight:700; display:flex; align-items:center; margin:2px 0 4px 0; }
.strat-row { display:flex; align-items:center; padding:8px 4px; border-bottom:1px solid #1c212b;
             font-size:0.84rem; white-space:nowrap; }
.strat-row:last-child { border-bottom:none; }
.strat-name { flex:0 0 150px; } .strat-hold { flex:1; text-align:right; color:#9CA3AF; }
[data-testid="stPageLink"] a { font-size:1.1rem !important; font-weight:800 !important;
    color:#E5E7EB !important; padding:2px 0 !important; }
[data-testid="stPageLink"] a:hover { color:#93C5FD !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h2 style='margin:0 0 22px 0;'>📊 퀀트 종합 대시보드 "
            "<span style='font-size:0.9rem; color:#6B7280; font-weight:500;'>· 4개 전략 현재 상태 한눈에</span></h2>",
            unsafe_allow_html=True)

PAGE_KOSPI = "pages/1_🇰🇷_KOSPI200_모멘텀.py"
PAGE_USA = "pages/4_🇺🇸_USA500_모멘텀.py"
PAGE_SMALL = "pages/5_내 소형주 퀀트 포트.py"
PAGE_SNOW = "pages/6 ❄️ 스노우볼 포트.py"


def _fmt(v):
    try:
        v = float(v); cls = 'pos' if v > 0 else ('neg' if v < 0 else 'dim')
        return f"<span class='{cls}'>{v:+.1f}%</span>"
    except Exception:
        return "<span class='dim'>-</span>"


def _tbl(rows):
    out = "<div class='mini'><table><tr><th>티커</th><th>종목명</th><th style='text-align:right;'>수익률</th></tr>"
    for code, name, ret in rows:
        out += (f"<tr><td class='dim'>{code}</td><td>{name}</td>"
                f"<td style='text-align:right;'>{_fmt(ret)}</td></tr>")
    return out + "</table></div>"


def _header(path, title, badge=None, refdate=None):
    c1, c2 = st.columns([3, 2])
    with c1:
        st.page_link(path, label=title)
        if refdate:
            st.markdown(f"<div style='font-size:0.75rem; color:#6B7280; margin-top:-10px; margin-bottom:6px;'>{refdate}</div>",
                        unsafe_allow_html=True)
    with c2:
        if badge:
            st.markdown(f"<div style='text-align:right; padding-top:4px;'>{badge}</div>", unsafe_allow_html=True)


def _badge(stop, reason):
    b = (f"<span class='badge-off'>🛑 투자 중지</span>" if stop else f"<span class='badge-on'>✅ 투자 진행</span>")
    return b + f" <span class='dim' style='font-size:0.78rem;'>({reason})</span>"


# ══════════════ 계산부 (캐시로 재로딩 가속) ══════════════
@st.cache_data(ttl=1800, show_spinner=False)
def _kospi_status():
    from utils.data_loader import load_daily_data
    from utils.calculator import get_kospi_ma_all, get_strategy_stocks_korea
    df_daily = load_daily_data()
    if df_daily is None or df_daily.empty:
        return None
    try:
        kc, kmas = get_kospi_ma_all(datetime.today().strftime('%Y-%m-%d'))
    except Exception:
        kc, kmas = 0, {}
    dk, dp, ds = get_strategy_stocks_korea(df_daily)
    n1 = int((dk['1개월(%)'] < 0).sum()) if '1개월(%)' in dk else 0
    n3 = int((dk['3개월(%)'] < 0).sum()) if '3개월(%)' in dk else 0
    is_bad = (n1 >= 100) and (n3 >= 100)
    is_below = (kc > 0) and (kc < kmas.get(6, 0))
    stop = is_bad or is_below
    reason = (("하락장 " if is_bad else "") + ("6개월선 이탈" if is_below else "")) or "안전"
    rc = '이번달수익률' if '이번달수익률' in dp.columns else '1개월(%)'
    perf = [(r['종목코드'], r['종목명'], r.get(rc)) for _, r in dp.head(6).iterrows()]
    spec = [(r['종목코드'], r['종목명'], r.get(rc)) for _, r in ds.head(2).iterrows()]
    allr = [x[2] for x in perf + spec if pd.notna(x[2])]
    avg = float(np.mean(allr)) if allr else 0.0
    refdate = str(df_daily['기준일'].iloc[0]) if '기준일' in df_daily.columns else None
    return {'stop': stop, 'reason': reason, 'avg': avg, 'perf': perf, 'spec': spec, 'refdate': refdate}


@st.cache_data(ttl=1800, show_spinner=False)
def _usa_status():
    from utils.data_loader import load_archive_data, get_folder_hash
    from utils.us_helpers import (preprocess_us_data, get_triple_momentum_us,
                                  get_spy_timing_map, get_multi4_cond1_map)
    df_raw = load_archive_data("archive_usa", get_folder_hash("archive_usa"))
    if df_raw is None or df_raw.empty:
        return None
    df = preprocess_us_data(df_raw, is_daily=False)
    latest = sorted(df['투자월'].dropna().unique())[-1]
    picks = get_triple_momentum_us(df[df['투자월'] == latest].copy(), cutoff=100, mode='rank')
    ym = datetime.today().strftime('%Y-%m')
    try:
        sb_below = bool(get_spy_timing_map(10).get(ym, False))
    except Exception:
        sb_below = False
    try:
        m4 = bool(get_multi4_cond1_map().get(ym, False))
    except Exception:
        m4 = False
    stop = sb_below or m4
    reason = " · ".join([x for x in [("SPY 이탈" if sb_below else ""), ("멀티4" if m4 else "")] if x]) or "안전"
    rc = '이번달수익률' if '이번달수익률' in picks.columns else '12-1개월(%)'
    rows = [(r['종목코드'], r['종목명'], r.get(rc)) for _, r in picks.head(10).iterrows()]
    allr = [x[2] for x in rows if pd.notna(x[2])]
    avg = float(np.mean(allr)) if allr else 0.0
    refdate = None
    try:
        from utils.data_loader import load_daily_data
        dfd = load_daily_data('momentum_data_daily_usa500.csv')
        if dfd is not None and not dfd.empty and '기준일' in dfd.columns:
            refdate = str(dfd['기준일'].iloc[0])
    except Exception:
        refdate = None
    return {'stop': stop, 'reason': reason, 'avg': avg, 'rows': rows, 'refdate': refdate}


@st.cache_data(ttl=1800, show_spinner=False)
def _snowball_status():
    from utils import snowball as sb
    prices = sb.load_monthly_prices(); div = sb.load_dividend_yield()
    ko = sb.load_ko_prices(); pen = sb.load_pen_prices()
    sso = sb.load_ssopen_prices(); mam = sb.load_mamtax_prices()

    def last(sig):
        if 'defensive' in sig.columns:
            sig = sig[sig['defensive'].notna()]
        return sig.iloc[-1] if len(sig) else None

    defs = [
        ("🇺🇸 또 메리츠", lambda: sb.compute_signals(prices, div), None),
        ("🇺🇸 맘 삼성", lambda: sb.compute_signals_samsung(prices), None),
        ("🇺🇸 쏘 삼성", lambda: sb.compute_signals_so(prices), None),
        ("🇰🇷 또 ISA", lambda: sb.compute_signals_ko(ko), sb.KO_TICKER_NAMES.get),
        ("🇰🇷 또 연금", lambda: sb.compute_signals_pension(pen), sb.PEN_TICKER_NAMES.get),
        ("🇰🇷 쏘 연금", lambda: sb.compute_signals_ssopen(sso, prices), sb.SSOPEN_TICKER_NAMES.get),
        ("🇰🇷 맘 비과세", lambda: sb.compute_signals_mamtax(mam, prices), sb.mamtax_live_name),
    ]
    out = []
    refmonth = None
    for nm, fn, name_fn in defs:
        try:
            l = last(fn())
            if l is not None and refmonth is None:
                refmonth = str(l.name)[:7]
            defensive = bool(l.get('defensive'))
            held = l.get('hold')
            if not isinstance(held, str) or not held.strip():
                h = l.get('holds'); items = list(h) if isinstance(h, (list, tuple, dict)) else []
                held = " · ".join((str(name_fn(t)) if name_fn else str(t)) for t in items) if items else '-'
        except Exception:
            defensive, held = None, '-'
        out.append((nm, defensive, held))
    return out, refmonth


@st.cache_data(ttl=120, show_spinner=False)
def _smallcap_status():
    _SHEET = "https://docs.google.com/spreadsheets/d/1XTroUdH7iKN40dQSrSjz3nsZ1l1k2mr5skXSzlEfl7Y/edit"
    import json, gspread, FinanceDataReader as fdr
    from google.oauth2.service_account import Credentials
    from concurrent.futures import ThreadPoolExecutor, as_completed
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    client = gspread.authorize(Credentials.from_service_account_info(json.loads(st.secrets["google_credentials"]), scopes=scopes))
    sheet = client.open_by_url(_SHEET)

    def load(ws_name):
        try:
            data = sheet.worksheet(ws_name).get_all_values()
            if len(data) > 1:
                df = pd.DataFrame(data[1:], columns=data[0]); df.columns = df.columns.str.strip()
                df['종목코드'] = df['종목코드'].apply(lambda x: str(int(float(str(x).strip()))).zfill(6) if str(x).strip() else "")
                df = df[df['종목코드'] != ""]
                for c in ['매수단가', '수량']:
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(r'[^0-9.-]', '', regex=True), errors='coerce').fillna(0)
                return df[['종목코드', '매수단가', '수량']]
        except Exception:
            pass
        return pd.DataFrame(columns=['종목코드', '매수단가', '수량'])

    ports = {"또": load("ddo"), "쏘": load("sso"), "맘": load("mom")}
    tickers = sorted({t for d in ports.values() for t in d['종목코드'].tolist()})
    px = {}

    def one(t):
        c = 0
        try:
            d = fdr.DataReader(str(t).zfill(6), datetime.today() - timedelta(days=12))
            if not d.empty:
                c = int(d['Close'].iloc[-1])
        except Exception:
            pass
        return t, c
    with ThreadPoolExecutor(max_workers=30) as ex:
        for f in as_completed([ex.submit(one, t) for t in tickers]):
            t, c = f.result(); px[t] = c

    refdate = None
    try:
        idx = fdr.DataReader('KS11', datetime.today() - timedelta(days=12))
        if not idx.empty:
            refdate = str(idx.index[-1].date())
    except Exception:
        refdate = None

    res, tbuy, tval = [], 0, 0
    for nm, df in ports.items():
        buy = val = 0
        if not df.empty:
            df = df.copy(); df['c'] = df['종목코드'].map(lambda x: px.get(x, 0))
            buy = float((df['매수단가'] * df['수량']).sum()); val = float((df['c'] * df['수량']).sum())
        res.append((nm, (val - buy) / buy * 100 if buy else 0.0, val - buy)); tbuy += buy; tval += val
    res.append(("합계", (tval - tbuy) / tbuy * 100 if tbuy else 0.0, tval - tbuy))
    return res, refdate


# ══════════════ 렌더 ══════════════
def render_kospi():
    d = _kospi_status()
    if d is None:
        _header(PAGE_KOSPI, "🇰🇷 KOSPI200 모멘텀"); st.info("일별 데이터 없음"); return
    _rd = f"📅 수익률 기준일 {d['refdate']}" if d.get('refdate') else None
    _header(PAGE_KOSPI, "🇰🇷 KOSPI200 모멘텀", _badge(d['stop'], d['reason']), refdate=_rd)
    if d['stop']:
        st.markdown("<div class='dim' style='font-size:0.88rem; padding:6px 0;'>방어 국면 — 현금(또는 금) 보유</div>", unsafe_allow_html=True)
        return
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='sect-h' style='color:#FCA5A5;'>🔥 퍼펙트 상승 (6)"
                    f"<span class='avg-chip'>평균 {_fmt(d['avg'])}</span></div>" + _tbl(d['perf']), unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='sect-h' style='color:#FCD34D;'>🐎 달리는 말 (2)</div>" + _tbl(d['spec']), unsafe_allow_html=True)


def render_usa():
    d = _usa_status()
    if d is None:
        _header(PAGE_USA, "🇺🇸 USA500 모멘텀"); st.info("데이터 없음"); return
    _rd = f"📅 수익률 기준일 {d['refdate']}" if d.get('refdate') else None
    _header(PAGE_USA, "🇺🇸 USA500 모멘텀", _badge(d['stop'], d['reason']), refdate=_rd)
    if d['stop']:
        st.markdown("<div class='dim' style='font-size:0.88rem; padding:6px 0;'>방어 국면 — 현금 보유</div>", unsafe_allow_html=True)
        return
    st.markdown(f"<div class='sect-h' style='color:#93C5FD;'>🎯 3·6·12 교집합 상위 10"
                f"<span class='avg-chip'>평균 {_fmt(d['avg'])}</span></div>" + _tbl(d['rows']), unsafe_allow_html=True)


def render_snowball():
    rows, refmonth = _snowball_status()
    _rd = f"📅 {refmonth} 월말 기준" if refmonth else None
    _header(PAGE_SNOW, "❄️ 스노우볼 포트", refdate=_rd)
    html = ""
    for nm, defensive, held in rows:
        if defensive is None:
            html += f"<div class='strat-row'><span class='strat-name'>{nm}</span><span class='strat-hold'>-</span></div>"; continue
        mode = ("<span style='color:#F87171;font-weight:800;'>🛡️방어</span>" if defensive
                else "<span style='color:#34D399;font-weight:800;'>⚔️공격</span>")
        html += (f"<div class='strat-row'><span class='strat-name'><b>{nm}</b> &nbsp;{mode}</span>"
                 f"<span class='strat-hold'>{held}</span></div>")
    st.markdown(html, unsafe_allow_html=True)


def render_smallcap():
    data, refdate = _smallcap_status()
    _rd = f"📅 한국장 마감 {refdate}" if refdate else None
    _header(PAGE_SMALL, "💼 내 소형주 퀀트 포트", refdate=_rd)
    rows = ""
    for i, (nm, pct, prof) in enumerate(data):
        top = "border-top:2px solid #2a3140;" if nm == "합계" else ""
        rows += (f"<tr style='{top}'><td><b>{nm}</b></td><td style='text-align:right;'>{_fmt(pct)}</td>"
                 f"<td style='text-align:right;' class='{'pos' if prof>0 else 'neg' if prof<0 else 'dim'}'>₩{int(prof):,}</td></tr>")
    st.markdown("<div class='mini' style='margin-top:6px;'><table>"
                "<tr><th>포트폴리오</th><th style='text-align:right;'>총수익률</th><th style='text-align:right;'>현재수익</th></tr>"
                + rows + "</table></div>", unsafe_allow_html=True)


def _safe(fn, title):
    with st.container(border=True):
        try:
            fn()
        except Exception as e:
            st.markdown(f"<div style='font-weight:800;'>{title}</div>", unsafe_allow_html=True)
            st.caption(f"⚠️ 로드 실패: {type(e).__name__} — {str(e)[:80]}")


# 위: KOSPI200 | USA500
r1 = st.columns(2, gap="medium")
with r1[0]:
    _safe(render_kospi, "🇰🇷 KOSPI200 모멘텀")
with r1[1]:
    _safe(render_usa, "🇺🇸 USA500 모멘텀")

st.write("")

# 아래: 스노우볼 | 소형주
r2 = st.columns(2, gap="medium")
with r2[0]:
    _safe(render_snowball, "❄️ 스노우볼 포트")
with r2[1]:
    _safe(render_smallcap, "💼 내 소형주 퀀트 포트")
