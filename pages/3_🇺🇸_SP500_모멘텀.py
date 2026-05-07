import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="US S&P 500 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS
from utils.ui_components import inject_custom_css, apply_korea_styling, style_kospi_ma, get_styled_stats, get_mdd_history, get_monthly_heatmap, ma_cfg, main_cfg

from utils.us_helpers import (
    preprocess_us_data, add_naver_links, robust_get_us_ma_all, robust_get_us_idx_return, 
    get_spx_history_cached, generate_excel_report_cached, 
    get_strategy_stocks_us_custom, run_backtest_us_fast, run_custom_backtest_us
)

inject_custom_css()

# 💡 [핵심 수정] 전체 순위표에서 '종목명'에만 눈이 편안한 파스텔 옐로우 적용
def apply_custom_total_styling(row, top_codes):
    styles = []
    is_top = row['종목코드'] in top_codes
    for col, val in row.items():
        style = ''
        if is_top and col == '종목명_L':
            style += 'background-color: #FFF9C4; font-weight: bold;'
            
        if isinstance(col, str) and ('(%)' in col or col == '커스텀스코어' or '수익률' in col):
            try:
                v = float(val)
                if v > 0:
                    style += 'color: #D32F2F;'
                elif v < 0:
                    style += 'color: #1976D2;'
            except:
                pass
        styles.append(style)
    return styles

@st.cache_data(show_spinner=False)
def cached_run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    return run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)

def render_vix_widget(safe_date):
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
        
    vix_bg = "#FFF0F0" if is_vix_warning else "#FFFFFF"
    vix_border = "#FFCDD2" if is_vix_warning else "#d1d5db"
    vix_title_color = "#C62828" if is_vix_warning else "#64748b"
    vix_val_color = "#D84315" if is_vix_warning else "#333333"
    vix_icon = "🚨" if is_vix_warning else "📊"
    vix_label = f"전일 ({vix_latest_date_str}일) 고가:" if vix_latest_date_str else "전일 고가:"
    
    return f'''<a href="https://m.stock.naver.com/worldstock/index/.VIX/total" target="_blank" style="text-decoration: none; color: inherit;">
        <div class="title-link" style="background-color: {vix_bg}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {vix_border}; height: 95px; display: flex; flex-direction: column; justify-content: center;">
            <div style="font-size: 12px; font-weight: bold; color: {vix_title_color}; margin-bottom: 2px;">{vix_icon} VIX 35 돌파</div>
            <div style="font-size: 11px; font-weight: bold; color: {vix_title_color}; margin-bottom: 4px;">VIX {vix_35_high} - {vix_35_date_str}돌파 ({days_diff_str})</div>
            <div style="font-size: 15px; color: {vix_val_color}; font-weight:900;">{vix_label} {vix_latest_high}</div>
        </div></a>'''

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
f_hash = get_folder_hash(archive_path) 
df_master_raw = load_archive_data(archive_path, f_hash) 

if df_master_raw.empty:
    st.error("🚨 archive_sp500 폴더에 데이터가 없습니다!")
    st.stop()

df_master = preprocess_us_data(df_master_raw, is_daily=False)

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
    '커스텀스코어': st.column_config.NumberColumn('커스텀스코어', format="%.2f"),
    '종가': st.column_config.NumberColumn('종가', format="%.2f"),
    '시가총액': st.column_config.NumberColumn('시가총액', format="%d")
})

