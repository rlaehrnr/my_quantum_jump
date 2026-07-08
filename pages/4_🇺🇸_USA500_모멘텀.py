import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="USA 500 통합 모멘텀", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS
# 💡 핵심: ui_components에서 앞서 정의한 공통 설정들을 똑같이 가져옵니다.
from utils.ui_components import (
    inject_custom_css, apply_korea_styling, style_kospi_ma, get_styled_stats, 
    get_mdd_history, get_monthly_heatmap, ma_cfg, apply_custom_total_styling, 
    render_vix_widget, us_main_cfg, col_order_strat1, col_order_strat2, 
    col_order_d1, col_order_d2, cols_m, cols_d
)

from utils.us_helpers import (
    preprocess_us_data, add_naver_links, robust_get_us_ma_all, robust_get_us_idx_return, 
    get_spx_history_cached, generate_excel_report_cached, 
    get_strategy_stocks_us_custom, run_backtest_us_fast, run_custom_backtest_us,
    calc_us_momentum, get_triple_momentum_us, run_backtest_triple_us
)

inject_custom_css()

@st.cache_data(show_spinner=False)
def cached_run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    return run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)

st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="https://m.stock.naver.com/worldstock/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
                <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">🇺🇸 USA 500 통합 모멘텀 (Top 500)</h1>
                <span style="font-size: 0.95rem; color: #10b981; background-color: #d1fae5; padding: 4px 10px; border-radius: 6px; border: 1px solid #6ee7b7; white-space: nowrap;">🔗 네이버 증권 이동</span>
            </div>
        </a>
    </div>
