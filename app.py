import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="퀀트 종합 대시보드", layout="wide", page_icon="📊")

# ──────────────────────────────────────────────────────────
# 공통 스타일 (한눈에 보이도록 컴팩트)
# ──────────────────────────────────────────────────────────
st.markdown("""
<style>
.block-container { padding-top: 1.2rem !important; padding-bottom: 0.5rem !important; }
.dash-card { background:#161a23; border:1px solid #262c39; border-radius:12px;
             padding:12px 14px; height:100%; }
.dash-h { font-size:1.05rem; font-weight:800; margin:0 0 6px 0; color:#E5E7EB;
          display:flex; align-items:center; gap:6px; }
.badge-on  { background:#10352410; color:#34D399; border:1px solid #34D39955;
             padding:2px 10px; border-radius:6px; font-weight:900; font-size:0.85rem; }
.badge-off { background:#3b101010; color:#F87171; border:1px solid #F8717155;
             padding:2px 10px; border-radius:6px; font-weight:900; font-size:0.85rem; }
.mini table { width:100%; border-collapse:collapse; font-size:0.8rem; }
.mini th { color:#9CA3AF; text-align:left; padding:2px 6px; font-weight:600;
           border-bottom:1px solid #262c39; }
.mini td { padding:2px 6px; border-bottom:1px solid #1c212b; color:#D1D5DB; }
.pos { color:#F87171; font-weight:700; } .neg { color:#60A5FA; font-weight:700; }
.dim { color:#6B7280; }
.strat-row { display:flex; justify-content:space-between; align-items:center;
             padding:3px 4px; border-bottom:1px solid #1c212b; font-size:0.82rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h2 style='margin:0 0 10px 0;'>📊 퀀트 종합 대시보드 "
            "<span style='font-size:0.9rem; color:#6B7280; font-weight:500;'>· 4개 전략 현재 상태 한눈에</span></h2>",
            unsafe_allow_html=True)


def _fmt_pct(v):
    try:
        v = float(v)
        cls = 'pos' if v > 0 else ('neg' if v < 0 else 'dim')
        return f"<span class='{cls}'>{v:+.1f}%</span>"
    except Exception:
        return "<span class='dim'>-</span>"


def _rows_html(df, code_col, name_col, ret_col, n):
    out = "<div class='mini'><table><tr><th>티커</th><th>종목명</th><th>수익률</th></tr>"
    for _, r in df.head(n).iterrows():
        out += (f"<tr><td class='dim'>{r.get(code_col,'')}</td>"
                f"<td>{r.get(name_col,'')}</td><td>{_fmt_pct(r.get(ret_col))}</td></tr>")
    out += "</table></div>"
    return out


# ══════════════════════════════════════════════════════════
# ① KOSPI200 — 최종판단 + 퍼펙트상승 6 · 달리는말 2
# ══════════════════════════════════════════════════════════
def render_kospi():
    from utils.data_loader import load_daily_data
    from utils.calculator import get_kospi_ma_all, get_strategy_stocks_korea

    df_daily = load_daily_data()
    if df_daily is None or df_daily.empty:
        st.info("KOSPI200 일별 데이터 없음")
        return
    safe_date = datetime.today().strftime('%Y-%m-%d')
    try:
        kospi_curr, kospi_mas = get_kospi_ma_all(safe_date)
    except Exception:
        kospi_curr, kospi_mas = 0, {}
    df_korea, df_perf, df_spec = get_strategy_stocks_korea(df_daily)
    neg_1m = int((df_korea['1개월(%)'] < 0).sum()) if '1개월(%)' in df_korea else 0
    neg_3m = int((df_korea['3개월(%)'] < 0).sum()) if '3개월(%)' in df_korea else 0
    is_bad = (neg_1m >= 100) and (neg_3m >= 100)
    is_below = (kospi_curr > 0) and (kospi_curr < kospi_mas.get(6, 0))
    stop = is_bad or is_below
    reason = ("하락장 " if is_bad else "") + ("6개월선 이탈" if is_below else "")
    if not stop:
        reason = "안전"

    badge = (f"<span class='badge-off'>🛑 투자 중지</span>" if stop
             else f"<span class='badge-on'>✅ 투자 진행</span>")
    st.markdown(f"<div class='dash-h'>🇰🇷 KOSPI200 모멘텀 &nbsp; {badge} "
                f"<span class='dim' style='font-size:0.78rem;'>({reason})</span></div>",
                unsafe_allow_html=True)

    ret_col = '이번달수익률' if '이번달수익률' in df_perf.columns else '1개월(%)'
    if stop:
        st.markdown("<div class='dim' style='font-size:0.85rem;'>방어 국면 — 현금(또는 금) 보유</div>",
                    unsafe_allow_html=True)
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div style='font-size:0.82rem; font-weight:700; color:#FCA5A5;'>🔥 퍼펙트 상승 (6)</div>"
                        + _rows_html(df_perf, '종목코드', '종목명', ret_col, 6), unsafe_allow_html=True)
        with c2:
            st.markdown("<div style='font-size:0.82rem; font-weight:700; color:#FCD34D;'>🐎 달리는 말 (2)</div>"
                        + _rows_html(df_spec, '종목코드', '종목명', ret_col, 2), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# ② USA500 — 최종판단 + 3중교집합 상위 10
# ══════════════════════════════════════════════════════════
def render_usa():
    from utils.data_loader import load_archive_data, get_folder_hash
    from utils.us_helpers import (preprocess_us_data, get_triple_momentum_us,
                                  get_spy_timing_map, get_multi4_cond1_map)

    df_raw = load_archive_data("archive_usa", get_folder_hash("archive_usa"))
    if df_raw is None or df_raw.empty:
        st.info("USA500 데이터 없음")
        return
    df = preprocess_us_data(df_raw, is_daily=False)
    latest = sorted(df['투자월'].dropna().unique())[-1]
    df_m = df[df['투자월'] == latest].copy()
    picks = get_triple_momentum_us(df_m, cutoff=100, mode='rank')

    # 현재(다음 투자월) 방어 판단: SPY 10개월선 이탈 OR 멀티4
    cur_ym = datetime.today().strftime('%Y-%m')
    try:
        spy_below = bool(get_spy_timing_map(10).get(cur_ym, False))
    except Exception:
        spy_below = False
    try:
        is_m4 = bool(get_multi4_cond1_map().get(cur_ym, False))
    except Exception:
        is_m4 = False
    stop = spy_below or is_m4
    reason = " · ".join([x for x in [("SPY 이탈" if spy_below else ""), ("멀티4" if is_m4 else "")] if x]) or "안전"

    badge = (f"<span class='badge-off'>🛑 투자 중지</span>" if stop
             else f"<span class='badge-on'>✅ 투자 진행</span>")
    st.markdown(f"<div class='dash-h'>🇺🇸 USA500 모멘텀 &nbsp; {badge} "
                f"<span class='dim' style='font-size:0.78rem;'>({reason})</span></div>",
                unsafe_allow_html=True)

    if stop:
        st.markdown("<div class='dim' style='font-size:0.85rem;'>방어 국면 — 현금 보유</div>",
                    unsafe_allow_html=True)
    else:
        ret_col = '이번달수익률' if '이번달수익률' in picks.columns else '12-1개월(%)'
        st.markdown("<div style='font-size:0.82rem; font-weight:700; color:#93C5FD;'>🎯 3·6·12 교집합 상위 10</div>"
                    + _rows_html(picks, '종목코드', '종목명', ret_col, 10), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# ③ 내 소형주 퀀트 포트 — 성과 요약 (Google Sheets 연동)
# ══════════════════════════════════════════════════════════
_SHEET_URL = "https://docs.google.com/spreadsheets/d/1XTroUdH7iKN40dQSrSjz3nsZ1l1k2mr5skXSzlEfl7Y/edit"


@st.cache_resource
def _gs_client():
    import json, gspread
    from google.oauth2.service_account import Credentials
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(json.loads(st.secrets["google_credentials"]), scopes=scopes)
    return gspread.authorize(creds)


def _load_config():
    cfg = {"start_ddo": 0, "start_sso": 0, "start_mom": 0}
    try:
        ws = _gs_client().open_by_url(_SHEET_URL).worksheet("Config")
        for row in ws.get_all_values()[1:]:
            k = str(row[0]).strip()
            if k in cfg and row[1]:
                cfg[k] = int(float(str(row[1]).replace(',', '').strip()))
    except Exception:
        pass
    return cfg


def _load_port(ws_name):
    try:
        ws = _gs_client().open_by_url(_SHEET_URL).worksheet(ws_name)
        data = ws.get_all_values()
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


@st.cache_data(ttl=60, show_spinner=False)
def _prices(tickers):
    import FinanceDataReader as fdr
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out = {}
    if not tickers:
        return out

    def one(t):
        code = str(t).zfill(6); c = p = 0
        try:
            d = fdr.DataReader(code, datetime.today() - timedelta(days=12))
            if not d.empty:
                c = int(d['Close'].iloc[-1]); p = int(d['Close'].iloc[-2]) if len(d) > 1 else c
        except Exception:
            pass
        return t, c, p
    with ThreadPoolExecutor(max_workers=30) as ex:
        for f in as_completed([ex.submit(one, t) for t in tickers]):
            t, c, p = f.result(); out[t] = {'curr': c, 'prev': p}
    return out


def render_smallcap():
    ports = {"또": _load_port("ddo"), "쏘": _load_port("sso"), "맘": _load_port("mom")}
    cfg = _load_config()
    all_t = tuple(sorted({t for d in ports.values() for t in d['종목코드'].tolist()}))
    px = _prices(all_t)

    st.markdown("<div class='dash-h'>💼 내 소형주 퀀트 포트 "
                "<span class='dim' style='font-size:0.78rem;'>(성과 요약)</span></div>",
                unsafe_allow_html=True)

    rows, tot_buy, tot_val = "", 0, 0
    key_map = {"또": "start_ddo", "쏘": "start_sso", "맘": "start_mom"}
    for nm, df in ports.items():
        buy = val = 0
        if not df.empty:
            df = df.copy()
            df['c'] = df['종목코드'].map(lambda x: px.get(x, {}).get('curr', 0))
            buy = float((df['매수단가'] * df['수량']).sum())
            val = float((df['c'] * df['수량']).sum())
        prof = val - buy
        pct = (prof / buy * 100) if buy else 0.0
        tot_buy += buy; tot_val += val
        rows += (f"<tr><td><b>{nm}</b></td><td>{_fmt_pct(pct)}</td>"
                 f"<td class='{'pos' if prof>0 else 'neg' if prof<0 else 'dim'}'>₩{int(prof):,}</td></tr>")
    tprof = tot_val - tot_buy
    tpct = (tprof / tot_buy * 100) if tot_buy else 0.0
    rows += (f"<tr style='border-top:1px solid #333;'><td><b>합계</b></td><td>{_fmt_pct(tpct)}</td>"
             f"<td class='{'pos' if tprof>0 else 'neg' if tprof<0 else 'dim'}'>₩{int(tprof):,}</td></tr>")
    st.markdown("<div class='mini'><table><tr><th>포트폴리오</th><th>총수익률</th><th>현재수익</th></tr>"
                + rows + "</table></div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# ④ 스노우볼 포트 — 7개 전략 현재 모드 + 보유
# ══════════════════════════════════════════════════════════
def render_snowball():
    from utils import snowball as sb

    prices = sb.load_monthly_prices(); div = sb.load_dividend_yield()
    ko = sb.load_ko_prices(); pen = sb.load_pen_prices()
    sso = sb.load_ssopen_prices(); mam = sb.load_mamtax_prices()

    def _last(sig):
        if 'defensive' in sig.columns:
            sig = sig[sig['defensive'].notna()]
        return sig.iloc[-1] if len(sig) else None

    strat_defs = [
        ("또 메리츠", lambda: sb.compute_signals(prices, div), None),
        ("맘 삼성", lambda: sb.compute_signals_samsung(prices), None),
        ("쏘 삼성", lambda: sb.compute_signals_so(prices), None),
        ("또 ISA", lambda: sb.compute_signals_ko(ko), sb.KO_TICKER_NAMES.get),
        ("또 연금", lambda: sb.compute_signals_pension(pen), sb.PEN_TICKER_NAMES.get),
        ("쏘 연금", lambda: sb.compute_signals_ssopen(sso, prices), sb.SSOPEN_TICKER_NAMES.get),
        ("맘 비과세", lambda: sb.compute_signals_mamtax(mam, prices), sb.mamtax_live_name),
    ]

    st.markdown("<div class='dash-h'>❄️ 스노우볼 포트 "
                "<span class='dim' style='font-size:0.78rem;'>(7전략 현재 모드·보유)</span></div>",
                unsafe_allow_html=True)

    html = ""
    for nm, fn, name_fn in strat_defs:
        try:
            last = _last(fn())
        except Exception:
            last = None
        if last is None:
            html += f"<div class='strat-row'><span>{nm}</span><span class='dim'>-</span></div>"
            continue
        defensive = bool(last.get('defensive'))
        held = last.get('hold')
        if not isinstance(held, str) or not held.strip():
            h = last.get('holds')
            items = list(h) if isinstance(h, (list, tuple, dict)) else []
            held = " · ".join((str(name_fn(t)) if name_fn else str(t)) for t in items) if items else '-'
        mode = ("<span style='color:#F87171;font-weight:800;'>🛡️방어</span>" if defensive
                else "<span style='color:#34D399;font-weight:800;'>⚔️공격</span>")
        html += (f"<div class='strat-row'><span><b>{nm}</b> &nbsp;{mode}</span>"
                 f"<span class='dim' style='text-align:right; max-width:58%;'>{held}</span></div>")
    st.markdown(html, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────
# 2×2 배치 (스크롤 없이 한눈에)
# ──────────────────────────────────────────────────────────
def _safe(fn, title):
    with st.container(border=True):
        try:
            fn()
        except Exception as e:
            st.markdown(f"<div class='dash-h'>{title}</div>", unsafe_allow_html=True)
            st.caption(f"⚠️ 로드 실패: {type(e).__name__} — {str(e)[:80]}")


r1 = st.columns(2, gap="small")
with r1[0]:
    _safe(render_kospi, "🇰🇷 KOSPI200 모멘텀")
with r1[1]:
    _safe(render_usa, "🇺🇸 USA500 모멘텀")

st.write("")
r2 = st.columns(2, gap="small")
with r2[0]:
    _safe(render_smallcap, "💼 내 소형주 퀀트 포트")
with r2[1]:
    _safe(render_snowball, "❄️ 스노우볼 포트")

st.caption("👈 좌측 메뉴에서 각 전략의 상세 페이지로 이동할 수 있어요.")
