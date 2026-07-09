import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="US S&P 500 모멘텀 터미널", layout="wide")

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
    calc_us_momentum, get_triple_momentum_us,
    run_backtest_triple_us_m4, get_multi4_cond1_map, get_multi4_start_ym,
    get_benchmark_monthly_returns
)

# ── 전략 공통 파라미터 (라이브 = 백테스트 기본값, 한 곳에서 관리하여 동일성 보장) ──
STRAT_CUTOFF_N = 100   # 교집합 추출 기준: 3-1·6-1·12-1 각 지표 상위 N위 (라이브·백테스트 공통)
STRAT_TOP_N = 10       # 매수 종목 수(12-1 정렬 상위 N)

inject_custom_css()

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
    st.error(f"🚨 {archive_path} 폴더에 데이터가 없습니다!")
    st.stop()

df_master = preprocess_us_data(df_master_raw, is_daily=False)
valid_years = df_master['투자연도'].dropna().unique().astype(int).tolist()
if not valid_years: valid_years = [datetime.today().year]
years_list = sorted(valid_years)
min_y, max_y = min(years_list), max(years_list)
if min_y >= max_y: min_y = max_y - 1 

tab1, tab2, tab3 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트"])

# ==========================================
# 탭 1. 월별 상세 분석
# ==========================================
with tab1:
    avail_years = [str(y) for y in sorted(years_list, reverse=True)]
    c_y, c_m = st.columns([1.2, 8.8])
    with c_y: 
        st.markdown("<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>📅 투자 연도</b></div>", unsafe_allow_html=True)
        selected_year = st.selectbox("투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y_sp", label_visibility="collapsed")
    
    safe_year = int(float(selected_year)) if selected_year else datetime.today().year
    m_list = sorted(df_master[df_master['투자연도'] == safe_year]['투자월'].astype(str).apply(lambda x: x.split('-')[1] if '-' in x else x).unique())
    default_m_index = len(m_list) - 1 if len(m_list) > 0 else 0

    with c_m:
        month_label = st.empty()
        if m_list:
            selected_month = st.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m_sp", label_visibility="collapsed", index=default_m_index)
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

        # 🎯 종합 모멘텀: 3-1·6-1·12-1 각 상위 N위 교집합 → 12-1 내림차순 (백테스트와 동일)
        df_combo_t1 = get_triple_momentum_us(df_monthly, cutoff=STRAT_CUTOFF_N, mode='rank')
        df_combo_t1['순위'] = range(1, len(df_combo_t1) + 1)

        # 🌐 전체 순위: 시가총액 내림차순
        df_us_t1 = df_us_t1.sort_values('시가총액', ascending=False).reset_index(drop=True)
        df_us_t1['순위'] = range(1, len(df_us_t1) + 1)
        
        spx_1m, spx_3m = robust_get_us_idx_return(base_date, '^GSPC')
        ndx_1m, ndx_3m = robust_get_us_idx_return(base_date, '^IXIC')
        
        cycle_year_t1 = get_cycle_year(safe_year)
        bad_m_str_t1 = ", ".join(f"{m}월" for m in PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year_t1, [])) or "없음"
        
        # 방어 판정: SPY 12개월선 이탈 OR 멀티4(cond1) — 백테스트와 동일 조건
        is_below_ma = (spx_curr > 0) and (spx_curr < (spx_mas.get(12) or 0))
        is_m4 = bool(get_multi4_cond1_map().get(target_month_str, False))
        defense_on = is_below_ma or is_m4
        status, box_c, text_c = ("🛑 투자 중지", "#FFEBEE", "#C62828") if defense_on else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        if defense_on:
            reason_desc = "240일선+멀티4" if (is_below_ma and is_m4) else ("멀티4 방어" if is_m4 else "S&P500 240일선 이탈")
        else:
            reason_desc = "안전"

        col1, col2, col3, col4, col5, col6 = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric("📈 S&P 500 1M", f"{spx_1m}%")
        with col2: st.metric("📈 S&P 500 3M", f"{spx_3m}%")
        with col3: st.metric("📈 NASDAQ 1M", f"{ndx_1m}%")
        with col4: st.metric("📈 NASDAQ 3M", f"{ndx_3m}%")
        with col5: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 12px; font-weight: bold; color: #64748b; margin-bottom: 2px;">🇺🇸대통령 <span style="color:#0047AB;">{cycle_year_t1}년차</span> ({safe_year}년)</div><div style="font-size: 16px; color: #D84315; font-weight:900;">🚨 위험달: {bad_m_str_t1}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_c}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_c}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_c}; font-weight: bold;">최종 판단 ({reason_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_c};">{status}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        # ===== 🎯 종합 모멘텀 (3-1·6-1·12-1 각 상위 N위 교집합, 12-1 정렬) =====
        col_c_t, col_c_i, col_c_r = st.columns([5.5, 2.5, 4.0])
        with col_c_t:
            st.markdown(f"<h4 style='margin:0;'>🎯 종합 모멘텀 <span style='font-size:13px; color:gray;'>(3·6·12 교집합 · {len(df_combo_t1)}개)</span></h4>", unsafe_allow_html=True)
        with col_c_i:
            top_n_combo = st.number_input("몇 개 투자", 1, max(1, len(df_combo_t1)), min(STRAT_TOP_N, max(1, len(df_combo_t1))), key="combo_n_sp", label_visibility="collapsed")
        with col_c_r:
            avg_ret_combo = df_combo_t1.head(top_n_combo)['이번달수익률'].mean() if len(df_combo_t1) > 0 and '이번달수익률' in df_combo_t1.columns else 0
            if avg_ret_combo != 0:
                st.markdown(f"<div style='margin-top:8px; font-size:0.95rem; font-weight:bold;'>상위 {top_n_combo}개 투자 평균: <span style='color:{'#D32F2F' if avg_ret_combo>0 else '#1976D2'};'>{avg_ret_combo:+.2f}%</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:gray;'>상위 N개 투자 시 종목명이 강조됩니다.</div>", unsafe_allow_html=True)
        st.markdown(f'<p class="strategy-desc">3-1M · 6-1M · 12-1M 각각 상위 {STRAT_CUTOFF_N}위에 모두 든 교집합 종목을 12-1M 내림차순 정렬. 상위 N개 투자 가정. (전략 백테스트와 동일 기준)</p>', unsafe_allow_html=True)

        top_codes_combo = df_combo_t1.head(top_n_combo)['종목코드'].tolist()
        col_order_combo = ['순위', '통합티커_L', '종목명_L', '3-1개월(%)', '6-1개월(%)', '12-1개월(%)', '이번달수익률']
        st.dataframe(df_combo_t1.style.apply(apply_custom_total_styling, top_codes=top_codes_combo, axis=1), use_container_width=True, height=600, hide_index=True, column_order=col_order_combo, column_config=us_main_cfg)

        st.markdown("---")
        
        col_total_t, col_total_i, col_total_r = st.columns([5.5, 2.5, 4.0])
        with col_total_t: 
            st.markdown("<h3 style='margin:0;'>🌐 S&P 500 전체 순위</h3>", unsafe_allow_html=True)
        with col_total_i:
            top_n_total_t1 = st.number_input("전체 순위 하이라이트 (N위)", 1, len(df_us_t1), 10, key="top_n_total_t1_sp", label_visibility="collapsed")
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
    f_daily_path = 'data/momentum_data_daily_sp500.csv'
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

        # 🎯 종합 모멘텀: 3-1·6-1·12-1 각 상위 N위 교집합 → 12-1 내림차순 (백테스트와 동일)
        df_combo_d = get_triple_momentum_us(df_daily, cutoff=STRAT_CUTOFF_N, mode='rank')
        df_combo_d['순위'] = range(1, len(df_combo_d) + 1)

        # 🌐 전체 순위: 시가총액 내림차순
        df_us_d = df_us_d.sort_values('시가총액', ascending=False).reset_index(drop=True)
        df_us_d['순위'] = range(1, len(df_us_d) + 1)
        
        spx_1m_d, spx_3m_d = robust_get_us_idx_return(safe_date, '^GSPC')
        ndx_1m_d, ndx_3m_d = robust_get_us_idx_return(safe_date, '^IXIC')

        # 방어 판정: SPY 12개월선 이탈 OR 멀티4(cond1) — 백테스트와 동일 조건
        cur_month_d = pd.to_datetime(safe_date).strftime('%Y-%m')
        is_below_ma_d = (spx_curr_d > 0) and (spx_curr_d < (spx_mas_d.get(12) or 0))
        is_m4_d = bool(get_multi4_cond1_map().get(cur_month_d, False))
        defense_on_d = is_below_ma_d or is_m4_d
        status_d, box_d, text_d = ("🛑 투자 중지", "#FFEBEE", "#C62828") if defense_on_d else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        if defense_on_d:
            reason_desc_d = "240일선+멀티4" if (is_below_ma_d and is_m4_d) else ("멀티4 방어" if is_m4_d else "S&P500 240일선 이탈")
        else:
            reason_desc_d = "안전"

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
            top_n_combo_d = st.number_input("몇 개 투자", 1, max(1, len(df_combo_d)), min(STRAT_TOP_N, max(1, len(df_combo_d))), key="combo_n_sp_d", label_visibility="collapsed")
        with col_cd_r:
            avg_ret_combo_d = df_combo_d.head(top_n_combo_d)['이번달수익률'].mean() if len(df_combo_d) > 0 and '이번달수익률' in df_combo_d.columns else 0
            if avg_ret_combo_d != 0:
                st.markdown(f"<div style='margin-top:8px; font-size:0.95rem; font-weight:bold;'>상위 {top_n_combo_d}개 투자 평균: <span style='color:{'#D32F2F' if avg_ret_combo_d>0 else '#1976D2'};'>{avg_ret_combo_d:+.2f}%</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:gray;'>상위 N개 투자 시 종목명이 강조됩니다.</div>", unsafe_allow_html=True)
        st.markdown(f'<p class="strategy-desc">3-1M · 6-1M · 12-1M 각각 상위 {STRAT_CUTOFF_N}위에 모두 든 교집합 종목을 12-1M 내림차순 정렬. 상위 N개 투자 가정. (전략 백테스트와 동일 기준)</p>', unsafe_allow_html=True)

        top_codes_combo_d = df_combo_d.head(top_n_combo_d)['종목코드'].tolist()
        col_order_combo_d = ['순위', '통합티커_L', '종목명_L', '3-1개월(%)', '6-1개월(%)', '12-1개월(%)']
        st.dataframe(df_combo_d.style.apply(apply_custom_total_styling, top_codes=top_codes_combo_d, axis=1), use_container_width=True, height=600, hide_index=True, column_order=col_order_combo_d, column_config=us_main_cfg)

        st.markdown("---")
        
        top_n_total_d = st.session_state.get("top_n_total_t1_sp", 10)
        col_total_td, col_total_id, col_total_rd = st.columns([5.5, 2.5, 4.0])
        with col_total_td: 
            st.markdown(f"<h3 style='margin:0;'>🌐 S&P 500 전체 순위</h3>", unsafe_allow_html=True)
        with col_total_id:
            top_n_total_d = st.number_input("전체 순위 하이라이트 (N위)", 1, len(df_us_d), top_n_total_d, key="top_n_total_t2_sp", label_visibility="collapsed")
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
# 탭 3. 전략 백테스트 (3·6·12 교집합 + 멀티4 방어)
# ==========================================
with tab3:
    m4_start = get_multi4_start_ym()
    m4_note = (f"멀티4: TIP·VWO·VEA 6M 음수 &amp; (VIXY 6M&lt;0 또는 ≥+40%) 방어 · SPY 개월선과 OR · {m4_start}~ 작동"
               if m4_start else "멀티4 신호 데이터 없음 → SPY 마켓타이밍만 적용")

    with st.form("bt_m4_form_usa", border=False):
        st.markdown(f"<h4 style='margin:0;'>⚙️ 시뮬레이션 설정 <span style='font-size:12px; color:gray; font-weight:normal;'>&nbsp;&nbsp;{m4_note}</span></h4>", unsafe_allow_html=True)
        st.markdown('<p class="strategy-desc">3-1M · 6-1M · 12-1M 각 상위 N위 교집합 → 12-1M 정렬 → 매수 순위까지 매수. 방어 = SPY 개월선 이탈 OR 멀티4</p>', unsafe_allow_html=True)
        cm1, cm_ma, cm_chk = st.columns([1.5, 1, 1.5])
        with cm1: start_year_m, end_year_m = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t5_yr_sp')
        with cm_ma: ma_months_t5 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 12, key='t5_ma_sp')
        with cm_chk:
            st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
            apply_timing_m = st.checkbox("🛑 SPY 마켓타이밍 적용", value=True, key='t5_chk_spy_sp')
            use_multi4 = st.checkbox("🛡️ 멀티4 위험회피 추가", value=True, key='t5_chk_m4_sp')

        st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
        st.markdown("##### ✂️ 교집합 추출 및 매수 순위 설정")
        cm_e1, cm_e2, cm_e3 = st.columns([1.3, 1.5, 0.8])
        with cm_e1:
            top_n_t5 = st.number_input("🎯 교집합 추출 기준 (각 지표 상위 N위)", min_value=1, max_value=500, value=STRAT_CUTOFF_N, key='t5_n_all_sp')
        with cm_e2:
            rank_t5_s, rank_t5_e = st.slider("🛒 매수 순위 (12-1 정렬)", 1, 50, (1, STRAT_TOP_N), key='t5_rnk_sp')
        with cm_e3:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            run_bt_m4 = st.form_submit_button("✅ 백테스트 실행", use_container_width=True)

    only_after = st.checkbox("📅 멀티4 유효구간만 테스트 (상장 이후로 시작 연도 자동 조정)", value=False, key='t5_only_after_sp')
    eff_start_m = start_year_m
    if only_after and use_multi4 and m4_start:
        eff_start_m = max(start_year_m, int(m4_start[:4]))
        st.caption(f"⏱️ 시작 연도를 {eff_start_m}년으로 조정했습니다 (멀티4 유효 시작 {m4_start}).")

    if run_bt_m4 or 'run_bt_state_m4_v1' not in st.session_state:
        st.session_state['run_bt_state_m4_v1'] = True

    if st.session_state.get('run_bt_state_m4_v1', False):
        spx_hist_m = get_spx_history_cached()
        with st.spinner("멀티4 방어 백테스트 구동 중..."):
            df_res_m, df_trades_m = run_backtest_triple_us_m4(
                df_master, eff_start_m, end_year_m, ma_months_t5, apply_timing_m, use_multi4,
                top_n_t5, rank_t5_s, rank_t5_e, spx_hist_m
            )
            if not df_res_m.empty:
                strat_col = [c for c in df_res_m.columns if c not in ['투자월', 'invested']][0]

                # 벤치마크(SPY·QQQ) 월간수익률을 테스트 투자월에 정렬
                bench = get_benchmark_monthly_returns()
                ret_all = df_res_m.set_index('투자월')[[strat_col]].copy()
                bench_cols = []
                for b in ['SPY', 'QQQ']:
                    if not bench.empty and b in bench.columns:
                        ret_all[b] = bench[b].reindex(ret_all.index)
                        bench_cols.append(b)
                all_cols = [strat_col] + bench_cols

                df_cum_m = (1 + ret_all[all_cols].fillna(0.0) / 100).cumprod() * 100
                df_cum_m.loc[(pd.to_datetime(df_res_m['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
                df_cum_m = df_cum_m.sort_index()

                invested_mask = df_res_m.set_index('투자월')['invested'].reindex(ret_all.index).fillna(False).astype(bool)
                years = len(df_res_m) / 12

                def _stat_row(name, is_strat):
                    cum = df_cum_m[name]; final_val = cum.iloc[-1]
                    cagr = ((final_val/100)**(1/years)-1)*100 if final_val > 0 and years > 0 else -100
                    mdd = ((cum/cum.cummax())-1).min()*100
                    r = ret_all[name]
                    if is_strat and invested_mask.any():
                        rr = r[invested_mask.values]
                        win = (rr > 0).mean()*100; avg = rr.mean()
                        inv_ratio = invested_mask.sum()/len(invested_mask)*100
                    else:
                        rr = r.dropna()
                        win = (rr > 0).mean()*100 if len(rr) else 0; avg = rr.mean() if len(rr) else 0
                        inv_ratio = 100.0
                    return {"전략명": name, "CAGR (연평균)": f"{cagr:.1f}%", "총 누적수익률": f"{final_val-100:,.1f}%", "MDD (최대낙폭)": f"{mdd:.1f}%", "투자월 비율": f"{inv_ratio:.1f}%", "월별 승률": f"{win:.1f}%", "평균 수익률": f"{avg:.2f}%"}

                stats_df_m = pd.DataFrame([_stat_row(strat_col, True)] + [_stat_row(b, False) for b in bench_cols])

                m4_defense_cnt = int((df_trades_m['전략'].isin(['멀티4', '마켓타이밍+멀티4'])).sum()) if not df_trades_m.empty else 0
                settings_dict_m = {
                    '테스트 시작 연도': f"{eff_start_m}년",
                    '테스트 종료 연도': f"{end_year_m}년",
                    '마켓타이밍 (개월선)': f"{ma_months_t5}개월선",
                    'SPY 마켓타이밍': "적용(현금)" if apply_timing_m else "미적용",
                    '멀티4 위험회피': f"적용 (유효 {m4_start}~)" if (use_multi4 and m4_start) else "미적용",
                    '교집합 추출 기준': f"각 지표 상위 {top_n_t5}위",
                    '매수 순위 (12-1 정렬)': f"{rank_t5_s}위 ~ {rank_t5_e}위",
                    '멀티4 방어 발동 개월': f"{m4_defense_cnt}개월",
                    '벤치마크': ", ".join(bench_cols) if bench_cols else "없음"
                }
                excel_data_m = generate_excel_report_cached(tuple(settings_dict_m.items()), stats_df_m, df_res_m, df_cum_m, df_trades_m)

                col_tm, col_bm = st.columns([7.5, 2.5])
                with col_tm: st.markdown("#### 📊 전략 핵심 통계 (초기 자본 100 기준 · SPY·QQQ 비교)")
                with col_bm:
                    st.download_button("📥 종합 엑셀 리포트 다운로드", data=excel_data_m, file_name="SP500_전략백테스트.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

                st.dataframe(get_styled_stats(stats_df_m), use_container_width=True, hide_index=True)

                st.markdown("#### 🗓️ 상세 분석 (월별 수익률 히트맵 & MDD)")
                analysis_strat_t5 = strat_col
                col_hm_m, col_mdd_m = st.columns([7.5, 2.5])
                with col_hm_m: st.dataframe(get_monthly_heatmap(df_res_m, analysis_strat_t5), use_container_width=True)
                with col_mdd_m: st.dataframe(get_mdd_history(df_cum_m[analysis_strat_t5]), use_container_width=True, hide_index=True)

                st.plotly_chart(px.line(df_cum_m.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale · 전략 vs SPY·QQQ)", labels={'variable': '', 'value': '누적자산'}), use_container_width=True)
                with st.expander("📝 월별 전체 상세 기록 보기 (전략·벤치마크)"): st.dataframe(ret_all.style.format("{:.2f}%", na_rep="-"), use_container_width=True)
            else:
                st.warning("해당 조건에서 결과가 비어 있습니다. 교집합 기준(N위)이나 기간을 조정해 보세요.")