''', unsafe_allow_html=True)

archive_path = "archive_usa"
f_hash = get_folder_hash(archive_path) 
df_master_raw = load_archive_data(archive_path, f_hash) 

if df_master_raw.empty:
    st.error(f"🚨 {archive_path} 폴더에 데이터가 없습니다!")
    st.stop()

df_master = preprocess_us_data(df_master_raw, is_daily=False)
valid_years = df_master['투자연도'].dropna().unique().astype(int).tolist()
if not valid_years: valid_years = [datetime.today().year]
years_list = sorted(valid_years)
min_y, max_y = min(years_list), max(years_list)
if min_y >= max_y: min_y = max_y - 1 

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트", "🏅 스코어 커스텀 백테스트"])

# ==========================================
# 탭 1. 월별 상세 분석
# ==========================================
with tab1:
    avail_years = [str(y) for y in sorted(years_list, reverse=True)]
    c_y, c_m = st.columns([1.2, 8.8])
    with c_y: 
        st.markdown("<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>📅 투자 연도</b></div>", unsafe_allow_html=True)
        selected_year = st.selectbox("투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y_usa", label_visibility="collapsed")
    
    safe_year = int(float(selected_year)) if selected_year else datetime.today().year
    m_list = sorted(df_master[df_master['투자연도'] == safe_year]['투자월'].astype(str).apply(lambda x: x.split('-')[1] if '-' in x else x).unique())
    default_m_index = len(m_list) - 1 if len(m_list) > 0 else 0

    with c_m:
        month_label = st.empty()
        if m_list:
            selected_month = st.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m_usa", label_visibility="collapsed", index=default_m_index)
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
        df_us_t1 = calc_us_momentum(df_monthly)

        # 🎯 종합 모멘텀: 3-1·6-1·12-1 각 상위 30% 교집합 → 12-1 내림차순
        df_combo_t1 = get_triple_momentum_us(df_monthly, cutoff=30, mode='pct')
        df_combo_t1['순위'] = range(1, len(df_combo_t1) + 1)

        # 🌐 전체 순위: 시가총액 내림차순
        df_us_t1['커스텀스코어'] = (-0.1 * df_us_t1['1개월(%)']) + (0.7 * df_us_t1['3개월(%)']) + (0.4 * df_us_t1['6개월(%)'])
        df_us_t1 = df_us_t1.sort_values('시가총액', ascending=False).reset_index(drop=True)
        df_us_t1['순위'] = range(1, len(df_us_t1) + 1)
        
        spx_1m, spx_3m = robust_get_us_idx_return(base_date, '^GSPC')
        ndx_1m, ndx_3m = robust_get_us_idx_return(base_date, '^IXIC')
        
        cycle_year_t1 = get_cycle_year(safe_year)
        bad_m_str_t1 = ", ".join(f"{m}월" for m in PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year_t1, [])) or "없음"
        
        is_below_ma = (spx_curr > 0) and (spx_curr < (spx_mas.get(12) or 0))
        status, box_c, text_c = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below_ma else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc = "S&P500 240일선 이탈" if is_below_ma else "안전"

        col1, col2, col3, col4, col5, col6 = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric("📈 S&P 500 1M", f"{spx_1m}%")
        with col2: st.metric("📈 S&P 500 3M", f"{spx_3m}%")
        with col3: st.metric("📈 NASDAQ 1M", f"{ndx_1m}%")
        with col4: st.metric("📈 NASDAQ 3M", f"{ndx_3m}%")
        with col5: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 12px; font-weight: bold; color: #64748b; margin-bottom: 2px;">🇺🇸대통령 <span style="color:#0047AB;">{cycle_year_t1}년차</span> ({safe_year}년)</div><div style="font-size: 16px; color: #D84315; font-weight:900;">🚨 위험달: {bad_m_str_t1}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_c}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_c}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_c}; font-weight: bold;">최종 판단 ({reason_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_c};">{status}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        # ===== 🎯 종합 모멘텀 (3-1·6-1·12-1 각 상위 30% 교집합, 12-1 정렬) =====
        col_c_t, col_c_i, col_c_r = st.columns([5.5, 2.5, 4.0])
        with col_c_t:
            st.markdown(f"<h4 style='margin:0;'>🎯 종합 모멘텀 <span style='font-size:13px; color:gray;'>(3·6·12 교집합 · {len(df_combo_t1)}개)</span></h4>", unsafe_allow_html=True)
        with col_c_i:
            top_n_combo = st.number_input("몇 개 투자", 1, max(1, len(df_combo_t1)), min(10, max(1, len(df_combo_t1))), key="combo_n_usa", label_visibility="collapsed")
        with col_c_r:
            avg_ret_combo = df_combo_t1.head(top_n_combo)['이번달수익률'].mean() if len(df_combo_t1) > 0 and '이번달수익률' in df_combo_t1.columns else 0
            if avg_ret_combo != 0:
                st.markdown(f"<div style='margin-top:8px; font-size:0.95rem; font-weight:bold;'>상위 {top_n_combo}개 투자 평균: <span style='color:{'#D32F2F' if avg_ret_combo>0 else '#1976D2'};'>{avg_ret_combo:+.2f}%</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:gray;'>상위 N개 투자 시 종목명이 강조됩니다.</div>", unsafe_allow_html=True)
        st.markdown('<p class="strategy-desc">3-1M · 6-1M · 12-1M 각각 상위 30%에 모두 든 교집합 종목을 12-1M 내림차순 정렬. 상위 N개 투자 가정.</p>', unsafe_allow_html=True)

        top_codes_combo = df_combo_t1.head(top_n_combo)['종목코드'].tolist()
        col_order_combo = ['순위', '통합티커_L', '종목명_L', '3-1개월(%)', '6-1개월(%)', '12-1개월(%)', '이번달수익률']
        st.dataframe(df_combo_t1.style.apply(apply_custom_total_styling, top_codes=top_codes_combo, axis=1), use_container_width=True, height=600, hide_index=True, column_order=col_order_combo, column_config=us_main_cfg)

        st.markdown("---")
        
        col_total_t, col_total_i, col_total_r = st.columns([5.5, 2.5, 4.0])
        with col_total_t: 
            st.markdown("<h3 style='margin:0;'>🌐 USA 500 전체 순위</h3>", unsafe_allow_html=True)
        with col_total_i:
            top_n_total_t1 = st.number_input("전체 순위 하이라이트 (N위)", 1, len(df_us_t1), 10, key="top_n_total_t1_usa", label_visibility="collapsed")
        with col_total_r:
            avg_ret_total_t1 = df_us_t1.head(top_n_total_t1)['이번달수익률'].mean() if len(df_us_t1) > 0 and '이번달수익률' in df_us_t1.columns else 0
            if avg_ret_total_t1 != 0:
                st.markdown(f"<div style='margin-top:8px; font-size:0.95rem; font-weight:bold;'>상위 {top_n_total_t1}개 평균: <span style='color:{'#D32F2F' if avg_ret_total_t1>0 else '#1976D2'};'>{avg_ret_total_t1:+.2f}%</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:gray;'>선택한 순위의 종목명이 강조됩니다.</div>", unsafe_allow_html=True)
            
        top_codes_total_t1 = df_us_t1.head(top_n_total_t1)['종목코드'].tolist()
        st.dataframe(df_us_t1.style.apply(apply_custom_total_styling, top_codes=top_codes_total_t1, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_m, column_config=us_main_cfg)

# ==========================================
# 탭 2. 실시간 데일리 순위
# ==========================================
with tab2:
    f_daily_path = 'data/momentum_data_daily_usa500.csv'
    if not os.path.exists(f_daily_path):
        f_daily_path = 'data/momentum_data_daily_usa300.csv'
    if os.path.exists(f_daily_path):
        df_daily_raw = pd.read_csv(f_daily_path)
        df_daily = preprocess_us_data(df_daily_raw, is_daily=True)
        
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
        df_us_d = calc_us_momentum(df_daily)

        # 🎯 종합 모멘텀: 3-1·6-1·12-1 각 상위 30% 교집합 → 12-1 내림차순
        df_combo_d = get_triple_momentum_us(df_daily, cutoff=30, mode='pct')
        df_combo_d['순위'] = range(1, len(df_combo_d) + 1)

        # 🌐 전체 순위: 시가총액 내림차순
        df_us_d['커스텀스코어'] = (-0.1 * df_us_d['1개월(%)']) + (0.7 * df_us_d['3개월(%)']) + (0.4 * df_us_d['6개월(%)'])
        df_us_d = df_us_d.sort_values('시가총액', ascending=False).reset_index(drop=True)
        df_us_d['순위'] = range(1, len(df_us_d) + 1)
        
        spx_1m_d, spx_3m_d = robust_get_us_idx_return(safe_date, '^GSPC')
        ndx_1m_d, ndx_3m_d = robust_get_us_idx_return(safe_date, '^IXIC')

        is_below_ma_d = (spx_curr_d > 0) and (spx_curr_d < (spx_mas_d.get(12) or 0))
        status_d, box_d, text_d = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below_ma_d else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc_d = "S&P500 240일선 이탈" if is_below_ma_d else "안전"

        col1d, col2d, col3d, col4d, col5d, col6d = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1d: st.metric("📈 S&P 500 1M", f"{spx_1m_d}%")
        with col2d: st.metric("📈 S&P 500 3M", f"{spx_3m_d}%")
        with col3d: st.metric("📈 NASDAQ 1M", f"{ndx_1m_d}%")
        with col4d: st.metric("📈 NASDAQ 3M", f"{ndx_3m_d}%")
        with col5d: st.markdown(render_vix_widget(safe_date), unsafe_allow_html=True)
        with col6d: st.markdown(f'<div style="background-color: {box_d}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_d}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_d}; font-weight: bold;">오늘의 시장 상태 ({reason_desc_d})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_d};">{status_d}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        # ===== 🎯 종합 모멘텀 (3-1·6-1·12-1 각 상위 30% 교집합, 12-1 정렬) =====
        col_cd_t, col_cd_i, col_cd_r = st.columns([5.5, 2.5, 4.0])
        with col_cd_t:
            st.markdown(f"<h4 style='margin:0;'>🎯 종합 모멘텀 <span style='font-size:13px; color:gray;'>(3·6·12 교집합 · {len(df_combo_d)}개)</span></h4>", unsafe_allow_html=True)
        with col_cd_i:
            top_n_combo_d = st.number_input("몇 개 투자", 1, max(1, len(df_combo_d)), min(10, max(1, len(df_combo_d))), key="combo_n_us_d", label_visibility="collapsed")
        with col_cd_r:
            avg_ret_combo_d = df_combo_d.head(top_n_combo_d)['이번달수익률'].mean() if len(df_combo_d) > 0 and '이번달수익률' in df_combo_d.columns else 0
            if avg_ret_combo_d != 0:
                st.markdown(f"<div style='margin-top:8px; font-size:0.95rem; font-weight:bold;'>상위 {top_n_combo_d}개 투자 평균: <span style='color:{'#D32F2F' if avg_ret_combo_d>0 else '#1976D2'};'>{avg_ret_combo_d:+.2f}%</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:gray;'>상위 N개 투자 시 종목명이 강조됩니다.</div>", unsafe_allow_html=True)
        st.markdown('<p class="strategy-desc">3-1M · 6-1M · 12-1M 각각 상위 30%에 모두 든 교집합 종목을 12-1M 내림차순 정렬. 상위 N개 투자 가정.</p>', unsafe_allow_html=True)

        top_codes_combo_d = df_combo_d.head(top_n_combo_d)['종목코드'].tolist()
        col_order_combo_d = ['순위', '통합티커_L', '종목명_L', '3-1개월(%)', '6-1개월(%)', '12-1개월(%)']
        st.dataframe(df_combo_d.style.apply(apply_custom_total_styling, top_codes=top_codes_combo_d, axis=1), use_container_width=True, height=600, hide_index=True, column_order=col_order_combo_d, column_config=us_main_cfg)

        st.markdown("---")
        
        top_n_total_d = st.session_state.get("top_n_total_t1_usa", 10)
        col_total_td, col_total_id, col_total_rd = st.columns([5.5, 2.5, 4.0])
        with col_total_td: 
            st.markdown(f"<h3 style='margin:0;'>🌐 USA 500 전체 순위</h3>", unsafe_allow_html=True)
        with col_total_id:
            top_n_total_d = st.number_input("전체 순위 하이라이트 (N위)", 1, len(df_us_d), top_n_total_d, key="top_n_total_t2_usa", label_visibility="collapsed")
        with col_total_rd:
            avg_ret_total_d = df_us_d.head(top_n_total_d)['이번달수익률'].mean() if len(df_us_d) > 0 and '이번달수익률' in df_us_d.columns else 0
            if avg_ret_total_d != 0:
                st.markdown(f"<div style='margin-top:8px; font-size:0.95rem; font-weight:bold;'>상위 {top_n_total_d}개 평균: <span style='color:{'#D32F2F' if avg_ret_total_d>0 else '#1976D2'};'>{avg_ret_total_d:+.2f}%</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:gray;'>선택한 순위의 종목명이 강조됩니다.</div>", unsafe_allow_html=True)
            
        top_codes_total_d = df_us_d.head(top_n_total_d)['종목코드'].tolist()
        st.dataframe(df_us_d.style.apply(apply_custom_total_styling, top_codes=top_codes_total_d, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_d, column_config=us_main_cfg)
    else:
        st.info("데일리 데이터가 준비되지 않았습니다.")

# ==========================================
# 탭 3. 전략 백테스트
# ==========================================
with tab3:
    with st.form("bt_settings_form_usa", border=False):
        st.markdown("<h4 style='margin:0;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
        st.markdown('<p class="strategy-desc">3-1M · 6-1M · 12-1M 각각 상위 N위에 모두 든 교집합 → 12-1M 내림차순 정렬 → 매수 순위까지 매수</p>', unsafe_allow_html=True)
        c1, c_ma_us, c_chk = st.columns([1.5, 1, 1.5])
        with c1: start_year, end_year = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr_usa')
        with c_ma_us: ma_months_t3 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 12, key='t3_ma_usa')
        with c_chk:
            st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
            apply_timing = st.checkbox("🛑 마켓타이밍 적용 (이탈 시 현금)", value=True, key='t3_chk_usa')
        
        st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
        st.markdown("##### ✂️ 교집합 추출 및 매수 순위 설정")
        
        c_ex1, c_ex2, c_ex3 = st.columns([1.3, 1.5, 0.8])
        with c_ex1: 
            top_n_t3 = st.number_input("🎯 교집합 추출 기준 (각 지표 상위 N위)", min_value=1, max_value=500, value=150, key='t3_n_all_usa')
        with c_ex2: 
            rank_t3_s, rank_t3_e = st.slider("🛒 매수 순위 (12-1 정렬)", 1, 50, (1, 10), key='t3_rnk_usa')
        with c_ex3:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            run_bt_us = st.form_submit_button("✅ 백테스트 실행", use_container_width=True)

    if run_bt_us or 'run_bt_state_usa_v7' not in st.session_state:
        st.session_state['run_bt_state_usa_v7'] = True

    if st.session_state.get('run_bt_state_usa_v7', False):
        spx_hist = get_spx_history_cached()
        
        with st.spinner("3·6·12 교집합 백테스트 구동 중..."):
            df_res, df_trades = run_backtest_triple_us(
                df_master, start_year, end_year, ma_months_t3, apply_timing, 
                top_n_t3, rank_t3_s, rank_t3_e, spx_hist
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
                    '교집합 추출 기준': f"각 지표 상위 {top_n_t3}위",
                    '매수 순위 (12-1 정렬)': f"{rank_t3_s}위 ~ {rank_t3_e}위"
                }

                excel_data = generate_excel_report_cached(tuple(settings_dict.items()), stats_df, df_res, df_cum, df_trades)

                col_t, col_b = st.columns([7.5, 2.5])
                with col_t: st.markdown("#### 📊 전략 핵심 통계 (초기 자본 100 기준)")
                with col_b: 
                    st.download_button("📥 종합 엑셀 리포트 다운로드", data=excel_data, file_name="USA_3-6-12교집합_백테스트.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

                st.dataframe(get_styled_stats(stats_df), use_container_width=True, hide_index=True)
                
                st.markdown("#### 🗓️ 상세 분석 (월별 수익률 히트맵 & MDD)")
                analysis_strat_t3 = s_cols[0]
                
                col_hm, col_mdd = st.columns([7.5, 2.5])
                with col_hm: st.dataframe(get_monthly_heatmap(df_res, analysis_strat_t3), use_container_width=True)
                with col_mdd: st.dataframe(get_mdd_history(df_cum[analysis_strat_t3]), use_container_width=True, hide_index=True)
                
                st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)"), use_container_width=True)
                with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)
            else:
                st.warning("해당 조건에서 교집합 종목이 없어 백테스트 결과가 비어 있습니다. 교집합 기준(N위)을 늘리거나 기간을 조정해 보세요.")

# ==========================================
# 탭 4. 스코어 커스텀 백테스트
# ==========================================
with tab4:
    col_title_c, col_check_c = st.columns([1, 4])
    with col_title_c: st.markdown("<h4 style='margin:0;'>⚙️ 스코어 가중치 설정</h4>", unsafe_allow_html=True)
    with col_check_c:
        st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
        apply_timing_c = st.checkbox("🛑 마켓타이밍 적용 (이탈 시 현금)", value=True, key='t4_chk_main_usa')
    
    with st.form("custom_form_usa", border=False):
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
    with c6: start_year_c, end_year_c = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t4_yr_usa')
    with c_ma_c: ma_months_t4 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 12, key='t4_ma_usa')
    with c7: custom_pct = st.slider("🏅 상위 % 커트라인", 5, 50, 30, step=5, key='t4_pct_usa')
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위", 1, 30, (1, 10), key='t4_rnk_usa')

    if apply_weights or 'custom_run_usa' not in st.session_state: st.session_state['custom_run_usa'] = True
    if st.session_state.get('custom_run_usa', False):
        with st.spinner("미국 커스텀 시뮬레이션 중..."):
            df_res_c, df_trades_c = cached_run_custom_backtest_us(df_master, start_year_c, end_year_c, ma_months_t4, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)
            if not df_res_c.empty:
                df_cum_c = (1 + df_res_c.set_index('투자월')[['커스텀 전략']] / 100).cumprod() * 100
                df_cum_c.loc[(pd.to_datetime(df_res_c['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
                df_cum_c = df_cum_c.sort_index()

                col_tc, col_bc = st.columns([7.5, 2.5])
                with col_tc: st.markdown("#### 📊 전략 핵심 통계")
                with col_bc: st.download_button("📥 상세내역 다운로드", df_trades_c.to_csv(index=False).encode('utf-8-sig'), "USA500_커스텀_백테스트.csv", "text/csv", use_container_width=True)

                final_val_c = df_cum_c['커스텀 전략'].iloc[-1]
                years_c = len(df_res_c) / 12
                cagr_c = ((final_val_c/100)**(1/years_c)-1)*100 if final_val_c > 0 else -100
                mdd_c = ((df_cum_c['커스텀 전략']/df_cum_c['커스텀 전략'].cummax())-1).min()*100
                stats_c = [{"전략명": "커스텀 스코어", "CAGR (연평균)": f"{cagr_c:.1f}%", "총 누적수익률": f"{final_val_c-100:,.1f}%", "MDD (최대낙폭)": f"{mdd_c:.1f}%", "투자월 비율": f"{(df_res_c['invested'].sum()/len(df_res_c))*100:.1f}%", "월별 승률": f"{(df_res_c.loc[df_res_c['invested'], '커스텀 전략']>0).mean()*100:.1f}%" if df_res_c['invested'].any() else "0.0%", "평균 수익률": f"{df_res_c.loc[df_res_c['invested'], '커스텀 전략'].mean():.2f}%" if df_res_c['invested'].any() else "0.00%"}]
                
                stats_df_t4 = pd.DataFrame(stats_c)
                settings_dict_t4 = {
                    '테스트 시작 연도': f"{start_year_c}년",
                    '테스트 종료 연도': f"{end_year_c}년",
                    '마켓타이밍 (개월선)': f"{ma_months_t4}개월선",
                    '마켓타이밍 적용': "적용(현금)" if apply_timing_c else "미적용",
                    '가중치 설정': f"{w1}, {w3}, {w6}, {w12}",
                    '교집합 추출 기준': f"상위 {custom_pct}% 이내",
                    '매수 순위': f"{rank_c_s}위 ~ {rank_c_e}위"
                }
                
                excel_data_t4 = generate_excel_report_cached(tuple(settings_dict_t4.items()), stats_df_t4, df_res_c, df_cum_c, df_trades_c)

                st.dataframe(get_styled_stats(stats_df_t4), use_container_width=True, hide_index=True)
                
                col_hm_c, col_mdd_c = st.columns([6, 4])
                with col_hm_c: st.dataframe(get_monthly_heatmap(df_res_c, '커스텀 전략'), use_container_width=True)
                with col_mdd_c: st.dataframe(get_mdd_history(df_cum_c['커스텀 전략']), use_container_width=True, hide_index=True)

                st.plotly_chart(px.line(df_cum_c.reset_index(), x='투자월', y='커스텀 전략', log_y=True, title="커스텀 누적 성과"), use_container_width=True)
                with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res_c.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)
