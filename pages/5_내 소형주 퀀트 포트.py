import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import yfinance as yf
import json
import gspread
from google.oauth2.service_account import Credentials
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

# --- [1. 설정 및 경로] ---
st.set_page_config(page_title="내 퀀트 포트폴리오", layout="wide")

# ✅ 선생님의 구글 시트 주소 고정
SHEET_URL = "https://docs.google.com/spreadsheets/d/1XTroUdH7iKN40dQSrSjz3nsZ1l1k2mr5skXSzlEfl7Y/edit"

st.markdown("""
    <style>
    .block-container { padding-top: 2.5rem !important; }
    .main-title { font-size: 1.8rem !important; font-weight: bold; margin-bottom: 1.5rem; }
    .section-title { font-size: 1.6rem !important; font-weight: bold; margin-top: 25px; margin-bottom: 15px; color: #E5E7EB; }
    .stMetric { background-color: rgba(130, 130, 130, 0.1); padding: 15px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); }
    .stTabs [data-baseweb="tab"] { font-size: 18px; font-weight: bold; }
    .summary-table { width: 100%; border-collapse: collapse; text-align: center; font-size: 1.15rem; background-color: #1a1c24; border-radius: 12px; overflow: hidden; margin-top: 10px; }
    .summary-table th { background-color: #2d313e; padding: 15px; color: #9ca3af; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px; }
    .summary-table td { padding: 16px; border-bottom: 1px solid #2d313e; color: #e5e7eb; }
    .highlight-cell { background-color: rgba(255, 255, 255, 0.03); font-size: 1.2rem; }
    .summary-total { background-color: #242834; font-size: 1.3rem; }
    div[data-testid="stForm"] [data-testid="stFormSubmitButton"] button { height: 73px !important; white-space: pre-wrap; line-height: 1.4; font-size: 1.05rem; }
    .val-red-thin { color: #FF3333 !important; font-weight: 500; }
    .val-blue-thin { color: #3399FF !important; font-weight: 500; }
    .val-red { color: #FF3333 !important; font-weight: bold; }
    .val-blue { color: #3399FF !important; font-weight: bold; }
    .val-white { color: #ffffff !important; font-weight: bold; }
    .val-gray { color: #9ca3af !important; font-weight: normal !important; }
    .box-red { background-color: rgba(255, 51, 51, 0.15); color: #FF3333; padding: 6px 14px; border-radius: 8px; border: 1px solid rgba(255, 51, 51, 0.3); font-weight: bold;}
    .box-blue { background-color: rgba(51, 153, 255, 0.15); color: #3399FF; padding: 6px 14px; border-radius: 8px; border: 1px solid rgba(51, 153, 255, 0.3); font-weight: bold;}
    </style>
""", unsafe_allow_html=True)

def parse_krw(val_str, default_val):
    try:
        if isinstance(val_str, str):
            cleaned = ''.join(c for c in val_str if c.isdigit() or c == '-')
            return int(cleaned) if cleaned else default_val
        return int(val_str)
    except: return default_val

# --- [2. 구글 시트 엔진] ---
@st.cache_resource
def get_gspread_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds_info = json.loads(st.secrets["google_credentials"])
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

def load_config_from_gsheet():
    default_cfg = {"start_date": str(datetime.today().date()), "start_ddo": 0, "start_sso": 0, "start_mom": 0}
    try:
        client = get_gspread_client()
        sheet = client.open_by_url(SHEET_URL)
        ws = sheet.worksheet("Config")
        data = ws.get_all_values()
        if len(data) > 1:
            for row in data[1:]:
                k = str(row[0]).strip()
                if k in default_cfg:
                    if k == 'start_date': default_cfg[k] = str(row[1]).strip()
                    else: default_cfg[k] = int(float(str(row[1]).replace(',', '').strip())) if row[1] else 0
    except: pass
    return default_cfg

def save_config_to_gsheet(cfg):
    try:
        client = get_gspread_client()
        sheet = client.open_by_url(SHEET_URL)
        ws = sheet.worksheet("Config")
        ws.clear()
        ws.update(values=[["key", "value"]] + [[k, str(v)] for k, v in cfg.items()], range_name='A1')
    except Exception as e: st.error(f"설정 저장 오류: {e}")

