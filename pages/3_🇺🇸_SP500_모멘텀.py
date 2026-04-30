import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import FinanceDataReader as fdr

st.set_page_config(page_title="S&P 500 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS
from utils.ui_components import inject_custom_css, apply_korea_styling, style_kospi_ma, get_styled_stats, get_mdd_history, get_monthly_heatmap, ma_cfg, main_cfg

inject_custom_css()

# 💡 [미국용] 미국 지수 이동평균선 및 수익률 계산 함수
@st.cache_data(ttl=3600)
def get_us_ma_all(target_date_str, ticker='^GSPC'):
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=450)
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start_date, end=target_date + timedelta(days=1), progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty: return 0, {}
        
        curr_p = df['Close'].iloc[-1]
        mas = {
            4: round(df['Close'].rolling(80).mean().iloc[-1], 2),
            5: round(df['Close'].rolling(100).mean().iloc[-1], 2),
            6: round(df['Close'].rolling(120).mean().iloc[-1], 2),
            10: round(df['Close'].rolling(200).mean().iloc[-1], 2),
            12: round(df['Close'].rolling(240).mean().iloc[-1], 2)
        }
        return curr_p, mas
    except: return 0, {}

@st.cache_data(ttl=3600)
def get_us_idx_return(target_date_str, ticker='^GSPC'):
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=120)
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start_date, end=target_date + timedelta(days=1), progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        if df.empty: return 0.0, 0.0
        
        curr_p = df['Close'].iloc[-1]
        
        df_1m = df[df.index <= target_date - pd.DateOffset(months=1)]
        ret_1m = round(((curr_p / df_1m['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m.empty else 0.0
        
        df_3m = df[df.index <= target_date - pd.DateOffset(months=3)]
        ret_3m = round(((curr_p / df_3m['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m.empty else 0.0
        
        return ret_1m, ret_3m
    except: return 0.0, 0.0

# 💡 [미국용] (x개월 - 1개월) 모멘텀 계산
def calc_us_momentum(df):
    df_calc = df.copy()
    for m in [3, 6, 12]:
        col_m = f'{m}개월(%)'
        col_1 = '1개월(%)'
        if col_m in df_calc.columns and col_1 in df_calc.columns:
            # (1 + M개월수익률) / (1 + 1개월수익률) - 1
            df_calc[f'{m}-1개월(%)'] = ((1 + df_calc[col_m]/100) / (1 + df_calc[col_1]/100) - 1) * 100
        else:
            df_calc[f'{m}-1개월(%)'] = 0.0
    return df_calc

def get_strategy_stocks_us(df_month, top_pct=30):
    df_calc = calc_us_momentum(df_month)
    
    q12_1 = df_calc['12-1개월(%)'].quantile(1 - top_pct/100)
    q6_1  = df_calc['6-1개월(%)'].quantile(1 - top_pct/100)
    q3_1  = df_calc['3-1개월(%)'].quantile(1 - top_pct/100)
    
    cond1 = (df_calc['12-1개월(%)'] >= q12_1) & (df_calc['6-1개월(%)'] >= q6_1) & (df_calc['12-1개월(%)'] > 0) & (df_calc['6-1개월(%)'] > 0)
    strat1 = df_calc[cond1].sort_values('6-1개월(%)', ascending=False)
    
    cond2 = (df_calc['6-1개월(%)'] >= q6_1) & (df_calc['3-1개월(%)'] >= q3_1) & (df_calc['6-1개월(%)'] > 0) & (df_calc['3-1개월(%)'] > 0)
    strat2 = df_calc[cond2].sort_values('3-1개월(%)', ascending=False)
    
    return df_calc, strat1, strat2

# 💡 [미국용] 영어 컬럼 자동 매핑 함수
def map_english_columns(df):
    col_mapping = {
        'Date': '종목선정일', 'Year': '투자연도', 'Ticker': '종목코드', 'Close_Price': '종가',
        'Past_1M_Return(%)': '1개월(%)', 'Past_3M_Return(%)': '3개월(%)', 
        'Past_6M_Return(%)': '6개월(%)', 'Past_12M_Return(%)': '12개월(%)', 
        'Forward_1M_Return(%)': '이번달수익률'
    }
    df = df.rename(columns=col_mapping)
    if '종목명' not in df.columns and '종목코드' in df.columns: df['종목명'] = df['종목코드']
    if '시가총액' not in df.columns: df['시가총액'] = 0
    if '거래량' not in df.columns: df['거래량'] = 0
    if '투자월' not in df.columns and '종목선정일' in df.columns:
        df['투자월'] = pd.to_datetime(df['종목선정일']).dt.strftime('%Y-%m')
        df['투자연도'] = pd.to_datetime(df['종목선정일']).dt.year
    return df

st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="https://finance.yahoo.com/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
                <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">🇺🇸 S&P 500 모멘텀 터미널</h1>
                <span style="font-size: 0.95rem; color: #3b82f6; background-color: #eff6ff; padding: 4px 10px; border-radius: 6px; border: 1px solid #bfdbfe; white-space: nowrap;">🔗 Yahoo Finance 이동</span>
            </div>
        </a>
    </div>
''', unsafe_allow_html=True)

archive_path = "archive_sp500"
f_hash = get_folder_hash(archive_path) 
df_master = load_archive_data(archive_path, f_hash) 
f_daily = 'data/momentum_data_daily_sp500.csv'

if df_master.empty:
    st.error("🚨 archive_sp500 폴더에 데이터가 없습니다!")
    st.stop()

# 💡 영어 칼럼을 한국어로 매핑 (Zfill 같은 한국주식 코드는 적용 안 함)
df_master = map_english_columns(df_master)

target_cols = ['시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']
for col in target_cols:
    if col in df_master.columns:
        df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

us_main_cfg = main_cfg.copy()
us_main_cfg.update({
    '12-1개월(%)': st.column_config.NumberColumn('12-1개월(%)', format="%.2f%%"),
    '6-1개월(%)': st.column_config.NumberColumn('6-1개월(%)', format="%.2f%%"),
    '3-1개월(%)': st.column_config.NumberColumn('3-1개월(%)', format="%.2f%%")
})

# 💡 [미국용] 백테스트 함수 (S&P500 200일선 적용)
@st.cache_data(show_spinner=False)
def cached_run_backtest_us(df, start_year, end_year, apply_timing, rank_s1, rank_s2, top_pct):
    import yfinance as yf
    try:
        spx = yf.download('^GSPC', start=f'{start_year-2}-01-01', end=f'{end_year}-12-31', progress=False)
        if isinstance(spx.columns, pd.MultiIndex): spx.columns = spx.columns.get_level_values(0)
        spx['MA200'] = spx['Close'].rolling(200).mean()
        spx['Is_Below'] = spx['Close'] < spx['MA200']
    except:
        spx = pd.DataFrame()

    timing_dict = {}
    for m_str in sorted(df['투자월'].dropna().unique()):
        base_date = pd.to_datetime(df[df['투자월'] == m_str]['종목선정일'].iloc[0])
        if not spx.empty:
            past_spx = spx[spx.index <= base_date]
            timing_dict[m_str] = past_spx.iloc[-1]['Is_Below'] if not past_spx.empty else False
        else: timing_dict[m_str] = False

    records, trade_logs = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        
        df_calc = df[df['투자월'] == m_str].copy()
        if df_calc.empty: continue
        
        df_calc = calc_us_momentum(df_calc)
        
        q12_1 = df_calc['12-1개월(%)'].quantile(1 - top_pct/100)
        q6_1  = df_calc['6-1개월(%)'].quantile(1 - top_pct/100)
        q3_1  = df_calc['3-1개월(%)'].quantile(1 - top_pct/100)
        
        cond1 = (df_calc['12-1개월(%)'] >= q12_1) & (df_calc['6-1개월(%)'] >= q6_1) & (df_calc['12-1개월(%)'] > 0) & (df_calc['6-1개월(%)'] > 0)
        strat1_df = df_calc[cond1].sort_values('6-1개월(%)', ascending=False).iloc[rank_s1[0]-1:rank_s1[1]]
        
        cond2 = (df_calc['6-1개월(%)'] >= q6_1) & (df_calc['3-1개월(%)'] >= q3_1) & (df_calc['6-1개월(%)'] > 0) & (df_calc['3-1개월(%)'] > 0)
        strat2_df = df_calc[cond2].sort_values('3-1개월(%)', ascending=False).iloc[rank_s2[0]-1:rank_s2[1]]
        
        is_below_ma = timing_dict.get(m_str, False)
        mult = 0.0 if (apply_timing and is_below_ma) else 1.0
        
        ret1 = strat1_df['이번달수익률'].mean() * mult if not strat1_df.empty else 0
        ret2 = strat2_df['이번달수익률'].mean() * mult if not strat2_df.empty else 0
        
        s1_codes, s2_codes = set(strat1_df['종목코드']), set(strat2_df['종목코드'])
        all_codes = s1_codes.union(s2_codes)
        ret_combined_excl = df_calc[df_calc['종목코드'].isin(all_codes)]['이번달수익률'].mean() * mult if all_codes else 0
        
        sum_ret = strat1_df['이번달수익률'].sum() + strat2_df['이번달수익률'].sum()
        total_len = len(strat1_df) + len(strat2_df)
        ret_combined_incl = (sum_ret / total_len * mult) if total_len > 0 else 0
        
        records.append({
            '투자월': m_str, 'invested': mult > 0,
            f'🔥 12-1M & 6-1M ({rank_s1[0]}~{rank_s1[1]}위)': ret1,
            f'🐎 6-1M & 3-1M ({rank_s2[0]}~{rank_s2[1]}위)': ret2,
            '앙상블 (50:50 전략)': (ret1 * 0.5) + (ret2 * 0.5),
            '통합 전략 (중복 제외 1/N)': ret_combined_excl,
            '통합 전략 (중복 인정 1/N)': ret_combined_incl
        })
        
        if mult > 0:
            for i, (_, r) in enumerate(strat1_df.iterrows()): trade_logs.append({'투자월': m_str, '전략': '12-1M & 6-1M', '순위': f"{i+rank_s1[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
            for i, (_, r) in enumerate(strat2_df.iterrows()): trade_logs.append({'투자월': m_str, '전략': '6-1M & 3-1M', '순위': f"{i+rank_s2[0]}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
        else:
            trade_logs.append({'투자월': m_str, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)


tab1, tab2, tab3 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트"])

with tab1:
    avail_years = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    c_y, c_m = st.columns([1.2, 8.8])
    with c_y: 
        st.markdown("<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>📅 투자 연도</b></div>", unsafe_allow_html=True)
        selected_year = st.selectbox("투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y", label_visibility="collapsed")
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    default_m_index = len(m_list) - 1 
    with c_m:
        month_label = st.empty()
        selected_month = st.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m", label_visibility="collapsed", index=default_m_index)

    target_month_str = f"{selected_year}-{selected_month}"
    df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        month_label.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🌙 투자 월</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 선정일: {base_date}</span></div>", unsafe_allow_html=True)

        spx_curr, spx_mas = get_us_ma_all(base_date, '^GSPC')
        ndx_curr, ndx_mas = get_us_ma_all(base_date, '^IXIC')
        ma_df = pd.DataFrame([
            {'지수_L': "https://finance.yahoo.com/quote/%5EGSPC#S&P500", '현재가_L': f"https://finance.yahoo.com/quote/%5EGSPC#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)},
            {'지수_L': "https://finance.yahoo.com/quote/%5EIXIC#NASDAQ", '현재가_L': f"https://finance.yahoo.com/quote/%5EIXIC#{ndx_curr:,.2f}", 'base_price': round(ndx_curr, 2), '4개월선': ndx_mas.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us(df_monthly, top_pct=30)
        
        spx_1m, spx_3m = get_us_idx_return(base_date, '^GSPC')
        ndx_1m, ndx_3m = get_us_idx_return(base_date, '^IXIC')
        
        df_strat1_t1['순위'] = range(1, len(df_strat1_t1) + 1)
        df_strat2_t1['순위'] = range(1, len(df_strat2_t1) + 1)
        df_us_t1 = df_us_t1.sort_values('시가총액', ascending=False) if '시가총액' in df_us_t1.columns else df_us_t1
        df_us_t1['순위'] = range(1, len(df_us_t1) + 1)

        cycle_year_t1 = get_cycle_year(int(selected_year))
        bad_m_str_t1 = ", ".join(f"{m}월" for m in PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year_t1, [])) or "없음"
        
        # 💡 [미국 시장타이밍] S&P 500 200일(10개월)선 하향 이탈 시 투자 중단
        is_below_ma = (spx_curr > 0) and (spx_curr < spx_mas.get(10, 0))
        status, box_c, text_c = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below_ma else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc = "S&P500 200일선 이탈" if is_below_ma else "안전"

        col1, col2, col3, col4, col5, col6 = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric("📈 S&P 500 1M", f"{spx_1m}%")
        with col2: st.metric("📈 S&P 500 3M", f"{spx_3m}%")
        with col3: st.metric("📈 NASDAQ 1M", f"{ndx_1m}%")
        with col4: st.metric("📈 NASDAQ 3M", f"{ndx_3m}%")
        with col5: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 12px; font-weight: bold; color: #64748b; margin-bottom: 2px;">🇺🇸대통령 <span style="color:#0047AB;">{cycle_year_t1}년차</span> ({selected_year}년)</div><div style="font-size: 16px; color: #D84315; font-weight:900;">🚨 위험달: {bad_m_str_t1}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_c}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_c}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_c}; font-weight: bold;">최종 판단 ({reason_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_c};">{status}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_strat1_t1, df_strat2_t1, df_us_t1]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.yahoo.com/quote/{r['종목코드']}#{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://finance.yahoo.com/quote/{r['종목코드']}#{r['종목명']}", axis=1)

        c_l, c_r = st.columns(2)
        count_p, count_s = len(df_strat1_t1), len(df_strat2_t1)
        with c_l:
            col_t1, col_i1, col_r1 = st.columns([4, 2, 4])
            with col_t1: st.markdown(f"<h4 style='margin:0;'>🔥 12-1M & 6-1M <span style='font-size:13px; color:gray;'>({count_p}개)</span></h4>", unsafe_allow_html=True)
            with col_i1: top_n_p = st.number_input("p_n", 1, max(1, count_p), min(6, count_p) if count_p > 0 else 1, key="calc_p", label_visibility="collapsed")
            with col_r1:
                avg_ret_p = df_strat1_t1.head(top_n_p)['이번달수익률'].mean() if count_p > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_p}개 평균: <span style='color:{'#D32F2F' if avg_ret_p>0 else '#1976D2'};'>{avg_ret_p:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12-1M & 6-1M 모두 상위 30% 이내 & 0보다 큰 종목 (6-1M 순)</p>', unsafe_allow_html=True)
            
        with c_r:
            col_t2, col_i2, col_r2 = st.columns([4, 2, 4])
            with col_t2: st.markdown(f"<h4 style='margin:0;'>🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({count_s}개)</span></h4>", unsafe_allow_html=True)
            with col_i2: top_n_s = st.number_input("s_n", 1, max(1, count_s), min(2, count_s) if count_s > 0 else 1, key="calc_s", label_visibility="collapsed")
            with col_r2:
                avg_ret_s = df_strat2_t1.head(top_n_s)['이번달수익률'].mean() if count_s > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_s}개 평균: <span style='color:{'#D32F2F' if avg_ret_s>0 else '#1976D2'};'>{avg_ret_s:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">6-1M & 3-1M 모두 상위 30% 이내 & 0보다 큰 종목 (3-1M 순)</p>', unsafe_allow_html=True)

        overlap_codes = set(df_strat1_t1.head(top_n_p)['종목코드']).intersection(set(df_strat2_t1.head(top_n_s)['종목코드']))
        
        with c_l:
            st.dataframe(df_strat1_t1.style.apply(apply_korea_styling, highlight_codes=df_strat1_t1.head(top_n_p)['종목코드'].tolist(), overlap_codes=overlap_codes, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)', '이번달수익률'], column_config=us_main_cfg)
        with c_r:
            st.dataframe(df_strat2_t1.style.apply(apply_korea_styling, highlight_codes=df_strat2_t1.head(top_n_s)['종목코드'].tolist(), overlap_codes=overlap_codes, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)', '이번달수익률'], column_config=us_main_cfg)

        st.markdown("<hr style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        st.markdown("### 🏆 기간별 모멘텀 상위 30위")
        
        df_12_1 = df_us_t1.sort_values('12-1개월(%)', ascending=False).head(30)
        df_6_1 = df_us_t1.sort_values('6-1개월(%)', ascending=False).head(30)
        df_3_1 = df_us_t1.sort_values('3-1개월(%)', ascending=False).head(30)
        
        for df in [df_12_1, df_6_1, df_3_1]: df['순위'] = range(1, 31)
            
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.markdown("#### 🥇 12-1개월 모멘텀")
            st.dataframe(df_12_1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)'], column_config=us_main_cfg)
        with col_m2:
            st.markdown("#### 🥈 6-1개월 모멘텀")
            st.dataframe(df_6_1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)'], column_config=us_main_cfg)
        with col_m3:
            st.markdown("#### 🥉 3-1개월 모멘텀")
            st.dataframe(df_3_1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '3-1개월(%)'], column_config=us_main_cfg)

        st.markdown("---")
        st.markdown(f"### 🌐 S&P 500 전체 순위 <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 선정일: {base_date}</span>", unsafe_allow_html=True)
        cols_m = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '이번달수익률']
        st.dataframe(df_us_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_m, column_config=us_main_cfg)

with tab2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily)
        df_daily = map_english_columns(df_daily)
        
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        safe_date = b_date_d if b_date_d != "오늘" else datetime.today().strftime('%Y-%m-%d')
        
        for col in ['시가총액', '종가', '거래량']:
            if col in df_daily.columns:
                df_daily[col] = pd.to_numeric(df_daily[col], errors='coerce').fillna(0)
                
        if '시가총액' in df_daily.columns and df_daily['시가총액'].max() > 10000000:
            df_daily['시가총액'] = df_daily['시가총액'] / 100000000
        
        st.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        
        spx_curr_d, spx_mas_d = get_us_ma_all(safe_date, '^GSPC')
        ndx_curr_d, ndx_mas_d = get_us_ma_all(safe_date, '^IXIC')
        ma_df_d = pd.DataFrame([
            {'지수_L': "https://finance.yahoo.com/quote/%5EGSPC#S&P500", '현재가_L': f"https://finance.yahoo.com/quote/%5EGSPC#{spx_curr_d:,.2f}", 'base_price': round(spx_curr_d, 2), '4개월선': spx_mas_d.get(4, 0), '5개월선': spx_mas_d.get(5, 0), '6개월선': spx_mas_d.get(6, 0), '10개월선': spx_mas_d.get(10, 0), '12개월선': spx_mas_d.get(12, 0)},
            {'지수_L': "https://finance.yahoo.com/quote/%5EIXIC#NASDAQ", '현재가_L': f"https://finance.yahoo.com/quote/%5EIXIC#{ndx_curr_d:,.2f}", 'base_price': round(ndx_curr_d, 2), '4개월선': ndx_mas_d.get(4, 0), '5개월선': ndx_mas_d.get(5, 0), '6개월선': ndx_mas_d.get(6, 0), '10개월선': ndx_mas_d.get(10, 0), '12개월선': ndx_mas_d.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_us_d, df_strat1_d, df_strat2_d = get_strategy_stocks_us(df_daily, top_pct=30)
        spx_1m_d, spx_3m_d = get_us_idx_return(safe_date, '^GSPC')
        ndx_1m_d, ndx_3m_d = get_us_idx_return(safe_date, '^IXIC')
        
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
        
        vix_html = f'''
        <a href="https://m.stock.naver.com/worldstock/index/.VIX/total" target="_blank" style="text-decoration: none; color: inherit;">
            <div class="title-link" style="background-color: {vix_bg}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {vix_border}; height: 95px; display: flex; flex-direction: column; justify-content: center;">
                <div style="font-size: 12px; font-weight: bold; color: {vix_title_color}; margin-bottom: 2px;">{vix_icon} VIX 35 돌파</div>
                <div style="font-size: 11px; font-weight: bold; color: {vix_title_color}; margin-bottom: 4px;">VIX {vix_35_high} - {vix_35_date_str}돌파 ({days_diff_str})</div>
                <div style="font-size: 15px; color: {vix_val_color}; font-weight:900;">{vix_label} {vix_latest_high}</div>
            </div>
        </a>'''
        
        with col5d: st.markdown(vix_html, unsafe_allow_html=True)
        with col6d: st.markdown(f'<div style="background-color: {box_d}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_d}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_d}; font-weight: bold;">오늘의 시장 상태 ({reason_desc_d})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_d};">{status_d}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_strat1_d, df_strat2_d, df_us_d]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.yahoo.com/quote/{r['종목코드']}#{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://finance.yahoo.com/quote/{r['종목코드']}#{r['종목명']}", axis=1)

        c_d1, c_d2 = st.columns(2)
        overlap_d = set(df_strat1_d.head(top_n_p)['종목코드']).intersection(set(df_strat2_d.head(top_n_s)['종목코드']))
        
        with c_d1:
            st.markdown(f"<h4 style='margin:0;'>🔥 12-1M & 6-1M <span style='font-size:13px; color:gray;'>({len(df_strat1_d)}개)</span></h4>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12-1M & 6-1M 모두 상위 30% 이내 & 0보다 큰 종목 (6-1M 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_strat1_d.style.apply(apply_korea_styling, highlight_codes=df_strat1_d.head(top_n_p)['종목코드'].tolist(), overlap_codes=overlap_d, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)'], column_config=us_main_cfg)
        with c_d2:
            st.markdown(f"<h4 style='margin:0;'>🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({len(df_strat2_d)}개)</span></h4>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">6-1M & 3-1M 모두 상위 30% 이내 & 0보다 큰 종목 (3-1M 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_strat2_d.style.apply(apply_korea_styling, highlight_codes=df_strat2_d.head(top_n_s)['종목코드'].tolist(), overlap_codes=overlap_d, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)'], column_config=us_main_cfg)
            
        st.markdown("<hr style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        st.markdown("### 🏆 기간별 모멘텀 상위 30위")
        
        df_12_1_d = df_us_d.sort_values('12-1개월(%)', ascending=False).head(30)
        df_6_1_d = df_us_d.sort_values('6-1개월(%)', ascending=False).head(30)
        df_3_1_d = df_us_d.sort_values('3-1개월(%)', ascending=False).head(30)
        
        for df in [df_12_1_d, df_6_1_d, df_3_1_d]: df['순위'] = range(1, 31)
            
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.markdown("#### 🥇 12-1개월 모멘텀")
            st.dataframe(df_12_1_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)'], column_config=us_main_cfg)
        with col_d2:
            st.markdown("#### 🥈 6-1개월 모멘텀")
            st.dataframe(df_6_1_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)'], column_config=us_main_cfg)
        with col_d3:
            st.markdown("#### 🥉 3-1개월 모멘텀")
            st.dataframe(df_3_1_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '3-1개월(%)'], column_config=us_main_cfg)

        st.markdown("---")
        st.markdown(f"### 🌐 S&P 500 전체 순위 <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span>", unsafe_allow_html=True)
        cols_d = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)']
        st.dataframe(df_us_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_d, column_config=us_main_cfg)

with tab3:
    st.markdown("<h4 style='margin:0;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
    c1, c_chk = st.columns([2, 1.5])
    with c1: start_year, end_year = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr')
    with c_chk:
        st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
        apply_timing = st.checkbox("🛑 마켓타이밍 적용 (S&P 500 200일선 이탈 시 현금)", value=True, key='t3_chk')
    
    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
    c2, c3, c4, c5 = st.columns([1, 1, 1, 1])
    with c2: perf_pct_t3 = st.slider("🔥 상위 % 커트라인", 5, 50, 30, step=5)
    with c3: rank_p_s, rank_p_e = st.slider("🔥 12M & 6M 매수 순위", 1, 30, (1, 6))
    with c4: st.empty()
    with c5: rank_s_s, rank_s_e = st.slider("🐎 6M & 3M 매수 순위", 1, 30, (1, 2))

    with st.spinner("미국 모멘텀 백테스트 구동 중..."):
        df_res, df_trades = cached_run_backtest_us(df_master, start_year, end_year, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e), perf_pct_t3)
        if not df_res.empty:
            s_cols_raw = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols_raw] / 100).cumprod() * 100
            df_cum.loc[(pd.to_datetime(df_res['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
            df_cum = df_cum.sort_index()

            col_t, col_b = st.columns([7.5, 2.5])
            with col_t: st.markdown("#### 📊 전략 핵심 통계 (초기 자본 100 기준)")
            with col_b: st.download_button("📥 상세내역 다운로드", df_trades.to_csv(index=False).encode('utf-8-sig'), "US_조합_백테스트.csv", "text/csv", use_container_width=True)

            stats = []
            for col in s_cols_raw:
                final_val = df_cum[col].iloc[-1]
                years = len(df_res)/12
                cagr = ((final_val/100)**(1/years)-1)*100 if final_val > 0 else -100
                win_rate = (df_res.loc[df_res['invested'], col]>0).mean()*100 if df_res['invested'].any() else 0
                mdd = ((df_cum[col]/df_cum[col].cummax())-1).min()*100
                stats.append({"전략명": col, "CAGR (연평균)": f"{cagr:.1f}%", "총 누적수익률": f"{final_val-100:,.1f}%", "MDD (최대낙폭)": f"{mdd:.1f}%", "투자월 비율": f"{(df_res['invested'].sum()/len(df_res))*100:.1f}%", "월별 승률": f"{win_rate:.1f}%", "평균 수익률": f"{df_res.loc[df_res['invested'], col].mean():.2f}%" if df_res['invested'].any() else "0.00%"})
            
            st.dataframe(get_styled_stats(pd.DataFrame(stats)), use_container_width=True, hide_index=True)
            
            st.markdown("#### 🗓️ 상세 분석 (월별 수익률 히트맵 & MDD)")
            analysis_strat_t3 = st.radio("분석할 전략을 선택하세요", s_cols_raw, horizontal=True, index=0, key="analysis_radio_t3")
            
            col_hm, col_mdd = st.columns([6, 4])
            with col_hm: st.dataframe(get_monthly_heatmap(df_res, analysis_strat_t3), use_container_width=True)
            with col_mdd: st.dataframe(get_mdd_history(df_cum[analysis_strat_t3]), use_container_width=True, hide_index=True)
            
            st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)"), use_container_width=True)
            with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)
