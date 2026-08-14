import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="퀀트 종합 대시보드", layout="wide", page_icon="📊")

st.markdown("""
<style>
.block-container { padding-top: 2.6rem !important; padding-bottom: 1rem !important; }
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

st.markdown("<h2 style='margin:0 0 10px 0;'>📊 퀀트 종합 대시보드 "
            "<span style='font-size:0.9rem; color:#6B7280; font-weight:500;'>· 4개 전략 현재 상태 한눈에</span></h2>",
            unsafe_allow_html=True)

PAGE_KOSPI = "pages/1_🇰🇷_KOSPI200_모멘텀.py"
PAGE_USA = "pages/4_🇺🇸_USA500_모멘텀.py"
PAGE_SMALL = "pages/5_내 소형주 퀀트 포트.py"
PAGE_SNOW = "pages/6 ❄️ 스노우볼 포트.py"

# USA500 전략 매수 순위 (12-1 정렬 기준).
# pages/4_🇺🇸_USA500_모멘텀.py의 STRAT_RANK_START/END와 반드시 일치시킨다 —
# 홈 요약과 상세 페이지가 같은 종목을 보여줘야 한다.
USA_RANK_START = 3
USA_RANK_END = 8


def _fmt(v):
    try:
        v = float(v); cls = 'pos' if v > 0 else ('neg' if v < 0 else 'dim')
        return f"<span class='{cls}'>{v:+.2f}%</span>"
    except Exception:
        return "<span class='dim'>-</span>"


def _tbl(rows):
    out = "<div class='mini'><table><tr><th>티커</th><th>종목명</th><th style='text-align:right;'>수익률</th></tr>"
    for code, name, ret in rows:
        out += (f"<tr><td class='dim'>{code}</td><td>{name}</td>"
                f"<td style='text-align:right;'>{_fmt(ret)}</td></tr>")
    return out + "</table></div>"


def _header(path, title, badge=None, refdate=None):
    c1, c2, c3 = st.columns([2.3, 2.0, 1.7], vertical_alignment="center")
    with c1:
        st.page_link(path, label=title)
    with c2:
        if refdate:
            st.markdown(f"<div style='font-size:0.75rem; color:#6B7280; white-space:nowrap;'>{refdate}</div>",
                        unsafe_allow_html=True)
    with c3:
        if badge:
            st.markdown(f"<div style='text-align:right;'>{badge}</div>", unsafe_allow_html=True)


def _badge(stop, reason):
    b = (f"<span class='badge-off'>🛑 투자 중지</span>" if stop else f"<span class='badge-on'>✅ 투자 진행</span>")
    return b + f" <span class='dim' style='font-size:0.78rem;'>({reason})</span>"


# ══════════════ 계산부 (캐시로 재로딩 가속) ══════════════
@st.cache_data(ttl=1800, show_spinner=False)
def _kospi_status():
    from utils.data_loader import load_daily_data, load_archive_data, get_folder_hash
    from utils.calculator import get_strategy_stocks_korea, get_korea_market_status

    # 선정 종목 · 투자/중지 판정 모두 '월간 아카이브 최신 투자월'(저번달 말 선정) 기준이다.
    # 판정은 공통 함수 get_korea_market_status로 계산 → KOSPI200 페이지 '월별 상세 분석'(탭1)
    # 최신 달과 정확히 같은 결과가 나온다. (데일리 순위 탭2의 '오늘의 시장 상태'와는 성격이 다르다.
    # 이 판정은 저번달 말에 정해져 한 달 내내 고정이며, 매일 바뀌지 않는다.)
    dm = load_archive_data("archive_kospi", get_folder_hash("archive_kospi"))
    if dm is None or dm.empty:
        return None
    dm['종목코드'] = dm['종목코드'].astype(str).str.zfill(6)
    dm = dm[dm['종목코드'].str.endswith('0')].copy()
    for col in ['시가총액', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']:
        if col in dm.columns:
            dm[col] = pd.to_numeric(dm[col], errors='coerce').fillna(0)
    latest_m = sorted(dm['투자월'].dropna().unique())[-1]
    dmm = dm[dm['투자월'] == latest_m].copy()

    mkt = get_korea_market_status(dmm)
    stop = bool(mkt['stop']) if mkt else False
    reason = mkt['reason'] if mkt else "안전"

    _, dp, ds = get_strategy_stocks_korea(dmm)
    rc = '이번달수익률' if '이번달수익률' in dp.columns else '1개월(%)'
    perf = [(r['종목코드'], r['종목명'], r.get(rc)) for _, r in dp.head(6).iterrows()]
    spec = [(r['종목코드'], r['종목명'], r.get(rc)) for _, r in ds.head(2).iterrows()]
    perf_r = [x[2] for x in perf if pd.notna(x[2])]
    spec_r = [x[2] for x in spec if pd.notna(x[2])]
    avg_p = float(np.mean(perf_r)) if perf_r else 0.0
    avg_s = float(np.mean(spec_r)) if spec_r else 0.0
    avg = (avg_p + avg_s) / 2   # 앙상블(50:50)

    # 수익률(이번달수익률) 신선도 표시용 — 데일리 로봇이 매일 갱신하는 기준일
    df_daily = load_daily_data()
    refdate = (str(df_daily['기준일'].iloc[0])
               if df_daily is not None and not df_daily.empty and '기준일' in df_daily.columns
               else None)
    return {'stop': stop, 'reason': reason, 'avg': avg, 'avg_p': avg_p, 'avg_s': avg_s,
            'perf': perf, 'spec': spec, 'refdate': refdate, 'month': latest_m}


@st.cache_data(ttl=1800, show_spinner=False)
def _usa_status():
    from utils.data_loader import get_folder_hash
    from utils.us_helpers import load_us_master, get_triple_momentum_us, get_usa_market_status
    # pages/4 와 같은 캐시 항목을 공유한다 (홈 → USA500 페이지 이동 시 재계산 없음)
    df = load_us_master("archive_usa", get_folder_hash("archive_usa"))
    if df is None or df.empty:
        return None
    latest = sorted(df['투자월'].dropna().unique())[-1]
    df_month = df[df['투자월'] == latest].copy()
    picks = get_triple_momentum_us(df_month, cutoff=100, mode='rank')

    # 투자/중지 판정은 공통 함수로 계산 → USA500 페이지 '월별 상세 분석'(탭1) 최신 달과 동일.
    # (기존엔 홈만 SPY 월봉 10개월선을 봐서, 페이지 일봉 240일선/백테스트 12개월선과 어긋났다.)
    mkt = get_usa_market_status(df_month)
    stop = bool(mkt['stop']) if mkt else False
    reason = mkt['reason'] if mkt else "안전"
    rc = '이번달수익률' if '이번달수익률' in picks.columns else '12-1개월(%)'
    # 전략: 3·6·12 교집합 → 12-1 내림차순 → STRAT_RANK_START~END위 매수 (상세 페이지와 동일)
    picks_pick = picks.iloc[USA_RANK_START - 1:USA_RANK_END]
    rows = [(r['종목코드'], r['종목명'], r.get(rc)) for _, r in picks_pick.iterrows()]
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
        """'현재 달' = 보유 종목이 정해진 마지막 달. pages/6의 각 render_*와 같은 기준이다.

        ⚠️ 예전엔 defensive가 채워진 마지막 달을 골랐다. 그러면 방어/공격 판정은 났는데
           보유가 안 정해진 달(워밍업 구간, 또는 신규 ETF의 CSV를 로봇이 아직 안 만든 경우)에
           홈은 그 달을, 페이지는 그 전 달을 '현재'라고 말해 두 화면이 어긋난다.
           hold(표시용 문자열)와 holds(티커 리스트)는 값이 있는 행이 서로 같음을 확인했고,
           페이지도 전략에 따라 둘 중 있는 쪽을 쓴다.
        """
        col = 'hold' if 'hold' in sig.columns else ('holds' if 'holds' in sig.columns else None)
        if col is not None:
            sig = sig[sig[col].notna()]
        elif 'defensive' in sig.columns:
            sig = sig[sig['defensive'].notna()]
        return sig.iloc[-1] if len(sig) else None

    # ※ 맘 삼성은 2026-08 폐지 (레버리지 ETF의 변동성 끌림으로 지배당하는 전략).
    #   삼성증권 계좌는 쏘 삼성 하나로 합쳐 '맘·쏘 삼성'으로 운용한다.
    defs = [
        ("🇺🇸 또 메리츠", lambda: sb.compute_signals(prices, div), None),
        ("🇺🇸 맘·쏘 삼성", lambda: sb.compute_signals_so(prices), None),
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


@st.cache_resource(show_spinner=False)
def _gspread_client():
    # 인증 객체는 세션 내내 재사용 (매 새로고침마다 재인증하지 않도록 분리)
    import json, gspread
    from google.oauth2.service_account import Credentials
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    return gspread.authorize(Credentials.from_service_account_info(json.loads(st.secrets["google_credentials"]), scopes=scopes))


def _normalize_code(x):
    """종목코드를 6자리로 맞춘다. (pages/5_내 소형주 퀀트 포트.py의 normalize_code와 동일)

    💡 우선주·전환우선주는 코드에 알파벳이 섞인다 (00104K, 37550K, 37550L).
       float() 변환은 이런 코드에서 ValueError를 내고, 그게 except에 삼켜져
       소형주 요약이 통째로 0으로 보였다. 숫자 코드 처리는 예전과 같다.
    """
    s = str(x).strip()
    if not s:
        return ""
    try:
        return str(int(float(s))).zfill(6)
    except ValueError:
        return s.zfill(6)


@st.cache_data(ttl=300, show_spinner=False)
def _smallcap_status():
    _SHEET = "https://docs.google.com/spreadsheets/d/1XTroUdH7iKN40dQSrSjz3nsZ1l1k2mr5skXSzlEfl7Y/edit"
    import FinanceDataReader as fdr
    from concurrent.futures import ThreadPoolExecutor, as_completed
    client = _gspread_client()
    sheet = client.open_by_url(_SHEET)

    def load(ws_name):
        try:
            data = sheet.worksheet(ws_name).get_all_values()
            if len(data) > 1:
                df = pd.DataFrame(data[1:], columns=data[0]); df.columns = df.columns.str.strip()
                df['종목코드'] = df['종목코드'].apply(_normalize_code)
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
        now = datetime.now(timezone(timedelta(hours=9)))
        today = now.date()
        idx = fdr.DataReader('KS11', datetime.today() - timedelta(days=12))
        last_dt = idx.index[-1].date() if not idx.empty else None
        trading_now = (now.weekday() < 5) and (9 * 60 <= now.hour * 60 + now.minute <= 15 * 60 + 30)
        if (last_dt is not None and last_dt >= today) or trading_now:
            refdate = f"📊 실시간 {today}"          # 장중 등 → 오늘(실시간)
        elif last_dt is not None:
            refdate = f"📅 한국장 마감 {last_dt}"     # 장 마감/휴장 → 마지막 거래일
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
    ens = f"<span class='avg-chip'>앙상블 평균 {_fmt(d['avg'])}</span>"
    if d['stop']:
        st.markdown(f"<div style='font-size:0.8rem; color:#F87171; padding:2px 0 5px 0;'>"
                    f"🛑 현재 방어(투자중지) — 공격이었다면 담았을 종목 {ens}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='font-size:0.8rem; color:#34D399; padding:2px 0 5px 0;'>"
                    f"⚔️ 이번달 투자 종목 {ens}</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='sect-h' style='color:#FCA5A5;'>🔥 퍼펙트 상승 (6)"
                    f"<span class='avg-chip'>평균 {_fmt(d['avg_p'])}</span></div>" + _tbl(d['perf']), unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='sect-h' style='color:#FCD34D;'>🐎 달리는 말 (2)"
                    f"<span class='avg-chip'>평균 {_fmt(d['avg_s'])}</span></div>" + _tbl(d['spec']), unsafe_allow_html=True)


def render_usa():
    d = _usa_status()
    if d is None:
        _header(PAGE_USA, "🇺🇸 USA500 모멘텀"); st.info("데이터 없음"); return
    _rd = f"📅 수익률 기준일 {d['refdate']}" if d.get('refdate') else None
    _header(PAGE_USA, "🇺🇸 USA500 모멘텀", _badge(d['stop'], d['reason']), refdate=_rd)
    if d['stop']:
        st.markdown("<div class='dim' style='font-size:0.88rem; padding:6px 0;'>방어 국면 — 현금 보유</div>", unsafe_allow_html=True)
        return
    st.markdown(f"<div class='sect-h' style='color:#93C5FD;'>🎯 3·6·12 교집합 {USA_RANK_START}~{USA_RANK_END}위"
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
    _header(PAGE_SMALL, "💼 내 소형주 퀀트 포트", refdate=refdate)
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