# 💡 [핵심] StockInfo 탭에서 액면가 및 종목 정보 로드
def load_stock_info_from_gsheet():
    info_map = {}
    try:
        client = get_gspread_client()
        sheet = client.open_by_url(SHEET_URL)
        ws = sheet.worksheet("StockInfo")
        data = ws.get_all_records()
        for row in data:
            code = str(row.get('종목코드', '')).strip().zfill(6)
            if code:
                info_map[code] = {
                    '액면가': parse_krw(row.get('액면가', 0), 0),
                    '상장주식수': parse_krw(row.get('상장주식수', 0), 0)
                }
    except: pass
    return info_map

def load_portfolio_from_gsheet(ws_name):
    df_empty = pd.DataFrame(columns=["종목명", "종목코드", "매수단가", "수량"])
    try:
        client = get_gspread_client()
        sheet = client.open_by_url(SHEET_URL)
        ws = sheet.worksheet(ws_name)
        data = ws.get_all_values()
        if len(data) > 1:
            df = pd.DataFrame(data[1:], columns=data[0])
            df.columns = df.columns.str.strip()
            df['종목코드'] = df['종목코드'].apply(lambda x: str(int(float(str(x).strip()))).zfill(6) if str(x).strip() else "")
            df = df[df['종목코드'] != ""]
            for c in ['매수단가', '수량']:
                if c in df.columns: df[c] = pd.to_numeric(df[c].astype(str).str.replace(r'[^0-9.-]', '', regex=True), errors='coerce').fillna(0).astype(int)
            return df[["종목명", "종목코드", "매수단가", "수량"]]
    except: pass
    return df_empty

def save_portfolio_to_gsheet(ws_name, df):
    try:
        client = get_gspread_client()
        sheet = client.open_by_url(SHEET_URL)
        ws = sheet.worksheet(ws_name)
        ws.clear()
        ws.update(values=[df.columns.values.tolist()] + df.fillna("").values.tolist(), range_name='A1')
    except Exception as e: st.error(f"저장 오류: {e}")

# --- [3. 실시간 데이터 수집 엔진] ---
@st.cache_data(ttl=86400, show_spinner=False)
def get_krx_master():
    try:
        df = fdr.StockListing('KRX')
        df['종목코드'] = df['Code'].astype(str).str.zfill(6)
        df['시총_억'] = (df['Marcap'] / 100000000).fillna(0).astype(int)
        return df, df.set_index('종목코드')['시총_억'].to_dict()
    except: return pd.DataFrame(), {}

@st.cache_data(ttl=60, show_spinner=False)
def fetch_multi_prices(tickers):
    if not tickers: return {}
    price_map = {}
    def get_price(t):
        code = str(t).zfill(6)
        c, p = 0, 0
        try:
            df = fdr.DataReader(code, datetime.today() - timedelta(days=12))
            if not df.empty: c, p = int(df['Close'].iloc[-1]), int(df['Close'].iloc[-2]) if len(df) > 1 else int(df['Close'].iloc[-1])
        except: pass
        return t, c, p
    with ThreadPoolExecutor(max_workers=30) as ex:
        for f in as_completed([ex.submit(get_price, t) for t in tickers]):
            t, c, p = f.result(); price_map[t] = {'curr': c, 'prev': p}
    return price_map

# --- [4. 초기화 및 데이터 로드] ---
master_df, live_cap_map = get_krx_master()
gsheet_stock_info = load_stock_info_from_gsheet() # 💡 구글 시트 StockInfo 탭 데이터 로드
search_options = ["🔍 종목 검색"] + ("[" + master_df['종목코드'] + "] " + master_df['Name']).tolist() if not master_df.empty else ["데이터 로드 중..."]

if 'portfolio_config' not in st.session_state:
    st.session_state['portfolio_config'] = load_config_from_gsheet()

for p_key in ["ddo", "sso", "mom"]:
    if f'editor_key_{p_key}' not in st.session_state: st.session_state[f'editor_key_{p_key}'] = 0
    if f'df_{p_key}' not in st.session_state: st.session_state[f'df_{p_key}'] = load_portfolio_from_gsheet(p_key)