col_order_strat1 = ['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)', '이번달수익률']
col_order_strat2 = ['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)', '이번달수익률']
col_order_d1 = ['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)']
col_order_d2 = ['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)']
cols_m = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '커스텀스코어', '이번달수익률']
cols_d = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '커스텀스코어']

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
        
        df_monthly = add_naver_links(df_monthly)
        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us_custom(df_monthly, top_n_12=150, top_n_6=150, top_n_3=150)
        
        df_us_t1['커스텀스코어'] = (-0.1 * df_us_t1['1개월(%)']) + (0.7 * df_us_t1['3개월(%)']) + (0.4 * df_us_t1['6개월(%)'])
        df_us_t1 = df_us_t1.sort_values('커스텀스코어', ascending=False)
        df_us_t1['순위'] = range(1, len(df_us_t1) + 1)
        
        spx_1m, spx_3m = robust_get_us_idx_return(base_date, '^GSPC')
        ndx_1m, ndx_3m = robust_get_us_idx_return(base_date, '^IXIC')
        
        df_strat1_t1['순위'] = range(1, len(df_strat1_t1) + 1)
        df_strat2_t1['순위'] = range(1, len(df_strat2_t1) + 1)

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
            # 💡 [핵심 수정 2] 창이 작아져도 두 줄로 내려오지 않도록 박스 간격 확장 [5:3.5:3.5]
            col_t1, col_i1, col_r1 = st.columns([5, 3.5, 3.5])
            with col_t1: st.markdown(f"<h4 style='margin:0;'>🔥 12-1M & 6-1M <span style='font-size:13px; color:gray;'>({count_p}개)</span></h4>", unsafe_allow_html=True)
            with col_i1: top_n_p = st.number_input("p_n", 1, max(1, count_p), val_p, key="calc_p", label_visibility="collapsed")
            with col_r1:
                avg_ret_p = df_strat1_t1.head(top_n_p)['이번달수익률'].mean() if count_p > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_p}개 평균: <span style='color:{'#D32F2F' if avg_ret_p>0 else '#1976D2'};'>{avg_ret_p:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12-1M & 6-1M 각각 150위 이내 교집합 종목 (6-1M 순)</p>', unsafe_allow_html=True)
            
        with c_r:
            col_t2, col_i2, col_r2 = st.columns([5, 3.5, 3.5])
            with col_t2: st.markdown(f"<h4 style='margin:0;'>🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({count_s}개)</span></h4>", unsafe_allow_html=True)
            with col_i2: top_n_s = st.number_input("s_n", 1, max(1, count_s), val_s, key="calc_s", label_visibility="collapsed")
            with col_r2:
                avg_ret_s = df_strat2_t1.head(top_n_s)['이번달수익률'].mean() if count_s > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_s}개 평균: <span style='color:{'#D32F2F' if avg_ret_s>0 else '#1976D2'};'>{avg_ret_s:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">6-1M & 3-1M 각각 150위 이내 교집합 종목 (6-1M 순)</p>', unsafe_allow_html=True)

        sel_codes_p = df_strat1_t1.head(top_n_p)['종목코드'].tolist()
        sel_codes_s = df_strat2_t1.head(top_n_s)['종목코드'].tolist()
        overlap_codes_t1 = set(sel_codes_p).intersection(set(sel_codes_s))

        with c_l:
            st.dataframe(df_strat1_t1.style.apply(apply_korea_styling, highlight_codes=sel_codes_p, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat1, column_config=us_main_cfg)
        with c_r:
            st.dataframe(df_strat2_t1.style.apply(apply_korea_styling, highlight_codes=sel_codes_s, overlap_codes=overlap_codes_t1, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat2, column_config=us_main_cfg)

        st.markdown("---")
        
        # 💡 [핵심 수정 3] 전체 순위표 독립 하이라이트 추가 및 기준일 설명 삭제
        col_total_t, col_total_i, col_total_r = st.columns([5, 2, 5])
        with col_total_t: 
            st.markdown("<h3 style='margin:0;'>🌐 S&P 500 전체 순위</h3>", unsafe_allow_html=True)
        with col_total_i:
            top_n_total_t1 = st.number_input("전체 순위 하이라이트 (N위)", 1, len(df_us_t1), 10, key="top_n_total_t1", label_visibility="collapsed")
        with col_total_r:
            st.markdown("<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:gray;'>선택한 순위의 종목명이 강조됩니다.</div>", unsafe_allow_html=True)
            
        top_codes_total_t1 = df_us_t1.head(top_n_total_t1)['종목코드'].tolist()
        st.dataframe(df_us_t1.style.apply(apply_custom_total_styling, top_codes=top_codes_total_t1, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_m, column_config=us_main_cfg)

# ==========================================
# 탭 2. 실시간 데일리 순위
# ==========================================
with tab2:
    f_daily_path = 'data/momentum_data_daily_sp500.csv'
    if os.path.exists(f_daily_path):
        df_daily_raw = pd.read_csv(f_daily_path)
        df_daily = preprocess_us_data(df_daily_raw, is_daily=True)
        
        # 💡 [핵심 수정 4] 실시간 데일리 탭 기준일 뒤 시간(00:00:00) 텍스트 포맷 제거
        b_date_d_raw = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        try:
            b_date_d = pd.to_datetime(b_date_d_raw).strftime('%Y-%m-%d') if b_date_d_raw != "오늘" else "오늘"
        except:
            b_date_d = str(b_date_d_raw)
            
        safe_date = b_date_d if b_date_d != "오늘" else datetime.today().strftime('%Y-%m-%d')
        
        st.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        
        spx_curr_d, spx_mas_d = robust_get_us_ma_all(safe_date, '^GSPC')
        ndx_curr_d, ndx_mas_d = robust_get_us_ma_all(safe_date, '^IXIC')

        ma_df_d = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr_d:,.2f}", 'base_price': round(spx_curr_d, 2), '4개월선': spx_mas_d.get(4, 0), '5개월선': spx_mas_d.get(5, 0), '6개월선': spx_mas_d.get(6, 0), '10개월선': spx_mas_d.get(10, 0), '12개월선': spx_mas_d.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.IXIC#{ndx_curr_d:,.2f}", 'base_price': round(ndx_curr_d, 2), '4개월선': ndx_mas_d.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_daily = add_naver_links(df_daily)
        df_us_d, df_strat1_d, df_strat2_d = get_strategy_stocks_us_custom(df_daily, top_n_12=150, top_n_6=150, top_n_3=150)
        
        df_us_d['커스텀스코어'] = (-0.1 * df_us_d['1개월(%)']) + (0.7 * df_us_d['3개월(%)']) + (0.4 * df_us_d['6개월(%)'])
        df_us_d = df_us_d.sort_values('커스텀스코어', ascending=False)
        df_us_d['순위'] = range(1, len(df_us_d) + 1)
        
        spx_1m_d, spx_3m_d = robust_get_us_idx_return(safe_date, '^GSPC')
        ndx_1m_d, ndx_3m_d = robust_get_us_idx_return(safe_date, '^IXIC')
        
        df_strat1_d['순위'] = range(1, len(df_strat1_d) + 1)
        df_strat2_d['순위'] = range(1, len(df_strat2_d) + 1)

        is_below_ma_d = (spx_curr_d > 0) and (spx_curr_d < spx_mas_d.get(10, 0))
        status_d, box_d, text_d = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below_ma_d else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc_d = "S&P500 200일선 이탈" if is_below_ma_d else "안전"

        col1d, col2d, col3d, col4d, col5d, col6d = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1d: st.metric("📈 S&P 500 1M", f"{spx_1m_d}%")
        with col2d: st.metric("📈 S&P 500 3M", f"{spx_3m_d}%")
        with col3d: st.metric("📈 NASDAQ 1M", f"{ndx_1m_d}%")
        with col4d: st.metric("📈 NASDAQ 3M", f"{ndx_3m_d}%")
        with col5d: st.markdown(render_vix_widget(safe_date), unsafe_allow_html=True)
        with col6d: st.markdown(f'<div style="background-color: {box_d}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_d}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_d}; font-weight: bold;">오늘의 시장 상태 ({reason_desc_d})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_d};">{status_d}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        c_d1, c_d2 = st.columns(2)
        count_p_d, count_s_d = len(df_strat1_d), len(df_strat2_d)
        val_p_d = 5 if count_p_d >= 5 else max(1, count_p_d)
        val_s_d = 5 if count_s_d >= 5 else max(1, count_s_d)
        
        with c_d1:
            col_t1, col_i1, col_r1
