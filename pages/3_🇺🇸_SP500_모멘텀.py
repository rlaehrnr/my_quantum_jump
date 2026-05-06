import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import FinanceDataReader as fdr
import numpy as np
import io

st.set_page_config(page_title="US S&P 500 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS
from utils.ui_components import inject_custom_css, apply_korea_styling, style_kospi_ma, get_styled_stats, get_mdd_history, get_monthly_heatmap, ma_cfg, main_cfg
from utils.calculator import calc_us_momentum

inject_custom_css()

@st.cache_data(ttl=3600)
def robust_get_us_ma_all(target_date_str, ticker='^GSPC'):
    import yfinance as yf
    try:
        target_date = pd.to_datetime(target_date_str).normalize()
        df = pd.DataFrame()
        try:
            df = yf.Ticker(ticker).history(period="2y")
            if not df.empty and df.index.tz is not None: df.index = df.index.tz_localize(None)
        except: pass
        
        if df.empty:
            fdr_ticker = 'US500' if ticker == '^GSPC' else 'IXIC'
            df = fdr.DataReader(fdr_ticker)
            
        if df.empty: return 0.0, {}
        
        df.index = pd.to_datetime(df.index).normalize()
        df = df[df.index <= target_date]
        if df.empty: return 0.0, {}
        
        curr_p = df['Close'].iloc[-1]
        mas = {
            4: round(df['Close'].rolling(80).mean().iloc[-1], 2),
            5: round(df['Close'].rolling(100).mean().iloc[-1], 2),
            6: round(df['Close'].rolling(120).mean().iloc[-1], 2),
            10: round(df['Close'].rolling(200).mean().iloc[-1], 2),
            12: round(df['Close'].rolling(240).mean().iloc[-1], 2)
        }
        return curr_p, mas
    except Exception: return 0.0, {}

@st.cache_data(ttl=3600)
def robust_get_us_idx_return(target_date_str, ticker='^GSPC'):
    import yfinance as yf
    try:
        target_date = pd.to_datetime(target_date_str).normalize()
        df = pd.DataFrame()
        try:
            df = yf.Ticker(ticker).history(period="2y")
            if not df.empty and df.index.tz is not None: df.index = df.index.tz_localize(None)
        except: pass
        
        if df.empty:
            fdr_ticker = 'US500' if ticker == '^GSPC' else 'IXIC'
            df = fdr.DataReader(fdr_ticker)
            
        if df.empty: return 0.0, 0.0
        
        df.index = pd.to_datetime(df.index).normalize()
        df = df[df.index <= target_date]
        if df.empty: return 0.0, 0.0
        
        curr_p = df['Close'].iloc[-1]
        df_1m = df[df.index <= target_date - pd.DateOffset(months=1)]
        ret_1m = round(((curr_p / df_1m['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m.empty else 0.0
        df_3m = df[df.index <= target_date - pd.DateOffset(months=3)]
        ret_3m = round(((curr_p / df_3m['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m.empty else 0.0
        return ret_1m, ret_3m
    except Exception: return 0.0, 0.0

@st.cache_data(ttl=86400, show_spinner=False)
def get_spx_history_cached():
    import yfinance as yf
    try:
        spx = pd.DataFrame()
        try:
            spx = yf.Ticker('^GSPC').history(start='1998-01-01')
            if not spx.empty and spx.index.tz is not None: spx.index = spx.index.tz_localize(None)
        except: pass
        if spx.empty: spx = fdr.DataReader('US500', '1998-01-01')
        if not spx.empty: spx.index = pd.to_datetime(spx.index).normalize()
        return spx
    except: return pd.DataFrame()

# 💡 [해결 1] AttributeError 해결 (settings_tuple 사용)
@st.cache_data(show_spinner=False)
def generate_excel_report_cached(settings_tuple, df_stats, df_monthly, df_cum_ret, df_trade):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_set = pd.DataFrame(list(settings_tuple), columns=['설정 항목', '값'])
        df_set.to_excel(writer, sheet_name='요약_및_통계', index=False, startrow=0)
        df_stats.to_excel(writer, sheet_name='요약_및_통계', index=False, startrow=len(df_set) + 2)
        df_monthly.to_excel(writer, sheet_name='월별_수익률', index=False)
        df_mdd = ((df_cum_ret / df_cum_ret.cummax()) - 1) * 100
        df_mdd.reset_index().to_excel(writer, sheet_name='전략별_MDD', index=False)
        df_cum_ret.reset_index().to_excel(writer, sheet_name='누적_수익률', index=False)
        if not df_trade.empty:
            df_trade.to_excel(writer, sheet_name='상세_매매내역', index=False)
    return output.getvalue()


st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="https://m.stock.naver.com/worldstock/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
                <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">🇺🇸 US S&P 500 모멘텀 터미널</h1>
                <span style="font-size: 0.95rem; color: #10b981; background-color: #d1fae5; padding: 4px 10px; border-radius: 6px; border: 1px solid #6ee7b7; white-space: nowrap;">🔗 네이버 증권 이동</span>
            </div>
        </a>
    </div>
''', unsafe_allow_html=True)

archive_path = "archive_sp500"
f_daily = 'data/momentum_data_daily_sp500.csv'
f_hash = get_folder_hash(archive_path) 
df_master = load_archive_data(archive_path, f_hash) 

if df_master.empty:
    st.error("🚨 archive_sp500 폴더에 데이터가 없습니다!")
    st.stop()

col_mapping = {
    'Date': '종목선정일', 'Year': '투자연도_raw', 'Ticker': '종목코드', 
    'Close_Price': '종가', 'Past_1M_Return(%)': '1개월(%)', 
    'Past_3M_Return(%)': '3개월(%)', 'Past_6M_Return(%)': '6개월(%)', 
    'Past_12M_Return(%)': '12개월(%)', 'Forward_1M_Return(%)': '이번달수익률'
}

for eng, kor in col_mapping.items():
    if eng in df_master.columns and kor in df_master.columns:
        df_master[kor] = df_master[kor].fillna(df_master[eng])
        df_master = df_master.drop(columns=[eng])
    elif eng in df_master.columns:
        df_master = df_master.rename(columns={eng: kor})

df_master = df_master.dropna(subset=['종목코드'])
df_master['종목코드'] = df_master['종목코드'].astype(str).replace('nan', '')
df_master = df_master[df_master['종목코드'] != '']

if '종목명' not in df_master.columns: df_master['종목명'] = df_master['종목코드']
df_master['종목명'] = df_master['종목명'].fillna(df_master['종목코드'])
df_master['종목명'] = np.where(df_master['종목명'].astype(str).str.lower() == 'nan', df_master['종목코드'], df_master['종목명'])

if '시장' not in df_master.columns: df_master['시장'] = 'US'
df_master['시장'] = df_master['시장'].fillna('US')
df_master['시장'] = np.where(df_master['시장'].astype(str).str.lower() == 'nan', 'US', df_master['시장'])

df_master['통합티커'] = df_master['시장'] + ":" + df_master['종목코드']

df_master['종목선정일'] = pd.to_datetime(df_master['종목선정일'], errors='coerce')
df_master = df_master.dropna(subset=['종목선정일'])

target_dates = df_master['종목선정일'] + pd.Timedelta(days=15)
df_master['투자월'] = target_dates.dt.strftime('%Y-%m')
df_master['투자연도'] = target_dates.dt.year

target_cols = ['시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']
for col in target_cols:
    if col in df_master.columns: df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)
    else: df_master[col] = 0

valid_years = df_master['투자연도'].dropna().unique().astype(int).tolist()
if not valid_years: valid_years = [datetime.today().year]
years_list = sorted(valid_years)
min_y, max_y = min(years_list), max(years_list)
if min_y >= max_y: min_y = max_y - 1 

us_main_cfg = main_cfg.copy()
us_main_cfg.update({
    '12-1개월(%)': st.column_config.NumberColumn('12-1개월(%)', format="%.2f%%"),
    '6-1개월(%)': st.column_config.NumberColumn('6-1개월(%)', format="%.2f%%"),
    '3-1개월(%)': st.column_config.NumberColumn('3-1개월(%)', format="%.2f%%"),
    '종가': st.column_config.NumberColumn('종가', format="%.2f"),
    '시가총액': st.column_config.NumberColumn('시가총액', format="%d")
})

# 💡 [해결 3] 컬럼 순서도 다시 6-1개월이 먼저 오도록 복원
col_order_strat1 = ['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)', '이번달수익률']
col_order_strat2 = ['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)', '이번달수익률']
col_order_d1 = ['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)']
col_order_d2 = ['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)']

naver_exceptions = {'CIEN': '.K', 'COHR': '.K', 'EQNR': '.K', 'DELL': '.K'}
def get_naver_ticker(code): return f"{code}{naver_exceptions.get(code, '.O')}"

# 💡 [해결 3] 6-1개월 기준으로 정렬 방식 완벽 복원
def get_strategy_stocks_us_custom(df_month, top_n_12=150, top_n_6=150, top_n_3=150):
    df_calc = calc_us_momentum(df_month)
    
    top_12 = df_calc.sort_values('12-1개월(%)', ascending=False).head(top_n_12)
    top_6 = df_calc.sort_values('6-1개월(%)', ascending=False).head(top_n_6)
    top_3 = df_calc.sort_values('3-1개월(%)', ascending=False).head(top_n_3)
    
    strat1 = top_12[top_12['종목코드'].isin(top_6['종목코드'])].sort_values('6-1개월(%)', ascending=False)
    strat2 = top_6[top_6['종목코드'].isin(top_3['종목코드'])].sort_values('6-1개월(%)', ascending=False)
    
    return df_calc, strat1, strat2

@st.cache_data(show_spinner=False)
def run_backtest_us_fast(df, start_year, end_year, ma_months, apply_timing, rank_s1, rank_s2, top_n_12, top_n_6, top_n_3, spx):
    if not spx.empty:
        spx['MA'] = spx['Close'].rolling(ma_months * 20).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA']
        
    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        df_calc = df[df['투자월'] == m_str].copy()
        if df_calc.empty: continue
        
        base_date = pd.to_datetime(m_str + '-01') - pd.Timedelta(days=5)
        is_below = False
        if not spx.empty:
            past_spx = spx[spx.index <= base_date]
            if not past_spx.empty: is_below = past_spx['Is_Below'].iloc[-1]
                
        mult = 0.0 if (apply_timing and is_below) else 1.0
        
        _, s1_all, s2_all = get_strategy_stocks_us_custom(df_calc, top_n_12, top_n_6, top_n_3)
        s1 = s1_all.iloc[rank_s1[0]-1:rank_s1[1]] if not s1_all.empty else pd.DataFrame()
        s2 = s2_all.iloc[rank_s2[0]-1:rank_s2[1]] if not s2_all.empty else pd.DataFrame()
        
        r1 = s1['이번달수익률'].mean() * mult if not s1.empty else 0
        r2 = s2['이번달수익률'].mean() * mult if not s2.empty else 0
        
        s1_codes = set(s1['종목코드']) if not s1.empty else set()
        s2_codes = set(s2['종목코드']) if not s2.empty else set()
        all_codes = s1_codes.union(s2_codes)
        ret_combined_excl = df_calc[df_calc['종목코드'].isin(all_codes)]['이번달수익률'].mean() * mult if all_codes else 0
        
        sum_ret = (s1['이번달수익률'].sum() if not s1.empty else 0) + (s2['이번달수익률'].sum() if not s2.empty else 0)
        total_len = len(s1) + len(s2)
        ret_combined_incl = (sum_ret / total_len * mult) if total_len > 0 else 0
        
        records.append({
            '투자월': m_str, 'invested': mult > 0, 
            f'🔥 12-1M & 6-1M ({rank_s1[0]}~{rank_s1[1]}위)': r1, 
            f'🐎 6-1M & 3-1M ({rank_s2[0]}~{rank_s2[1]}위)': r2,
            '앙상블 (50:50 전략)': (r1 * 0.5) + (r2 * 0.5),
            '통합 전략 (중복 제외 1/N)': ret_combined_excl,
            '통합 전략 (중복 인정 1/N)': ret_combined_incl
        })
        
        if mult > 0:
            if not s1.empty:
                for i, (_, r) in enumerate(s1.iterrows()): trade_logs.append({'투자월': m_str, '전략': '12-1M & 6-1M', '순위': f"{i+rank_s1[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
            if not s2.empty:
                for i, (_, r) in enumerate(s2.iterrows()): trade_logs.append({'투자월': m_str, '전략': '6-1M & 3-1M', '순위': f"{i+rank_s2[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
        else:
            trade_logs.append({'투자월': m_str, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)


tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트", "🏅 스코어 커스텀 백테스트"])

# ==========================================
# 탭 1. 월별 상세 분석
# ==========================================
with tab1:
    avail_years = [str(y) for y in sorted(years_list, reverse=True)]
    c_y, c_m = st.columns([1.2, 8.8])
    with c_y: 
        st.markdown("<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>📅 투자 연도</b></div>", unsafe_allow_html=True)
        selected_year = st.selectbox("투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y", label_visibility="collapsed")
    
    safe_year = int(float(selected_year)) if selected_year else datetime.today().year
    m_list = sorted(df_master[df_master['투자연도'] == safe_year]['투자월'].astype(str).apply(lambda x: x.split('-')[1] if '-' in x else x).unique())
    default_m_index = len(m_list) - 1 if len(m_list) > 0 else 0

    with c_m:
        month_label = st.empty()
        if m_list:
            selected_month = st.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m", label_visibility="collapsed", index=default_m_index)
            target_month_str = f"{safe_year}-{selected_month}"
            df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
        else:
            st.warning(f"🚨 {safe_year}년에 해당하는 데이터가 없습니다.")
            df_monthly = pd.DataFrame()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0] if '종목선정일' in df_monthly.columns and not pd.isna(df_monthly['종목선정일'].iloc[0]) else datetime.today().strftime('%Y-%m-%d')
        month_label.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🌙 투자 월</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 선정일: {base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else base_date}</span></div>", unsafe_allow_html=True)

        spx_curr, spx_mas = robust_get_us_ma_all(base_date, '^GSPC')
        ndx_curr, ndx_mas = robust_get_us_ma_all(base_date, '^IXIC')
        
        ma_df = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.IXIC#{ndx_curr:,.2f}", 'base_price': round(ndx_curr, 2), '4개월선': ndx_mas.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_monthly['통합티커_L'] = df_monthly.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{get_naver_ticker(r['종목코드'])}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
        df_monthly['종목명_L'] = df_monthly.apply(lambda r: f"https://m.stock.naver.com/fchart/foreign/stock/{get_naver_ticker(r['종목코드'])}#{r['종목명']}", axis=1)

        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us_custom(df_monthly, top_n_12=150, top_n_6=150, top_n_3=150)
        spx_1m, spx_3m = robust_get_us_idx_return(base_date, '^GSPC')
        ndx_1m, ndx_3m = robust_get_us_idx_return(base_date, '^IXIC')
        
        df_strat1_t1['순위'] = range(1, len(df_strat1_t1) + 1)
        df_strat2_t1['순위'] = range(1, len(df_strat2_t1) + 1)
        df_us_t1 = df_us_t1.sort_values('시가총액', ascending=False) if '시가총액' in df_us_t1.columns else df_us_t1
        df_us_t1['순위'] = range(1, len(df_us_t1) + 1)

        cycle_year_t1 = get_cycle_year(safe_year)
        bad_m_str_t1 = ", ".join(f"{m}월" for m in PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year_t1, [])) or "없음"
        
        is_below_ma = (spx_curr > 0) and (spx_curr < spx_mas.get(10, 0))
        status, box_c, text_c = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below_ma else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc = "S&P500 200일선 이탈" if is_below_ma else "안전"

        col1, col2, col3, col4, col5, col6 = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric("📈 S&P 500 1M", f"{spx_1m}%")
        with col2: st.metric("📈 S&P 500 3M", f"{spx_3m}%")
        with col3: st.metric("📈 NASDAQ 1M", f"{ndx_1m}%")
        with col4: st.metric("📈 NASDAQ 3M", f"{ndx_3m}%")
        with col5: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 12px; font-weight: bold; color: #64748b; margin-bottom: 2px;">🇺🇸대통령 <span style="color:#0047AB;">{cycle_year_t1}년차</span> ({safe_year}년)</div><div style="font-size: 16px; color: #D84315; font-weight:900;">🚨 위험달: {bad_m_str_t1}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_c}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_c}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_c}; font-weight: bold;">최종 판단 ({reason_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_c};">{status}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        c_l, c_r = st.columns(2)
        count_p, count_s = len(df_strat1_t1), len(df_strat2_t1)
        val_p = 5 if count_p >= 5 else max(1, count_p)
        val_s = 5 if count_s >= 5 else max(1, count_s)
        
        with c_l:
            col_t1, col_i1, col_r1 = st.columns([4, 2, 4])
            with col_t1: st.markdown(f"<h4 style='margin:0;'>🔥 12-1M & 6-1M <span style='font-size:13px; color:gray;'>({count_p}개)</span></h4>", unsafe_allow_html=True)
            with col_i1: top_n_p = st.number_input("p_n", 1, max(1, count_p), val_p, key="calc_p", label_visibility="collapsed")
            with col_r1:
                avg_ret_p = df_strat1_t1.head(top_n_p)['이번달수익률'].mean() if count_p > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_p}개 평균: <span style='color:{'#D32F2F' if avg_ret_p>0 else '#1976D2'};'>{avg_ret_p:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12-1M & 6-1M 각각 150위 이내 교집합 종목 (6-1M 순)</p>', unsafe_allow_html=True)
            
        with c_r:
            col_t2, col_i2, col_r2 = st.columns([4, 2, 4])
            with col_t2: st.markdown(f"<h4 style='margin:0;'>🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({count_s}개)</span></h4>", unsafe_allow_html=True)
            with col_i2: top_n_s = st.number_input("s_n", 1, max(1, count_s), val_s, key="calc_s", label_visibility="collapsed")
            with col_r2:
                avg_ret_s = df_strat2_t1.head(top_n_s)['이번달수익률'].mean() if count_s > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_s}개 평균: <span style='color:{'#D32F2F' if avg_ret_s>0 else '#1976D2'};'>{avg_ret_s:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">6-1M & 3-1M 각각 150위 이내 교집합 종목 (6-1M 순)</p>', unsafe_allow_html=True)

        # 💡 [해결 2] 9위 10위 색상 오염 방지를 위해 하이라이트 코드를 각각 독립적으로 분리!
        sel_codes_p = df_strat1_t1.head(top_n_p)['종목코드'].tolist()
        sel_codes_s = df_strat2_t1.head(top_n_s)['종목코드'].tolist()
        overlap_codes_t1 = set(sel_codes_p).intersection(set(sel_codes_s))
        
        # 하단 전체 표를 위한 총합
        highlight_codes_all_t1 = list(set(sel_codes_p + sel_codes_s))

        with c_l:
            st.dataframe(df_strat1_t1.style.apply(apply_korea_styling, highlight_codes=sel_codes_p, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat1, column_config=us_main_cfg)
        with c_r:
            st.dataframe(df_strat2_t1.style.apply(apply_korea_styling, highlight_codes=sel_codes_s, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat2, column_config=us_main_cfg)

        st.markdown("<hr style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        st.markdown("### 🏆 기간별 모멘텀 상위 30위")
        
        df_12_1 = df_us_t1.sort_values('12-1개월(%)', ascending=False).head(30)
        df_6_1 = df_us_t1.sort_values('6-1개월(%)', ascending=False).head(30)
        df_3_1 = df_us_t1.sort_values('3-1개월(%)', ascending=False).head(30)
        
        for df in [df_12_1, df_6_1, df_3_1]: df['순위'] = range(1, 31)
            
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.markdown("#### 🥇 12-1개월 모멘텀")
            st.dataframe(df_12_1.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_t1, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)'], column_config=us_main_cfg)
        with col_m2:
            st.markdown("#### 🥈 6-1개월 모멘텀")
            st.dataframe(df_6_1.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_t1, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)'], column_config=us_main_cfg)
        with col_m3:
            st.markdown("#### 🥉 3-1개월 모멘텀")
            st.dataframe(df_3_1.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_t1, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '3-1개월(%)'], column_config=us_main_cfg)

        st.markdown("---")
        st.markdown(f"### 🌐 S&P 500 전체 순위 <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 선정일: {base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else base_date}</span>", unsafe_allow_html=True)
        cols_m = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '이번달수익률']
        st.dataframe(df_us_t1.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_t1, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_m, column_config=us_main_cfg)

# ==========================================
# 탭 2. 실시간 데일리 순위
# ==========================================
with tab2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily)
        
        for eng, kor in col_mapping.items():
            if eng in df_daily.columns and kor in df_daily.columns:
                df_daily[kor] = df_daily[kor].fillna(df_daily[eng])
                df_daily = df_daily.drop(columns=[eng])
            elif eng in df_daily.columns:
                df_daily = df_daily.rename(columns={eng: kor})
        
        df_daily = df_daily.dropna(subset=['종목코드'])
        df_daily['종목코드'] = df_daily['종목코드'].astype(str).replace('nan', '')
        df_daily = df_daily[df_daily['종목코드'] != '']
        
        if '종목명' not in df_daily.columns: df_daily['종목명'] = df_daily['종목코드']
        df_daily['종목명'] = df_daily['종목명'].fillna(df_daily['종목코드'])
        df_daily['종목명'] = np.where(df_daily['종목명'].astype(str).str.lower() == 'nan', df_daily['종목코드'], df_daily['종목명'])
        
        if '시장' not in df_daily.columns: df_daily['시장'] = 'US'
        df_daily['시장'] = df_daily['시장'].fillna('US')
        df_daily['시장'] = np.where(df_daily['시장'].astype(str).str.lower() == 'nan', 'US', df_daily['시장'])
        
        df_daily['통합티커'] = df_daily['시장'] + ":" + df_daily['종목코드']
        
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        safe_date = b_date_d if b_date_d != "오늘" else datetime.today().strftime('%Y-%m-%d')
        
        for col in target_cols:
            if col in df_daily.columns: df_daily[col] = pd.to_numeric(df_daily[col], errors='coerce').fillna(0)
            else: df_daily[col] = 0
        
        st.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        
        spx_curr_d, spx_mas_d = robust_get_us_ma_all(safe_date, '^GSPC')
        ndx_curr_d, ndx_mas_d = robust_get_us_ma_all(safe_date, '^IXIC')

        ma_df_d = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr_d:,.2f}", 'base_price': round(spx_curr_d, 2), '4개월선': spx_mas_d.get(4, 0), '5개월선': spx_mas_d.get(5, 0), '6개월선': spx_mas_d.get(6, 0), '10개월선': spx_mas_d.get(10, 0), '12개월선': spx_mas_d.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.IXIC#{ndx_curr_d:,.2f}", 'base_price': round(ndx_curr_d, 2), '4개월선': ndx_mas_d.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        # 💡 [해결 1] 잘리기 전에 미리 네이버 링크부터 달아줍니다.
        df_daily['통합티커_L'] = df_daily.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{get_naver_ticker(r['종목코드'])}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
        df_daily['종목명_L'] = df_daily.apply(lambda r: f"https://m.stock.naver.com/fchart/foreign/stock/{get_naver_ticker(r['종목코드'])}#{r['종목명']}", axis=1)

        df_us_d, df_strat1_d, df_strat2_d = get_strategy_stocks_us_custom(df_daily, top_n_12=150, top_n_6=150, top_n_3=150)
        spx_1m_d, spx_3m_d = robust_get_us_idx_return(safe_date, '^GSPC')
        ndx_1m_d, ndx_3m_d = robust_get_us_idx_return(safe_date, '^IXIC')
        
        df_strat1_d['순위'] = range(1, len(df_strat1_d) + 1)
        df_strat2_d['순위'] = range(1, len(df_strat2_d) + 1)
        df_us_d = df_us_d.sort_values('시가총액', ascending=False) if '시가총액' in df_us_d.columns else df_us_d
        df_us_d['순위'] = range(1, len(df_us_d) + 1)

        is_below_ma_d = (spx_curr_d > 0) and (spx_curr_d < spx_mas_d.get(10, 0))
        status_d, box_d, text_d = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below_ma_d else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc_d = "S&P500 200일선 이탈" if is_below_ma_d else "안전"

        vix_file = 'data/vix data.csv'
        vix_latest_high, vix_latest_date_str = "데이터없음", ""
        vix_35_date_str, vix_35_high, days_diff_str = "-", "-", "-"
        is_vix_warning = False

        if os.path.exists(vix_file):
            try:
                vix_df = pd.read_csv(vix_file)
                vix_df['날짜'] = pd.to_datetime(vix_df['날짜'])
                vix_df = vix_df.sort_values('날짜')
                if not vix_df.empty:
                    latest_row = vix_df.iloc[-1]
                    vix_latest_high = f"{latest_row['고가']:.2f}"
                    vix_latest_date = latest_row['날짜']
                    vix_latest_date_str = f"{vix_latest_date.month}/{vix_latest_date.day}"
                    
                    high_35_df = vix_df[vix_df['고가'] >= 35.0]
                    if not high_35_df.empty:
                        last_35_row = high_35_df.iloc[-1]
                        vix_35_date_str = last_35_row['날짜'].strftime('%y/%m/%d')
                        vix_35_high = f"{last_35_row['고가']:.2f}"
                        days_diff = (pd.to_datetime(safe_date) - last_35_row['날짜']).days
                        days_diff_str = f"{days_diff}일 경과"
                        if 0 <= days_diff <= 20: is_vix_warning = True
            except: pass

        col1d, col2d, col3d, col4d, col5d, col6d = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1d: st.metric("📈 S&P 500 1M", f"{spx_1m_d}%")
        with col2d: st.metric("📈 S&P 500 3M", f"{spx_3m_d}%")
        with col3d: st.metric("📈 NASDAQ 1M", f"{ndx_1m_d}%")
        with col4d: st.metric("📈 NASDAQ 3M", f"{ndx_3m_d}%")
        
        vix_bg = "#FFF0F0" if is_vix_warning else "#FFFFFF"
        vix_border = "#FFCDD2" if is_vix_warning else "#d1d5db"
        vix_title_color = "#C62828" if is_vix_warning else "#64748b"
        vix_val_color = "#D84315" if is_vix_warning else "#333333"
        vix_icon = "🚨" if is_vix_warning else "📊"
        vix_label = f"전일 ({vix_latest_date_str}일) 고가:" if vix_latest_date_str else "전일 고가:"
        
        vix_html = f'''<a href="https://m.stock.naver.com/worldstock/index/.VIX/total" target="_blank" style="text-decoration: none; color: inherit;">
            <div class="title-link" style="background-color: {vix_bg}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {vix_border}; height: 95px; display: flex; flex-direction: column; justify-content: center;">
                <div style="font-size: 12px; font-weight: bold; color: {vix_title_color}; margin-bottom: 2px;">{vix_icon} VIX 35 돌파</div>
                <div style="font-size: 11px; font-weight: bold; color: {vix_title_color}; margin-bottom: 4px;">VIX {vix_35_high} - {vix_35_date_str}돌파 ({days_diff_str})</div>
                <div style="font-size: 15px; color: {vix_val_color}; font-weight:900;">{vix_label} {vix_latest_high}</div>
            </div></a>'''
        
        with col5d: st.markdown(vix_html, unsafe_allow_html=True)
        with col6d: st.markdown(f'<div style="background-color: {box_d}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_d}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_d}; font-weight: bold;">오늘의 시장 상태 ({reason_desc_d})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_d};">{status_d}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        c_d1, c_d2 = st.columns(2)
        count_p_d, count_s_d = len(df_strat1_d), len(df_strat2_d)
        val_p_d = 5 if count_p_d >= 5 else max(1, count_p_d)
        val_s_d = 5 if count_s_d >= 5 else max(1, count_s_d)
        
        with c_d1:
            col_t1, col_i1, col_r1 = st.columns([4, 2, 4])
            with col_t1: st.markdown(f"<h4 style='margin:0;'>🔥 12-1M & 6-1M <span style='font-size:13px; color:gray;'>({count_p_d}개)</span></h4>", unsafe_allow_html=True)
            with col_i1: top_n_p_d = st.number_input("p_n", 1, max(1, count_p_d), val_p_d, key="calc_p_us_d", label_visibility="collapsed")
            with col_r1:
                avg_ret_p_d = df_strat1_d.head(top_n_p_d)['이번달수익률'].mean() if count_p_d > 0 and '이번달수익률' in df_strat1_d.columns else 0
            st.markdown('<p class="strategy-desc">12-1M & 6-1M 각각 150위 이내 교집합 종목 (6-1M 순)</p>', unsafe_allow_html=True)
            
        with c_d2:
            col_t2, col_i2, col_r2 = st.columns([4, 2, 4])
            with col_t2: st.markdown(f"<h4 style='margin:0;'>🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({count_s_d}개)</span></h4>", unsafe_allow_html=True)
            with col_i2: top_n_s_d = st.number_input("s_n", 1, max(1, count_s_d), val_s_d, key="calc_s_us_d", label_visibility="collapsed")
            with col_r2:
                avg_ret_s_d = df_strat2_d.head(top_n_s_d)['이번달수익률'].mean() if count_s_d > 0 and '이번달수익률' in df_strat2_d.columns else 0
            st.markdown('<p class="strategy-desc">6-1M & 3-1M 각각 150위 이내 교집합 종목 (6-1M 순)</p>', unsafe_allow_html=True)
            
        # 💡 [해결 2] 데일리 탭도 독립적 하이라이트 분리
        sel_codes_p_d = df_strat1_d.head(top_n_p_d)['종목코드'].tolist()
        sel_codes_s_d = df_strat2_d.head(top_n_s_d)['종목코드'].tolist()
        overlap_codes_d = set(sel_codes_p_d).intersection(set(sel_codes_s_d))
        highlight_codes_all_d = list(set(sel_codes_p_d + sel_codes_s_d))

        with c_d1:
            st.dataframe(df_strat1_d.style.apply(apply_korea_styling, highlight_codes=sel_codes_p_d, overlap_codes=overlap_codes_d, axis=1), use_container_width=True, hide_index=True, column_order=col_order_d1, column_config=us_main_cfg)
        with c_d2:
            st.dataframe(df_strat2_d.style.apply(apply_korea_styling, highlight_codes=sel_codes_s_d, overlap_codes=overlap_codes_d, axis=1), use_container_width=True, hide_index=True, column_order=col_order_d2, column_config=us_main_cfg)
            
        st.markdown("<hr style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        st.markdown("### 🏆 기간별 모멘텀 상위 30위")
        
        df_12_1_d = df_us_d.sort_values('12-1개월(%)', ascending=False).head(30)
        df_6_1_d = df_us_d.sort_values('6-1개월(%)', ascending=False).head(30)
        df_3_1_d = df_us_d.sort_values('3-1개월(%)', ascending=False).head(30)
        
        for df in [df_12_1_d, df_6_1_d, df_3_1_d]: df['순위'] = range(1, 31)
            
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.markdown("#### 🥇 12-1개월 모멘텀")
            st.dataframe(df_12_1_d.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_d, overlap_codes=overlap_codes_d, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)'], column_config=us_main_cfg)
        with col_d2:
            st.markdown("#### 🥈 6-1개월 모멘텀")
            st.dataframe(df_6_1_d.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_d, overlap_codes=overlap_codes_d, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)'], column_config=us_main_cfg)
        with col_d3:
            st.markdown("#### 🥉 3-1개월 모멘텀")
            st.dataframe(df_3_1_d.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_d, overlap_codes=overlap_codes_d, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '3-1개월(%)'], column_config=us_main_cfg)

        st.markdown("---")
        st.markdown(f"### 🌐 S&P 500 전체 순위 <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span>", unsafe_allow_html=True)
        cols_d = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)']
        st.dataframe(df_us_d.style.apply(apply_korea_styling, highlight_codes=highlight_codes_all_d, overlap_codes=overlap_codes_d, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_d, column_config=us_main_cfg)

# ==========================================
# 탭 3. 전략 백테스트
# ==========================================
with tab3:
    with st.form("bt_settings_form_us", border=False):
        st.markdown("<h4 style='margin:0;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
        c1, c_ma_us, c_chk = st.columns([1.5, 1, 1.5])
        with c1: start_year, end_year = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr_us')
        with c_ma_us: ma_months_t3 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 10, key='t3_ma_us')
        with c_chk:
            st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
            apply_timing = st.checkbox("🛑 마켓타이밍 적용 (이탈 시 현금)", value=True, key='t3_chk_us')
        
        st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
        st.markdown("##### ✂️ 모멘텀 추출 및 매수 순위 설정")
        
        c_ex1, c_ex2, c_ex3, c_ex4 = st.columns([1, 1.2, 1.2, 0.8])
        with c_ex1: 
            top_n_t3 = st.number_input("🎯 교집합 추출 기준 (N위)", min_value=1, max_value=500, value=150, key='t3_n_all')
        with c_ex2: 
            rank_p_s, rank_p_e = st.slider("🔥 12-1&6-1 매수 순위", 1, 30, (1, 5), key='t3_rnk1_us')
        with c_ex3: 
            rank_s_s, rank_s_e = st.slider("🐎 6-1&3-1 매수 순위", 1, 30, (1, 5), key='t3_rnk2_us')
        with c_ex4:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            run_bt_us = st.form_submit_button("✅ 백테스트 실행", use_container_width=True)

    if run_bt_us or 'run_bt_state_us' not in st.session_state:
        st.session_state['run_bt_state_us'] = True

    if st.session_state.get('run_bt_state_us', False):
        # 💡 [해결 4] 백테스트 렌더링 속도를 극대화하는 캐싱 로직 탑재 완료
        spx_hist = get_spx_history_cached()
        
        with st.spinner("미국 모멘텀 백테스트 구동 중... (동일 조건일 경우 0.1초 렌더링)"):
            df_res, df_trades = run_backtest_us_fast(
                df_master, start_year, end_year, ma_months_t3, apply_timing, 
                (rank_p_s, rank_p_e), (rank_s_s, rank_s_e), 
                top_n_t3, top_n_t3, top_n_t3, spx_hist
            )
            if not df_res.empty:
                s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
                df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
                df_cum.loc[(pd.to_datetime(df_res['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
                df_cum = df_cum.sort_index()

                stats = []
                for col in s_cols:
                    final_val = df_cum[col].iloc[-1]
                    years = len(df_res)/12
                    cagr = ((final_val/100)**(1/years)-1)*100 if final_val > 0 else -100
                    win_rate = (df_res.loc[df_res['invested'], col]>0).mean()*100 if df_res['invested'].any() else 0
                    mdd = ((df_cum[col]/df_cum[col].cummax())-1).min()*100
                    stats.append({"전략명": col, "CAGR (연평균)": f"{cagr:.1f}%", "총 누적수익률": f"{final_val-100:,.1f}%", "MDD (최대낙폭)": f"{mdd:.1f}%", "투자월 비율": f"{(df_res['invested'].sum()/len(df_res))*100:.1f}%", "월별 승률": f"{win_rate:.1f}%", "평균 수익률": f"{df_res.loc[df_res['invested'], col].mean():.2f}%" if df_res['invested'].any() else "0.00%"})
                
                stats_df = pd.DataFrame(stats)
                
                settings_dict = {
                    '테스트 시작 연도': f"{start_year}년",
                    '테스트 종료 연도': f"{end_year}년",
                    '마켓타이밍 (개월선)': f"{ma_months_t3}개월선",
                    '마켓타이밍 적용': "적용(현금)" if apply_timing else "미적용",
                    '교집합 추출 기준': f"상위 {top_n_t3}위 이내",
                    '12-1&6-1 매수 순위': f"{rank_p_s}위 ~ {rank_p_e}위",
                    '6-1&3-1 매수 순위': f"{rank_s_s}위 ~ {rank_s_e}위"
                }

                excel_data = generate_excel_report_cached(tuple(settings_dict.items()), stats_df, df_res, df_cum, df_trades)

                col_t, col_b = st.columns([7.5, 2.5])
                with col_t: st.markdown("#### 📊 전략 핵심 통계 (초기 자본 100 기준)")
                with col_b: 
                    st.download_button("📥 종합 엑셀 리포트 다운로드", data=excel_data, file_name="US_백테스트_종합리포트.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

                st.dataframe(get_styled_stats(stats_df), use_container_width=True, hide_index=True)
                
                st.markdown("#### 🗓️ 상세 분석 (월별 수익률 히트맵 & MDD)")
                analysis_strat_t3 = st.radio("분석할 전략을 선택하세요", s_cols, horizontal=True, index=0, key="analysis_radio_t3_us")
                
                col_hm, col_mdd = st.columns([6, 4])
                with col_hm: st.dataframe(get_monthly_heatmap(df_res, analysis_strat_t3), use_container_width=True)
                with col_mdd: st.dataframe(get_mdd_history(df_cum[analysis_strat_t3]), use_container_width=True, hide_index=True)
                
                st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)"), use_container_width=True)
                with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)

# ==========================================
# 탭 4. 스코어 커스텀 백테스트
# ==========================================
with tab4:
    col_title_c, col_check_c = st.columns([1, 4])
    with col_title_c: st.markdown("<h4 style='margin:0;'>⚙️ 스코어 가중치 설정</h4>", unsafe_allow_html=True)
    with col_check_c:
        st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
        apply_timing_c = st.checkbox("🛑 마켓타이밍 적용 (이탈 시 현금)", value=True, key='t4_chk_main_us')
    
    with st.form("custom_form_us", border=False):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])
        with c1: w1 = st.number_input("📉 1개월 가중치", value=-0.1, step=0.1, format="%.1f")
        with c2: w3 = st.number_input("📈 3개월 가중치", value=0.7, step=0.1, format="%.1f")
        with c3: w6 = st.number_input("📈 6개월 가중치", value=0.4, step=0.1, format="%.1f")
        with c4: w12 = st.number_input("📈 12개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            apply_weights = st.form_submit_button("✅ 실행", use_container_width=True)
            
    st.markdown("<hr style='margin: 15px 0px;'>", unsafe_allow_html=True)
    c6, c_ma_c, c7, c8 = st.columns([1, 0.8, 1, 1])
    with c6: start_year_c, end_year_c = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t4_yr_us')
    with c_ma_c: ma_months_t4 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 10, key='t4_ma_us')
    with c7: custom_pct = st.slider("🏅 상위 % 커트라인", 5, 50, 30, step=5, key='t4_pct_us')
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위", 1, 30, (1, 10), key='t4_rnk_us')

    if apply_weights or 'custom_run_us' not in st.session_state: st.session_state['custom_run_us'] = True
    if st.session_state.get('custom_run_us', False):
        with st.spinner("미국 커스텀 시뮬레이션 중..."):
            df_res_c, df_trades_c = run_custom_backtest_us(df_master, start_year_c, end_year_c, ma_months_t4, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)
            if not df_res_c.empty:
                df_cum_c = (1 + df_res_c.set_index('투자월')[['커스텀 전략']] / 100).cumprod() * 100
                df_cum_c.loc[(pd.to_datetime(df_res_c['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
                df_cum_c = df_cum_c.sort_index()

                col_tc, col_bc = st.columns([7.5, 2.5])
                with col_tc: st.markdown("#### 📊 전략 핵심 통계")
                with col_bc: st.download_button("📥 상세내역 다운로드", df_trades_c.to_csv(index=False).encode('utf-8-sig'), "US_커스텀_백테스트.csv", "text/csv", use_container_width=True)

                final_val_c = df_cum_c['커스텀 전략'].iloc[-1]
                years_c = len(df_res_c) / 12
                cagr_c = ((final_val_c/100)**(1/years_c)-1)*100 if final_val_c > 0 else -100
                mdd_c = ((df_cum_c['커스텀 전략']/df_cum_c['커스텀 전략'].cummax())-1).min()*100
                stats_c = [{"전략명": "커스텀 스코어", "CAGR (연평균)": f"{cagr_c:.1f}%", "총 누적수익률": f"{final_val_c-100:,.1f}%", "MDD (최대낙폭)": f"{mdd_c:.1f}%", "투자월 비율": f"{(df_res_c['invested'].sum()/len(df_res_c))*100:.1f}%", "월별 승률": f"{(df_res_c.loc[df_res_c['invested'], '커스텀 전략']>0).mean()*100:.1f}%" if df_res_c['invested'].any() else "0.0%", "평균 수익률": f"{df_res_c.loc[df_res_c['invested'], '커스텀 전략'].mean():.2f}%" if df_res_c['invested'].any() else "0.00%"}]
                st.dataframe(get_styled_stats(pd.DataFrame(stats_c)), use_container_width=True, hide_index=True)
                
                col_hm_c, col_mdd_c = st.columns([6, 4])
                with col_hm_c: st.dataframe(get_monthly_heatmap(df_res_c, '커스텀 전략'), use_container_width=True)
                with col_mdd_c: st.dataframe(get_mdd_history(df_cum_c['커스텀 전략']), use_container_width=True, hide_index=True)

                st.plotly_chart(px.line(df_cum_c.reset_index(), x='투자월', y='커스텀 전략', log_y=True, title="커스텀 누적 성과"), use_container_width=True)
                with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res_c.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)