all_tickers = set(t for p in ["ddo", "sso", "mom"] for t in st.session_state[f'df_{p}']['종목코드'].tolist())
global_prices = fetch_multi_prices(tuple(sorted(all_tickers)))

# --- [5. 탭 구현 함수] ---
def render_portfolio_tab(port_name, port_key, prices):
    scoreboard = st.container()
    st.markdown("---")
    
    c_add, c_file = st.columns([1.5, 1])
    with c_add:
        with st.expander(f"➕ {port_name} 종목 추가"):
            with st.form(f"add_{port_key}", clear_on_submit=True):
                sel = st.selectbox("종목 검색", options=search_options, key=f"sel_{port_key}")
                c1, c2 = st.columns(2)
                p, q = c1.number_input("매수단가", min_value=0, step=100), c2.number_input("수량", min_value=1, step=1)
                if st.form_submit_button("추가") and sel != search_options[0]:
                    new_row = pd.DataFrame([{"종목명": sel[9:], "종목코드": sel[1:7], "매수단가": int(p), "수량": int(q)}])
                    st.session_state[f'df_{port_key}'] = pd.concat([st.session_state[f'df_{port_key}'], new_row], ignore_index=True)
                    save_portfolio_to_gsheet(port_key, st.session_state[f'df_{port_key}'])
                    st.session_state[f'editor_key_{port_key}'] += 1
                    st.rerun()

    with c_file:
        with st.expander("📂 엑셀 업로드"):
            up_file = st.file_uploader("CSV/XLSX 선택", type=['csv', 'xlsx'], key=f"up_{port_key}")
            if st.button("구글 시트에 반영", key=f"btn_{port_key}") and up_file:
                try:
                    up_file.seek(0)
                    up_df = pd.read_csv(up_file) if up_file.name.endswith('csv') else pd.read_excel(up_file)
                    up_df.columns = up_df.columns.astype(str).str.replace('\ufeff', '', regex=False).str.strip()
                    code_col = [c for c in up_df.columns if '코드' in c][0]
                    up_df = up_df.rename(columns={code_col: '종목코드'}).dropna(subset=['종목코드'])
                    up_df['종목코드'] = up_df['종목코드'].apply(lambda x: str(int(float(str(x).strip()))).zfill(6))
                    if '종목명' not in up_df.columns: up_df['종목명'] = up_df['종목코드'].map(master_df.set_index('종목코드')['Name']).fillna('이름없음')
                    for c in ['매수단가', '수량']:
                        if c in up_df.columns: up_df[c] = pd.to_numeric(up_df[c].astype(str).str.replace(r'[^0-9.-]', '', regex=True), errors='coerce').fillna(0).astype(int)
                        else: up_df[c] = 0
                    final_df = up_df[["종목명", "종목코드", "매수단가", "수량"]].copy()
                    st.session_state[f'df_{port_key}'] = final_df
                    save_portfolio_to_gsheet(port_key, final_df)
                    st.session_state[f'editor_key_{port_key}'] += 1
                    st.rerun()
                except: st.error("파일 형식을 확인해주세요.")

    st.markdown(f"### 📝 {port_name} 편집")
    df_ed = st.data_editor(st.session_state[f'df_{port_key}'], num_rows="dynamic", use_container_width=True, key=f"ed_{port_key}_{st.session_state[f'editor_key_{port_key}']}")
    if st.button("구글 시트에 최종 저장", key=f"sv_{port_key}"):
        st.session_state[f'df_{port_key}'] = df_ed
        save_portfolio_to_gsheet(port_key, df_ed)
        st.session_state[f'editor_key_{port_key}'] += 1
        st.toast(f"✅ {port_name} 구글 시트에 저장 완료!", icon="🚀")
        st.rerun()

    with scoreboard:
        st.markdown(f"### 🚀 {port_name} 실시간 성적표")
        df = st.session_state[f'df_{port_key}'].copy()
        if not df.empty:
            # 💡 [핵심] 시총과 액면가를 시트 정보와 실시간 정보를 결합하여 표시
            df['액면가'] = df['종목코드'].apply(lambda x: gsheet_stock_info.get(x, {}).get('액면가', 0))
            df['현재가'] = df['종목코드'].apply(lambda x: prices.get(x, {}).get('curr', 0))
            
            # 시총 계산: 실시간 데이터 우선, 없으면 (시트 주식수 * 현재가)
            def get_m_cap(code, curr_p):
                cap = live_cap_map.get(code, 0)
                if cap == 0 and code in gsheet_stock_info:
                    shares = gsheet_stock_info[code].get('상장주식수', 0)
                    cap = int((shares * curr_p) / 100000000)
                return cap
            
            df['시총(억)'] = df.apply(lambda r: get_m_cap(r['종목코드'], r['현재가']), axis=1)
            df['전일종가'] = df['종목코드'].apply(lambda x: prices.get(x, {}).get('prev', 0))
            df['전일대비(%)'] = ((df['현재가'] - df['전일종가']) / df['전일종가'] * 100).fillna(0)
            df['평가금액'] = df['현재가'] * df['수량']
            df['매수총액'] = df['매수단가'] * df['수량']
            df['평가손익'] = df['평가금액'] - df['매수총액']
            df['수익률(%)'] = (df['평가손익'] / df['매수총액'] * 100).fillna(0)
            
            t_buy, t_val, t_profit = df['매수총액'].sum(), df['평가금액'].sum(), df['평가손익'].sum()
            t_prev_val = (df['전일종가'] * df['수량']).sum()
            d_diff, d_pct = t_val - t_prev_val, (t_val - t_prev_val) / t_prev_val * 100 if t_prev_val else 0
            
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("💰 총 매수", f"{int(t_buy):,}원"); c2.metric("📈 총 평가액", f"{int(t_val):,}원")
            c3.metric("🌟 오늘 변동액", f"{int(d_diff):,}원", delta=f"{d_pct:.2f}%")
            c4.metric("💸 총 평가손익", f"{int(t_profit):,}원", delta=f"{int(t_profit):,}원")
            c5.metric("📊 총 수익률", f"{(t_profit/t_buy*100) if t_buy > 0 else 0:.2f}%", delta=f"{(t_profit/t_buy*100) if t_buy > 0 else 0:.2f}%")
            
            df['티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)
            
            def style_row(st_df):
                s = pd.DataFrame('', index=st_df.index, columns=st_df.columns)
                for col in ['전일대비(%)', '평가손익', '수익률(%)']:
                    s[col] = st_df[col].apply(lambda x: 'color: #FF3333; font-weight:bold;' if x > 0 else ('color: #3399FF; font-weight:bold;' if x < 0 else ''))
                h_css, w_css = 'background-color: rgba(255, 167, 38, 0.1); color: #FFA726; font-weight:bold;', 'background-color: rgba(255, 0, 0, 0.2); color: #FF3333; font-weight:bold;'
                s['시총(억)'] = st_df['시총(억)'].apply(lambda x: h_css if 0 < x <= 150 else '')
                for i, row in st_df.iterrows():
                    if row['액면가'] > 0 and row['현재가'] < row['액면가']: s.loc[i, ['현재가', '액면가']] = w_css
                    elif 0 < row['현재가'] < 1000: s.loc[i, '현재가'] = h_css
                return s

            st.dataframe(df.style.apply(style_row, axis=None).format({'전일대비(%)':'{:.2f}%','수익률(%)':'{:.2f}%','시총(억)':'{:,}','매수단가':'{:,}','액면가':'{:,}','현재가':'{:,}','평가금액':'{:,}','평가손익':'{:,}'}), 
                         use_container_width=True, hide_index=True,
                         column_order=['티커_L', '종목명_L', '시총(억)', '수량', '매수단가', '액면가', '현재가', '전일대비(%)', '평가금액', '평가손익', '수익률(%)'],
                         column_config={"티커_L": st.column_config.LinkColumn("코드", display_text=r"code=(.+)"), "종목명_L": st.column_config.LinkColumn("종목명", display_text=r"#(.+)")})

# --- [6. 메인 화면] ---
st.markdown('<p class="main-title">💼 내 퀀트 포트폴리오 종합 대시보드</p>', unsafe_allow_html=True)
tabs = st.tabs(["📊 종합 요약", "🌱 또", "🌿 쏘", "🍀 맘", "⚖️ 리밸런싱 계산기"])

with tabs[0]:
    config = st.session_state['portfolio_config']
    total_start = config['start_ddo'] + config['start_sso'] + config['start_mom']
    st.markdown(f"##### ⚙️ 비교 시점 및 시작 수익금 설정 <span style='font-size: 1rem; color: #9ca3af;'>(총 시작금 : {total_start:,}원)</span>", unsafe_allow_html=True)
    with st.form("config_form"):
        c_dt, c_d, c_s, c_m, c_btn = st.columns([1.2, 1, 1, 1, 0.7])
        dt_v = datetime.strptime(config['start_date'], '%Y-%m-%d').date()
        with c_dt: new_date = st.date_input("📅 시작일", value=dt_v)
        # 💡 [해결] 100을 넣으면 저장 후 1,000,000으로 자동 변환 로직 유지
        with c_d: s_ddo = st.text_input("💰 [또] 시작금", value=f"{config['start_ddo']:,}")
        with c_s: s_sso = st.text_input("💰 [쏘] 시작금", value=f"{config['start_sso']:,}")
        with c_m: s_mom = st.text_input("💰 [맘] 시작금", value=f"{config['start_mom']:,}")
        with c_btn: 
            if st.form_submit_button("설정 저장"):
                def smart_p(v):
                    n = parse_krw(v, 0)
                    return n * 10000 if 0 < n < 10000 else n
                new_cfg = {"start_date": str(new_date), "start_ddo": smart_p(s_ddo), "start_sso": smart_p(s_sso), "start_mom": smart_p(s_mom)}
                st.session_state['portfolio_config'] = new_cfg
                save_config_to_gsheet(new_cfg)
                st.toast("✅ 설정 저장 완료!", icon="⚙️"); st.rerun()

    st.markdown('<p class="section-title">🏆 성과 요약</p>', unsafe_allow_html=True)
    summary_list, t_buy_all, t_val_all, t_daily_all, t_prev_all = [], 0, 0, 0, 0
    for p_n, p_k in [("또", "ddo"), ("쏘", "sso"), ("맘", "mom")]:
        df, s_val = st.session_state[f'df_{p_k}'], config[f'start_{p_k}']
        if not df.empty:
            df['c'] = df['종목코드'].apply(lambda x: global_prices.get(x, {}).get('curr', 0))
            df['p'] = df['종목코드'].apply(lambda x: global_prices.get(x, {}).get('prev', 0))
            buy, val, prev = (df['매수단가']*df['수량']).sum(), (df['c']*df['수량']).sum(), (df['p']*df['수량']).sum()
            prof, daily = val - buy, val - prev
            t_buy_all += buy; t_val_all += val; t_daily_all += daily; t_prev_all += prev
            summary_list.append({"name": p_n, "daily": daily, "dp": (daily/prev*100) if prev else 0, "pct": (prof/buy*100) if buy else 0, "prof": prof, "since": prof - s_val})
        else: summary_list.append({"name": p_n, "daily": 0, "dp": 0, "pct": 0, "prof": 0, "since": -s_val})

    html = "<table class='summary-table'><thead><tr><th>포트폴리오</th><th>오늘의 등락</th><th>등락률</th><th>총 수익률</th><th>현재 수익</th><th style='background-color:#3e4452;'>시작일 대비</th></tr></thead><tbody>"
    f_c = lambda v, b=False: (f"box-red" if b and v>0 else "box-blue" if b and v<0 else ("val-red" if v>0 else "val-blue" if v<0 else "val-gray"))
    for r in summary_list:
        html += f"<tr><td><b>{r['name']}</b></td><td class='{f_c(r['daily'])}'>₩{int(r['daily']):,}</td><td>{r['dp']:.2f}%</td><td class='{f_c(r['pct'])}'>{r['pct']:.2f}%</td><td class='{f_c(r['prof'])}'>₩{int(r['prof']):,}</td><td class='highlight-cell'><span class='{f_c(r['since'], True)}'>₩{int(r['since']):,}</span></td></tr>"
    t_p_all = t_val_all - t_buy_all
    html += f"<tr class='summary-total'><td><b>합계</b></td><td class='{f_c(t_daily_all)}'>₩{int(t_daily_all):,}</td><td>{(t_daily_all/t_prev_all*100 if t_prev_all else 0):.2f}%</td><td>{(t_p_all/t_buy_all*100 if t_buy_all else 0):.2f}%</td><td class='{f_c(t_p_all)}'>₩{int(t_p_all):,}</td><td class='highlight-cell'><span style='font-size:1.4rem;' class='{f_c(t_p_all - total_start, True)}'>₩{int(t_p_all - total_start):,}</span></td></tr></tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

with tabs[1]: render_portfolio_tab("또", "ddo", global_prices)
with tabs[2]: render_portfolio_tab("쏘", "sso", global_prices)
with tabs[3]: render_portfolio_tab("맘", "mom", global_prices)

with tabs[4]:
    st.markdown('<p class="section-title">⚖️ 리밸런싱 계산기</p>', unsafe_allow_html=True)
    c_sel, c_up = st.columns([1, 2])
    tgt_p = c_sel.selectbox("🔄 기준 포트폴리오", options=[("또", "ddo"), ("쏘", "sso"), ("맘", "mom")], format_func=lambda x: f"[{x[0]}] 기준")
    up_reb = c_up.file_uploader("목표 엑셀 업로드", type=['csv', 'xlsx'], key="reb_up_gs")
    if up_reb:
        try:
            up_reb.seek(0)
            t_df = pd.read_csv(up_reb) if up_reb.name.endswith('csv') else pd.read_excel(up_reb)
            t_df.columns = t_df.columns.astype(str).str.strip()
            c_col, m_col = [c for c in t_df.columns if '코드' in c][0], [c for c in t_df.columns if '목표' in c][0]
            t_df['종목코드'] = t_df[c_col].apply(lambda x: str(int(float(str(x).strip()))).zfill(6))
            t_df['목표금액'] = pd.to_numeric(t_df[m_col].astype(str).str.replace(r'[^0-9.]', '', regex=True)).fillna(0).astype(int) * 10000
            curr = st.session_state[f'df_{tgt_p[1]}'].copy()
            merged = pd.merge(curr[['종목코드', '수량']], t_df[['종목코드', '목표금액']], on='종목코드', how='outer').fillna(0)
            merged['종목명'] = merged['종목코드'].map(master_df.set_index('종목코드')['Name']).fillna('이름없음')
            p_map = fetch_multi_prices(tuple(merged['종목코드'].tolist()))
            merged['현재가'] = merged['종목코드'].apply(lambda x: p_map.get(x, {}).get('curr', 0))
            merged['현재평가액'] = merged['수량'] * merged['현재가']; merged['차액'] = merged['목표금액'] - merged['현재평가액']
            merged['주문'] = merged.apply(lambda r: "전량매도" if r['목표금액']==0 else ("신규매수" if r['수량']==0 else ("추가매수" if r['차액']>0 else "부분매도")), axis=1)
            merged['주문수량'] = merged.apply(lambda r: r['수량'] if r['주문']=="전량매도" else int(abs(r['차액']) // r['현재가']) if r['현재가']>0 else 0, axis=1)
            merged['예상금액'] = merged.apply(lambda r: r['주문수량']*r['현재가'] * (1 if '매수' in r['주문'] else -1), axis=1)
            buy_s, sell_s = merged[merged['예상금액']>0]['예상금액'].sum(), abs(merged[merged['예상금액']<0]['예상금액'].sum())
            st.markdown(f"**🔵 매도:** `₩{sell_s:,}` | **🔴 매수:** `₩{buy_s:,}` | **💡 잔액:** `₩{sell_s-buy_s:,}` {'잔금' if sell_s-buy_s>=0 else '추가 필요'}")
            st.dataframe(merged[['종목코드','종목명','현재가','수량','현재평가액','목표금액','주문','주문수량','예상금액']].style.format(precision=0), use_container_width=True, hide_index=True)
        except Exception as e: st.error(f"오류: {e}")
