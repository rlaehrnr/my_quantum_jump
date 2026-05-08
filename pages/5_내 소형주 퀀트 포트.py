import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import yfinance as yf
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- [1. 설정 및 경로] ---
st.set_page_config(page_title="내 퀀트 포트폴리오", layout="wide")

# 💡 포트폴리오 전용 폴더 설정
PORT_DIR = 'port'
if not os.path.exists(PORT_DIR):
    os.makedirs(PORT_DIR)
if not os.path.exists('data'):
    os.makedirs('data')

PORT_PATHS = {
    "ddo": f'{PORT_DIR}/port_ddo.csv',
    "sso": f'{PORT_DIR}/port_sso.csv',
    "mom": f'{PORT_DIR}/port_mom.csv'
}
MASTER_TICKER_PATH = 'data/krx_stock_master.csv'
CONFIG_PATH = 'data/portfolio_config.json' 
FACE_VALUE_PATH = 'data/krx_stock_info.csv' 

st.markdown("""
    <style>
    .block-container { padding-top: 2.5rem !important; }
    .main-title { font-size: 1.8rem !important; font-weight: bold; margin-bottom: 1.5rem; }
    .section-title { font-size: 1.6rem !important; font-weight: bold; margin-top: 25px; margin-bottom: 15px; color: #E5E7EB; }
    .stMetric { background-color: rgba(130, 130, 130, 0.1); padding: 15px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); }
    .stTabs [data-baseweb="tab"] { font-size: 18px; font-weight: bold; }
    
    @media (max-width: 768px) {
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            min-width: 45% !important; flex: 1 1 45% !important; margin-bottom: 10px !important;
        }
    }
    
    /* 📊 종합 요약 표 디자인 */
    .summary-table { width: 100%; border-collapse: collapse; text-align: center; font-size: 1.15rem; background-color: #1a1c24; border-radius: 12px; overflow: hidden; margin-top: 10px; }
    .summary-table th { background-color: #2d313e; padding: 15px; color: #9ca3af; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px; }
    .summary-table td { padding: 16px; border-bottom: 1px solid #2d313e; color: #e5e7eb; }
    .highlight-cell { background-color: rgba(255, 255, 255, 0.03); font-size: 1.2rem; }
    .summary-total { background-color: #242834; font-size: 1.3rem; }
    
    /* 설정 저장 버튼 완벽 맞춤 */
    div[data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
        height: 73px !important; margin-top: 0px !important; white-space: pre-wrap; line-height: 1.4; font-size: 1.05rem;
    }
    
    /* 숫자 색상 */
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

# --- [2. 데이터 수집 로직] ---
@st.cache_data(ttl=86400, show_spinner=False)
def get_face_value_map():
    if os.path.exists(FACE_VALUE_PATH):
        try:
            df = pd.read_csv(FACE_VALUE_PATH, dtype={'단축코드': str}, encoding='utf-8-sig')
            df['단축코드'] = df['단축코드'].astype(str).str.zfill(6)
            df['액면가'] = pd.to_numeric(df['액면가'].astype(str).str.replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0)
            return df.set_index('단축코드')['액면가'].to_dict()
        except: pass
    return {}

global_fv_map = get_face_value_map()

@st.cache_data(ttl=86400, show_spinner=False)
def get_stock_master_and_cap():
    if os.path.exists(MASTER_TICKER_PATH):
        try:
            df = pd.read_csv(MASTER_TICKER_PATH, dtype={'종목코드': str}, encoding='utf-8-sig')
            df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
            df['시가총액(억)'] = pd.to_numeric(df['시가총액(억)'].astype(str).str.replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0).astype(int)
            return df, df.set_index('종목코드')['시가총액(억)'].to_dict()
        except: pass
    return pd.DataFrame(), {}

master_df, global_cap_map = get_stock_master_and_cap()
if not master_df.empty: master_df['검색명'] = "[" + master_df['종목코드'] + "] " + master_df.get('종목명', master_df['종목코드'])
search_options = ["🔍 종목 검색"] + master_df['검색명'].tolist() if not master_df.empty else ["검색 데이터 없음"]

@st.cache_data(ttl=60, show_spinner=False)
def fetch_multi_prices(tickers):
    if not tickers: return {}
    price_map = {}
    def get_price(t):
        code_str = str(t).zfill(6) if str(t).isdigit() else str(t)
        curr_val, prev_val = 0, 0
        try:
            df = fdr.DataReader(code_str, datetime.today() - timedelta(days=100))
            if not df.empty:
                curr_val = int(df['Close'].iloc[-1])
                prev_val = int(df['Close'].iloc[-2]) if len(df) >= 2 else curr_val
        except:
            try:
                hist = yf.Ticker(code_str + ".KS").history(period="5d")
                if not hist.empty:
                    curr_val = int(hist['Close'].iloc[-1])
                    prev_val = int(hist['Close'].iloc[-2]) if len(hist) >= 2 else curr_val
            except: pass
        return t, curr_val, prev_val

    with ThreadPoolExecutor(max_workers=30) as executor:
        for f in as_completed([executor.submit(get_price, t) for t in tickers]):
            t, curr, prev = f.result()
            price_map[t] = {'curr': curr, 'prev': prev}
    return price_map

# 💡 CSV에서 포트폴리오와 시작금을 로드 (시작금 열 추가 연동)
def load_portfolio(path):
    df_empty = pd.DataFrame(columns=["종목명", "종목코드", "매수단가", "수량", "시작금"])
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, dtype={'종목코드': str}, encoding='utf-8-sig')
            df = df.dropna(subset=['종목코드'])
            df['종목코드'] = df['종목코드'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(6)
            
            if '종목명' not in df.columns:
                name_map = master_df.set_index('종목코드')['종목명'].to_dict() if not master_df.empty else {}
                df['종목명'] = df['종목코드'].map(name_map).fillna('이름없음')
                
            for c in ['매수단가', '수량', '시작금']:
                if c in df.columns: df[c] = pd.to_numeric(df[c].astype(str).replace(r'[^0-9.-]', '', regex=True), errors='coerce').fillna(0).astype(int)
                else: df[c] = 0
            return df[["종목명", "종목코드", "매수단가", "수량", "시작금"]]
        except: pass
    return df_empty

# 상태 초기화 및 CSV 시작금 덮어쓰기 로직
default_config = {"start_date": str(datetime.today().date()), "start_ddo": 0, "start_sso": 0, "start_mom": 0}
if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            default_config.update(json.load(f))
    except: pass

# CSV에서 최신 시작금 읽어오기 (CSV 우선 적용)
for p_key, path in [("ddo", PORT_PATHS["ddo"]), ("sso", PORT_PATHS["sso"]), ("mom", PORT_PATHS["mom"])]:
    if f'df_{p_key}' not in st.session_state:
        df_loaded = load_portfolio(path)
        st.session_state[f'df_{p_key}'] = df_loaded
        if not df_loaded.empty and '시작금' in df_loaded.columns:
            default_config[f'start_{p_key}'] = int(df_loaded['시작금'].iloc[0])

if 'portfolio_config' not in st.session_state:
    st.session_state['portfolio_config'] = default_config

all_tickers = set(t for p in ["ddo", "sso", "mom"] for t in st.session_state[f'df_{p}']['종목코드'].tolist())
global_prices = fetch_multi_prices(tuple(sorted(all_tickers)))

# --- [3. 개별 포트폴리오 탭 렌더링] ---
def render_portfolio_tab(port_name, port_key, path, prices):
    scoreboard_placeholder = st.container()
    st.markdown("---")
    
    col_add, col_file = st.columns([1.5, 1])
    with col_add:
        with st.expander(f"➕ {port_name} 종목 추가", expanded=False):
            with st.form(f"add_{port_key}", clear_on_submit=True):
                sel = st.selectbox("종목 검색", options=search_options, key=f"sel_{port_key}")
                c1, c2 = st.columns(2)
                p = c1.number_input("매수단가", min_value=0, step=100)
                q = c2.number_input("수량", min_value=1, step=1)
                if st.form_submit_button("추가") and sel != search_options[0]:
                    code, name = sel[1:7], sel[9:]
                    current_start_money = st.session_state['portfolio_config'].get(f'start_{port_key}', 0)
                    new_row = pd.DataFrame([{"종목명": name, "종목코드": code, "매수단가": int(p), "수량": int(q), "시작금": current_start_money}])
                    
                    st.session_state[f'df_{port_key}'] = pd.concat([st.session_state[f'df_{port_key}'], new_row], ignore_index=True)
                    st.session_state[f'df_{port_key}'].to_csv(path, index=False, encoding='utf-8-sig')
                    st.rerun()

    with col_file:
        with st.expander("📂 엑셀 업로드", expanded=False):
            up_file = st.file_uploader("CSV/XLSX", type=['csv', 'xlsx'], key=f"up_{port_key}")
            if up_file and st.button("반영", key=f"btn_{port_key}"):
                try:
                    # 1. 한글 인코딩 방어
                    if up_file.name.endswith('csv'):
                        try:
                            up_df = pd.read_csv(up_file, encoding='utf-8-sig')
                        except UnicodeDecodeError:
                            up_file.seek(0)
                            up_df = pd.read_csv(up_file, encoding='cp949')
                    else:
                        up_df = pd.read_excel(up_file)
                        
                    up_df.columns = up_df.columns.str.strip()
                    
                    # 2. 필수 열 확인 및 빈자리 자동 채우기
                    if '종목코드' not in up_df.columns:
                        st.error("🚨 업로드한 파일에 '종목코드' 열이 없습니다!")
                    else:
                        up_df['종목코드'] = up_df['종목코드'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(6)
                        
                        if '종목명' not in up_df.columns:
                            name_map = master_df.set_index('종목코드')['종목명'].to_dict() if not master_df.empty else {}
                            up_df['종목명'] = up_df['종목코드'].map(name_map).fillna('이름없음')
                            
                        if '매수단가' not in up_df.columns: up_df['매수단가'] = 0
                        if '수량' not in up_df.columns: up_df['수량'] = 0
                        
                        for col in ['매수단가', '수량']:
                            up_df[col] = pd.to_numeric(up_df[col].astype(str).replace(r'[^0-9.-]', '', regex=True), errors='coerce').fillna(0).astype(int)
                            
                        # 누락된 시작금을 설정에서 가져와서 자동으로 꽉 채움
                        up_df['시작금'] = st.session_state['portfolio_config'].get(f'start_{port_key}', 0)
                        
                        # 3. 덮어쓰기 및 리로드
                        st.session_state[f'df_{port_key}'] = up_df[["종목명", "종목코드", "매수단가", "수량", "시작금"]]
                        st.session_state[f'df_{port_key}'].to_csv(path, index=False, encoding='utf-8-sig')
                        st.rerun()
                except Exception as e: 
                    st.error(f"파일 오류가 발생했습니다: {e}")

    st.markdown(f"### 📝 {port_name} 편집")
    clean_df = st.session_state[f'df_{port_key}'][["종목명", "종목코드", "매수단가", "수량"]]
    clean_df.index = range(1, len(clean_df) + 1)

    df_editor = st.data_editor(clean_df, num_rows="dynamic", use_container_width=True, key=f"ed_{port_key}")
    if st.button("저장", key=f"sv_{port_key}"):
        df_editor['시작금'] = st.session_state['portfolio_config'].get(f'start_{port_key}', 0)
        st.session_state[f'df_{port_key}'] = df_editor
        st.session_state[f'df_{port_key}'].to_csv(path, index=False, encoding='utf-8-sig')
        st.rerun()

    with scoreboard_placeholder:
        st.markdown(f"### 🚀 {port_name} 실시간 성적표")
        df = st.session_state[f'df_{port_key}'].copy()
        if not df.empty:
            df['시총(억)'] = df['종목코드'].map(global_cap_map).fillna(0)
            df['액면가'] = df['종목코드'].map(global_fv_map).fillna(0)
            df['현재가'] = df['종목코드'].apply(lambda x: prices.get(x, {}).get('curr', 0))
            df['전일종가'] = df['종목코드'].apply(lambda x: prices.get(x, {}).get('prev', 0))
            
            df['전일대비(%)'] = ((df['현재가'] - df['전일종가']) / df['전일종가'] * 100).fillna(0)
            df['평가금액'] = df['현재가'] * df['수량']
            df['평가손익'] = (df['현재가'] - df['매수단가']) * df['수량']
            df['매수총액'] = df['매수단가'] * df['수량']
            df['수익률(%)'] = (df['평가손익'] / df['매수총액'] * 100).fillna(0)
            
            t_buy, t_val, t_profit, t_prev_val = df['매수총액'].sum(), df['평가금액'].sum(), df['평가손익'].sum(), (df['전일종가'] * df['수량']).sum()
            d_diff = t_val - t_prev_val
            d_pct = (d_diff / t_prev_val * 100) if t_prev_val > 0 else 0
            
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("💰 총 매수", f"{int(t_buy):,}원")
            c2.metric("📈 총 평가액", f"{int(t_val):,}원")
            c3.metric("🌟 오늘 변동액", f"{int(d_diff):,}원", delta=f"{d_pct:.2f}%")
            c4.metric("💸 총 평가손익", f"{int(t_profit):,}원", delta=f"{int(t_profit):,}원")
            c5.metric("📊 총 수익률", f"{(t_profit/t_buy*100) if t_buy > 0 else 0:.2f}%", delta=f"{(t_profit/t_buy*100) if t_buy > 0 else 0:.2f}%")
            
            df['티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)

            def style_port_final(st_df):
                s = pd.DataFrame('', index=st_df.index, columns=st_df.columns)
                for col in ['전일대비(%)', '평가손익', '수익률(%)']:
                    s[col] = st_df[col].apply(lambda x: 'color: #FF3333; font-weight:bold;' if x > 0 else ('color: #3399FF; font-weight:bold;' if x < 0 else ''))
                
                h_css = 'background-color: rgba(255, 167, 38, 0.1); color: #FFA726; border: 1px solid #FFA726; font-weight:bold; border-radius: 4px;'
                w_css = 'background-color: rgba(255, 0, 0, 0.2); color: #FF3333; border: 2px solid #FF3333; font-weight:bold; border-radius: 4px;'
                
                s['시총(억)'] = st_df['시총(억)'].apply(lambda x: h_css if 0 < x <= 150 else '')
                for i, row in st_df.iterrows():
                    if row['액면가'] > 0 and row['현재가'] < row['액면가']: s.loc[i, ['현재가', '액면가']] = w_css
                    elif 0 < row['현재가'] < 1000: s.loc[i, '현재가'] = h_css
                return s

            st.dataframe(df.style.apply(style_port_final, axis=None).format({'전일대비(%)':'{:.2f}%','수익률(%)':'{:.2f}%','시총(억)':'{:,}','매수단가':'{:,}','액면가':'{:,}','현재가':'{:,}','평가금액':'{:,}','평가손익':'{:,}'}), 
                         use_container_width=True, hide_index=True,
                         column_order=['티커_L', '종목명_L', '시총(억)', '수량', '매수단가', '액면가', '현재가', '전일대비(%)', '평가금액', '평가손익', '수익률(%)'],
                         column_config={"티커_L": st.column_config.LinkColumn("코드", display_text=r"code=(.+)"), "종목명_L": st.column_config.LinkColumn("종목명", display_text=r"#(.+)")})

# =========================================================
# 🚀 메인 대시보드
# =========================================================
st.markdown('<p class="main-title">💼 내 퀀트 포트폴리오 종합 대시보드</p>', unsafe_allow_html=True)
tabs = st.tabs(["📊 종합 요약", "🌱 또", "🌿 쏘", "🍀 맘", "⚖️ 리밸런싱 계산기"])

with tabs[0]:
    config = st.session_state['portfolio_config']
    total_start_sum = config.get('start_ddo', 0) + config.get('start_sso', 0) + config.get('start_mom', 0)
    
    try: dt_obj = datetime.strptime(config['start_date'], '%Y-%m-%d'); disp_date = f"{dt_obj.strftime('%y')}년 {dt_obj.month}월 {dt_obj.day}일"
    except: disp_date = config['start_date']
        
    st.markdown(f"##### ⚙️ 비교 시점 및 시작 수익금 설정 <span style='font-size: 1rem; color: #9ca3af; font-weight: normal; margin-left: 10px;'>(기준일 : {disp_date}, 총 시작금 : {total_start_sum:,}원)</span>", unsafe_allow_html=True)
    
    with st.form("config_form"):
        c_dt, c_d, c_s, c_m, c_btn = st.columns([1.2, 1, 1, 1, 0.7])
        dt_val = datetime.strptime(config['start_date'], '%Y-%m-%d').date() if '-' in config['start_date'] else datetime.today().date()
        
        with c_dt: new_date = st.date_input("📅 시작일", value=dt_val)
        with c_d: str_ddo = st.text_input("💰 [또] 시작금", value=f"{config['start_ddo']:,}")
        with c_s: str_sso = st.text_input("💰 [쏘] 시작금", value=f"{config['start_sso']:,}")
        with c_m: str_mom = st.text_input("💰 [맘] 시작금", value=f"{config['start_mom']:,}")
        with c_btn: submitted = st.form_submit_button("설정\n저장", use_container_width=True)
        
        if submitted:
            new_ddo = parse_krw(str_ddo, config['start_ddo'])
            new_sso = parse_krw(str_sso, config['start_sso'])
            new_mom = parse_krw(str_mom, config['start_mom'])
            new_config = {"start_date": str(new_date), "start_ddo": new_ddo, "start_sso": new_sso, "start_mom": new_mom}
            
            st.session_state['portfolio_config'] = new_config
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f: json.dump(new_config, f)
            
            # 💡 [핵심] 입력된 시작금을 각각의 CSV 파일 열에 덮어쓰기하여 저장
            for p_key, start_val in [("ddo", new_ddo), ("sso", new_sso), ("mom", new_mom)]:
                df = st.session_state[f'df_{p_key}']
                df['시작금'] = start_val
                df.to_csv(PORT_PATHS[p_key], index=False, encoding='utf-8-sig')
            
            st.rerun()

    st.markdown('<p class="section-title">🏆 포트폴리오 성과 요약</p>', unsafe_allow_html=True)
    summary_data, total_buy, total_profit, total_daily, total_since, total_prev_all = [], 0, 0, 0, 0, 0

    for p_name, p_key in [("또", "ddo"), ("쏘", "sso"), ("맘", "mom")]:
        df, start_val = st.session_state[f'df_{p_key}'], config[f'start_{p_key}']
        if not df.empty:
            df['curr'] = df['종목코드'].apply(lambda x: global_prices.get(x, {}).get('curr', 0))
            df['prev'] = df['종목코드'].apply(lambda x: global_prices.get(x, {}).get('prev', 0))
            t_buy, t_val, t_prev = (df['매수단가']*df['수량']).sum(), (df['curr']*df['수량']).sum(), (df['prev']*df['수량']).sum()
            t_profit, d_diff = t_val - t_buy, t_val - t_prev
            since_start = t_profit - start_val
            total_buy += t_buy; total_profit += t_profit; total_daily += d_diff; total_since += since_start; total_prev_all += t_prev
            summary_data.append({"name": p_name, "daily": d_diff, "daily_pct": (d_diff/t_prev*100) if t_prev else 0, "pct": (t_profit/t_buy*100) if t_buy else 0, "profit": t_profit, "since": since_start})
        else:
            summary_data.append({"name": p_name, "daily": 0, "daily_pct": 0, "pct": 0, "profit": 0, "since": -start_val})
            total_since -= start_val

    html = "<table class='summary-table'><thead><tr><th>포트폴리오</th><th>오늘의 등락</th><th>오늘의 등락률</th><th>총 수익률</th><th>현재 수익 금액</th><th style='color:#ffffff; background-color:#3e4452;'>시작일 기준 수익 금액</th></tr></thead><tbody>"
    get_t_cls = lambda v: "val-red-thin" if v > 0 else ("val-blue-thin" if v < 0 else "val-gray")
    get_cls = lambda v, b=False: (f"box-red" if b and v>0 else "box-blue" if b and v<0 else ("val-red" if v>0 else "val-blue" if v<0 else "val-gray"))

    for r in summary_data:
        html += f"<tr><td><b>{r['name']}</b></td><td class='{get_t_cls(r['daily'])}'>₩{int(r['daily']):,}</td><td class='{get_t_cls(r['daily_pct'])}'>{r['daily_pct']:.2f}%</td><td class='{get_cls(r['pct'])}'>{r['pct']:.2f}%</td><td class='{get_cls(r['profit'])}'>₩{int(r['profit']):,}</td><td class='highlight-cell'><span class='{get_cls(r['since'], True)}'>₩{int(r['since']):,}</span></td></tr>"

    html += f"<tr class='summary-total' style='border-top: 2px solid {'#FF3333' if total_since>=0 else '#3399FF'};'><td><b>합계</b></td><td class='{get_t_cls(total_daily)}'>₩{int(total_daily):,}</td><td class='{get_t_cls((total_daily/total_prev_all*100) if total_prev_all else 0)}'>{(total_daily/total_prev_all*100) if total_prev_all else 0:.2f}%</td><td class='val-white'><b>{total_profit/total_buy*100 if total_buy>0 else 0:.2f}%</b></td><td class='{get_cls(total_profit)}'><b>₩{int(total_profit):,}</b></td><td class='highlight-cell'><span style='font-size:1.4rem;' class='{get_cls(total_since, True)}'>₩{int(total_since):,}</span></td></tr></tbody></table>"
    st.markdown(html, unsafe_allow_html=True)

with tabs[1]: render_portfolio_tab("또", "ddo", PORT_PATHS["ddo"], global_prices)
with tabs[2]: render_portfolio_tab("쏘", "sso", PORT_PATHS["sso"], global_prices)
with tabs[3]: render_portfolio_tab("맘", "mom", PORT_PATHS["mom"], global_prices)

with tabs[4]:
    st.markdown('<p class="section-title">⚖️ 포트폴리오 교체/리밸런싱 계산기</p>', unsafe_allow_html=True)
    st.info("현재 보유 중인 포트폴리오를 기준으로, 새롭게 설정할 '목표 포트폴리오(엑셀/CSV)'를 업로드하면 최적의 매수/매도 주문 수량을 자동으로 계산해 드립니다.")
    
    c_sel, c_up = st.columns([1, 2])
    target_port_info = c_sel.selectbox("🔄 기준 포트폴리오 선택", options=[("또", "ddo"), ("쏘", "sso"), ("맘", "mom")], format_func=lambda x: f"[{x[0]}] 포트폴리오 기준")
    up_target = c_up.file_uploader("목표 엑셀/CSV 업로드 양식 (필수 열: '코드번호', '목표금액(100만원 단위)')", type=['csv', 'xlsx'], key="up_rebal")
    
    if up_target:
        try:
            tgt_df = pd.read_csv(up_target, encoding='utf-8-sig') if up_target.name.endswith('csv') else pd.read_excel(up_target)
            tgt_df.columns = tgt_df.columns.str.strip()
            code_col, target_col = [c for c in tgt_df.columns if '코드번호' in c][0], [c for c in tgt_df.columns if '목표금액' in c][0]
            
            tgt_df = tgt_df.dropna(subset=[code_col])
            tgt_df['종목코드'] = tgt_df[code_col].astype(str).str.replace(r'^[A-Za-z]+', '', regex=True).str.replace(r'\.0$', '', regex=True).str.zfill(6)
            tgt_df['목표금액'] = pd.to_numeric(tgt_df[target_col].astype(str).str.replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0).astype(int) * 10000
            
            curr_df = st.session_state[f'df_{target_port_info[1]}'].copy()
            merged = pd.merge(curr_df[['종목코드', '수량']], tgt_df[['종목코드', '목표금액']], on='종목코드', how='outer').fillna(0)
            merged['시총(억)'] = merged['종목코드'].map(global_cap_map).fillna(0)
            merged['액면가'] = merged['종목코드'].map(global_fv_map).fillna(0)
            merged['종목명'] = merged['종목코드'].map(master_df.set_index('종목코드')['종목명'].to_dict() if not master_df.empty else {}).fillna('이름없음')
            
            reb_prices = fetch_multi_prices(tuple(merged['종목코드'].unique()))
            merged['현재가'] = merged['종목코드'].apply(lambda x: reb_prices.get(x, {}).get('curr', 0))
            merged['현재평가금액'] = merged['수량'] * merged['현재가']
            merged['차액'] = merged['목표금액'] - merged['현재평가금액']
            
            def get_rebal_action(r):
                if r['목표금액'] == 0 and r['수량'] > 0: return "전량매도"
                if r['수량'] == 0 and r['목표금액'] > 0: return "신규매수"
                return "추가매수" if r['차액'] > 0 else ("부분매도" if r['차액'] < 0 else "유지")
                
            merged['주문'] = merged.apply(get_rebal_action, axis=1)
            merged['주문수량'] = merged.apply(lambda r: r['수량'] if r['주문']=="전량매도" else int(abs(r['차액']) // r['현재가']) if r['현재가']>0 else 0, axis=1)
            merged['예상체결금액'] = merged.apply(lambda r: r['주문수량']*r['현재가'] if r['주문'] in ["신규매수","추가매수"] else (-r['주문수량']*r['현재가'] if r['주문'] in ["전량매도","부분매도"] else 0), axis=1)
            
            merged = merged[(merged['수량'] > 0) | (merged['목표금액'] > 0)].sort_values(by='종목명')
            buy_sum, sell_sum = merged[merged['예상체결금액'] > 0]['예상체결금액'].sum(), merged[merged['예상체결금액'] < 0]['예상체결금액'].abs().sum()
            net_cash = sell_sum - buy_sum
            
            net_css, net_text = ("color: #FF3333; background-color: rgba(255, 51, 51, 0.15);", f"₩{net_cash:,} 잔금") if net_cash >= 0 else ("color: #3399FF; background-color: rgba(51, 153, 255, 0.15);", f"₩{abs(net_cash):,} 추가 필요")
            
            c_head, c_btn = st.columns([5, 1])
            c_head.markdown(f"**🔵 매도 자금:** `₩{sell_sum:,}` &nbsp;|&nbsp; **🔴 매수 자금:** `₩{buy_sum:,}` &nbsp;|&nbsp; **💡 잔액:** <span style='font-size: 1.25rem; padding: 2px 10px; border-radius: 6px; {net_css}'>**{net_text}**</span>", unsafe_allow_html=True)
            c_btn.download_button("📥 다운로드", merged.to_csv(index=False, encoding='utf-8-sig'), f"리밸런싱_{datetime.today().strftime('%Y%m%d')}.csv", "text/csv", use_container_width=True)
            
            def style_rebal(st_df):
                s = pd.DataFrame('', index=st_df.index, columns=st_df.columns)
                for i, r in st_df.iterrows():
                    if r['주문'] in ["신규매수", "추가매수"]: s.loc[i, ['주문','주문수량','예상체결금액']] = 'color: #FF3333; font-weight: bold; background-color: rgba(255,51,51,0.1);'
                    elif r['주문'] in ["전량매도", "부분매도"]: s.loc[i, ['주문','주문수량','예상체결금액']] = 'color: #3399FF; font-weight: bold; background-color: rgba(51,153,255,0.1);'
                    else: s.loc[i, ['주문','예상체결금액']] = 'color: #9ca3af;'
                return s

            st.dataframe(merged[['종목코드', '종목명', '시총(억)', '현재가', '액면가', '수량', '현재평가금액', '목표금액', '주문', '주문수량', '예상체결금액']].style.apply(style_rebal, axis=None).format({'시총(억)':'{:,}','현재가':'{:,}','액면가':'{:,}','수량':'{:,}','현재평가금액':'{:,}','목표금액':'{:,}','주문수량':'{:,}','예상체결금액':lambda x: f"+{x:,}" if x>0 else f"{x:,}" if x<0 else "0"}), use_container_width=True, hide_index=True)
        except Exception as e: st.error(f"오류: {e}")
