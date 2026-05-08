import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="USA 300 통합 모멘텀", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS
from utils.ui_components import inject_custom_css, apply_korea_styling, style_kospi_ma, get_styled_stats, get_mdd_history, get_monthly_heatmap, ma_cfg, main_cfg

from utils.us_helpers import (
    preprocess_us_data, add_naver_links, robust_get_us_ma_all, robust_get_us_idx_return, 
    get_spx_history_cached, generate_excel_report_cached, 
    get_strategy_stocks_us_custom, run_backtest_us_fast, run_custom_backtest_us
)

inject_custom_css()

# 전체 순위 하이라이트 스타일링 (파스텔 옐로우)
def apply_custom_total_styling(row, top_codes):
    styles = []
    is_top = row['종목코드'] in top_codes
    for col, val in row.items():
        style = ''
        if is_top and col == '종목명_L':
            style += 'background-color: #FFF9C4; font-weight: bold; color: #333;' 
            
        if isinstance(col, str) and ('(%)' in col or col == '커스텀스코어' or '수익률' in col):
            try:
                v = float(val)
                if v > 0: style += 'color: #D32F2F;'
                elif v < 0: style += 'color: #1976D2;'
            except: pass
        styles.append(style)
    return styles

@st.cache_data(show_spinner=False)
def cached_run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    return run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)

st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="https://m.stock.naver.com/worldstock/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
                <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">🇺🇸 USA 300 통합 모멘텀 (Top 300)</h1>
                <span style="font-size: 0.95rem; color: #10b981; background-color: #d1fae5; padding: 4px 10px; border-radius: 6px; border: 1px solid #6ee7b7; white-space: nowrap;">🔗 네이버 증권 이동</span>
            </div>
        </a>
    </div>
''', unsafe_allow_html=True)

# 💡 [데이터 로드 부분]
archive_path = "archive_usa"
f_hash = get_folder_hash(archive_path) 
df_master_raw = load_archive_data(archive_path, f_hash) 

if df_master_raw.empty:
    st.error(f"🚨 {archive_path} 폴더에 데이터가 없습니다! (현재 경로: {os.getcwd()})")
    st.info("팁: GitHub에 Push 하셨다면 Streamlit 페이지에서 'C'를 눌러 캐시를 비워보세요.")
    st.stop()

# 선생님이 컬럼명을 이미 맞췄으므로 전처리만 수행합니다.
df_master = preprocess_us_data(df_master_raw, is_daily=False)

valid_years = df_master['투자연도'].dropna().unique().astype(int).tolist()
years_list = sorted(valid_years)
min_y, max_y = (min(years_list), max(years_list)) if years_list else (2026, 2026)

us_main_cfg = main_cfg.copy()
us_main_cfg.update({
    '12-1개월(%)': st.column_config.NumberColumn('12-1개월(%)', format="%.2f%%"),
    '6-1개월(%)': st.column_config.NumberColumn('6-1개월(%)', format="%.2f%%"),
    '3-1개월(%)': st.column_config.NumberColumn('3-1개월(%)', format="%.2f%%"),
    '커스텀스코어': st.column_config.NumberColumn('커스텀스코어', format="%.2f"),
    '종가': st.column_config.NumberColumn('종가', format="%.2f"),
    '시가총액': st.column_config.NumberColumn('시가총액', format="%d")
})

col_order_strat1 = ['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)', '이번달수익률']
col_order_strat2 = ['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)', '이번달수익률']
cols_m = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '커스텀스코어', '이번달수익률']

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트", "🏅 스코어 커스텀 백테스트"])

with tab1:
    avail_years = [str(y) for y in sorted(years_list, reverse=True)]
    c_y, c_m = st.columns([1.2, 8.8])
    with c_y: 
        selected_year = st.selectbox("투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y_usa")
    
    safe_year = int(float(selected_year)) if selected_year else datetime.today().year
    m_list = sorted(df_master[df_master['투자연도'] == safe_year]['투자월'].astype(str).apply(lambda x: x.split('-')[1] if '-' in x else x).unique())
    default_m_index = len(m_list) - 1 if len(m_list) > 0 else 0

    with c_m:
        month_label = st.empty()
        if m_list:
            selected_month = st.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m_usa", index=default_m_index)
            target_month_str = f"{safe_year}-{selected_month}"
            df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
        else:
            df_monthly = pd.DataFrame()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        month_label.markdown(f"**기준 선정일:** {base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else base_date}")

        spx_curr, spx_mas = robust_get_us_ma_all(base_date, '^GSPC')
        ma_df = pd.DataFrame([{'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)}])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_monthly = add_naver_links(df_monthly)
        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us_custom(df_monthly, 150, 150, 150)
        
        df_us_t1['커스텀스코어'] = (-0.1 * df_us_t1['1개월(%)']) + (0.7 * df_us_t1['3개월(%)']) + (0.4 * df_us_t1['6개월(%)'])
        df_us_t1 = df_us_t1.sort_values('커스텀스코어', ascending=False)
        df_us_t1['순위'] = range(1, len(df_us_t1) + 1)
        
        c_l, c_r = st.columns(2)
        with c_l:
            st.markdown("#### 🔥 12-1M & 6-1M")
            st.dataframe(df_strat1_t1.head(10).style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat1, column_config=us_main_cfg)
        with c_r:
            st.markdown("#### 🐎 6-1M & 3-1M")
            st.dataframe(df_strat2_t1.head(10).style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat2, column_config=us_main_cfg)

        st.markdown("---")
        col_total_t, col_total_i, col_total_r = st.columns([5.3, 2.8, 3.9])
        with col_total_t: st.markdown("### 🌐 USA 300 전체 순위")
        with col_total_i: top_n_total = st.number_input("N위 하이라이트", 1, len(df_us_t1), 10, key="top_n_usa")
        with col_total_r:
            avg_ret = df_us_t1.head(top_n_total)['이번달수익률'].mean()
            st.markdown(f"**상위 {top_n_total}개 평균:** <span style='color:{'red' if avg_ret>0 else 'blue'};'>{avg_ret:+.2f}%</span>", unsafe_allow_html=True)
            
        top_codes = df_us_t1.head(top_n_total)['종목코드'].tolist()
        st.dataframe(df_us_t1.style.apply(apply_custom_total_styling, top_codes=top_codes, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_m, column_config=us_main_cfg)

# (나머지 탭들은 데이터가 로드된 후에 정상 작동합니다.)
