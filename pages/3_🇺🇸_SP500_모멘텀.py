import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import FinanceDataReader as fdr

st.set_page_config(page_title="US S&P 500 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS
from utils.ui_components import inject_custom_css, apply_korea_styling, style_kospi_ma, get_styled_stats, get_mdd_history, get_monthly_heatmap, ma_cfg, main_cfg
# 💡 스코어 커스텀 백테스트(run_custom_backtest_us) 임포트 추가
from utils.calculator import get_us_ma_all, get_us_idx_return, calc_us_momentum, get_strategy_stocks_us, map_english_columns, run_backtest_us, run_custom_backtest_us

inject_custom_css()

# 💡 [핵심] 네이버 증권 링크로 변경
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
df_master = load_archive_data(archive_path, f_hash) 
f_daily = 'data/momentum_data_daily_sp500.csv'

if df_master.empty:
    st.error("🚨 archive_sp500 폴더에 데이터가 없습니다!")
    st.stop()

df_master = map_english_columns(df_master)

# 💡 [해결] 실시간으로 종목명 맵핑 가져오기 (티커가 종목명으로 뜨는 문제 해결)
@st.cache_data(ttl=86400)
def get_sp500_names():
    try:
        df_sp = fdr.StockListing('S&P500')
        return dict(zip(df_sp['Symbol'].str.replace('.', '-', regex=False), df_sp['Name']))
    except: return {}

name_map = get_sp500_names()
if name_map:
    df_master['종목명'] = df_master['종목코드'].map(name_map).fillna(df_master['종목명'])

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

@st.cache_data(show_spinner=False)
def cached_run_backtest_us(df, start_year, end_year, apply_timing, rank_s1, rank_s2):
    return run_backtest_us(df, start_year, end_year, apply_timing, rank_s1, rank_s2, top_pct=30)

@st.cache_data(show_spinner=False)
def cached_run_custom_backtest_us(df, start_year_c, end_year_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    return run_custom_backtest_us(df, start_year_c, end_year_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)

# 💡 탭 4개 부활 (스코어 커스텀 백테스트 추가)
tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트", "🏅 스코어 커스텀 백테스트"])

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

        @st.cache_data(ttl=3600)
        def get_ma_data(date):
            spx_curr, spx_mas = get_us_ma_all(date, '^GSPC')
            ndx_curr, ndx_mas = get_us_ma_all(date, '^IXIC')
            return spx_curr, spx_mas, ndx_curr, ndx_mas
        spx_curr, spx_mas, ndx_curr, ndx_mas = get_ma_data(base_date)
        
        # 💡 [핵심] 네이버 증권 지수 링크
        ma_df = pd.DataFrame([
            {'지수_L': "https://m.stock.naver.com/worldstock/index/.INX/total", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)},
            {'지수_L': "https://m.stock.naver.com/worldstock/index/.IXIC/total", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#{ndx_curr:,.2f}", 'base_price': round(ndx_curr, 2), '4개월선': ndx_mas.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
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
            # 💡 [핵심] 개별 종목 네이버 증권 링크
            df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['종목명']}", axis=1)

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
            st.dataframe(df_strat1_t1.style.apply(apply_korea_styling, highlight_codes=df_strat1_t1.head(top_n_p)['종목코드'].tolist(), axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)', '이번달수익률'], column_config=us_main_cfg)
        
        with c_r:
            col_t2, col_i2, col_r2 = st.columns([4, 2, 4])
            with col_t2: st.markdown(f"<h4 style='margin:0;'>🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({count_s}개)</span></h4>", unsafe_allow_html=True)
            with col_i2: top_n_s = st.number_input("s_n", 1, max(1, count_s), min(2, count_s) if count_s > 0 else 1, key="calc_s", label_visibility="collapsed")
            with col_r2:
                avg_ret_s = df_strat2_t1.head(top_n_s)['이번달수익률'].mean() if count_s > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_s}개 평균: <span style='color:{'#D32F2F' if avg_ret_s>0 else '#1976D2'};'>{avg_ret_s:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">6-1M & 3-1M 모두 상위 30% 이내 & 0보다 큰 종목 (3-1M 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_strat2_t1.style.apply(apply_korea_styling, highlight_codes=df_strat2_t1.head(top_n_s)['종목코드'].tolist(), axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)', '이번달수익률'], column_config=us_main_cfg)

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
        if name_map: df_daily['종목명'] = df_daily['종목코드'].map(name_map).fillna(df_daily['종목명'])
        
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        safe_date = b_date_d if b_date_d != "오늘" else datetime.today().strftime('%Y-%m-%d')
        
        for col in ['시가총액', '종가', '거래량']:
            if col in df_daily.columns:
                df_daily[col] = pd.to_numeric(df_daily[col], errors='coerce').fillna(0)
        
        st.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        
        @st.cache_data(ttl=3600)
        def get_ma_data_d(date):
            spx_curr_d, spx_mas_d = get_us_ma_all(date, '^GSPC')
            ndx_curr_d, ndx_mas_d = get_us_ma_all(date, '^IXIC')
            return spx_curr_d, spx_mas_d, ndx_curr_d, ndx_mas_d
        spx_curr_d, spx_mas_d, ndx_curr_d, ndx_mas_d = get_ma_data_d(safe_date)

        ma_df_d = pd.DataFrame([
            {'지수_L': "https://m.stock.naver.com/worldstock/index/.INX/total", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#{spx_curr_d:,.2f}", 'base_price': round(spx_curr_d, 2), '4개월선': spx_mas_d.get(4, 0), '5개월선': spx_mas_d.get(5, 0), '6개월선': spx_mas_d.get(6, 0), '10개월선': spx_mas_d.get(10, 0), '12개월선': spx_mas_d.get(12, 0)},
            {'지수_L': "https://m.stock.naver.com/worldstock/index/.IXIC/total", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#{ndx_curr_d:,.2f}", 'base_price': round(ndx_curr_d, 2), '4개월선': ndx_mas_d.get(4, 0), '5개월선': ndx_mas_d.get(5, 0), '6개월선': ndx_mas_d.get(6, 0), '10개월선': ndx_mas_d.get(10, 0), '12개월선': ndx_mas_d.get(12, 0)}
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
        
        vix_html = f'''<a href="https://m.stock.naver.com/worldstock/index/.VIX/total" target="_blank" style="text-decoration: none; color: inherit;">
            <div class="title-link" style="background-color: {vix_bg}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {vix_border}; height: 95px; display: flex; flex-direction: column; justify-content: center;">
                <div style="font-size: 12px; font-weight: bold; color: {vix_title_color}; margin-bottom: 2px;">{vix_icon} VIX 35 돌파</div>
                <div style="font-size: 11px; font-weight: bold; color: {vix_title_color}; margin-bottom: 4px;">VIX {vix_35_high} - {vix_35_date_str}돌파 ({days_diff_str})</div>
                <div style="font-size: 15px; color: {vix_val_color}; font-weight:900;">{vix_label} {vix_latest_high}</div>
            </div></a>'''
        
        with col5d: st.markdown(vix_html, unsafe_allow_html=True)
        with col6d: st.markdown(f'<div style="background-color: {box_d}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_d}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_d}; font-weight: bold;">오늘의 시장 상태 ({reason_desc_d})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_d};">{status_d}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_strat1_d, df_strat2_d, df_us_d]:
            df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['종목명']}", axis=1)

        c_d1, c_d2 = st.columns(2)
        with c_d1:
            st.markdown(f"<h4 style='margin:0;'>🔥 12-1M & 6-1M <span style='font-size:13px; color:gray;'>({len(df_strat1_d)}개)</span></h4>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12-1M & 6-1M 모두 상위 30% 이내 & 0보다 큰 종목 (6-1M 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_strat1_d.style.apply(apply_korea_styling, highlight_codes=df_strat1_d.head(top_n_p)['종목코드'].tolist(), axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)'], column_config=us_main_cfg)
        with c_d2:
            st.markdown(f"<h4 style='margin:0;'>🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({len(df_strat2_d)}개)</span></h4>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">6-1M & 3-1M 모두 상위 30% 이내 & 0보다 큰 종목 (3-1M 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_strat2_d.style.apply(apply_korea_styling, highlight_codes=df_strat2_d.head(top_n_s)['종목코드'].tolist(), axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)'], column_config=us_main_cfg)
            
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
    # 💡 [핵심] 상위 커트라인 슬라이더 제거 및 UI 정돈
    c3, c5 = st.columns([1, 1])
    with c3: rank_p_s, rank_p_e = st.slider("🔥 12-1&6-1 전략 (매수 순위)", 1, 30, (1, 5))
    with c5: rank_s_s, rank_s_e = st.slider("🐎 6-1&3-1 전략 (매수 순위)", 1, 30, (1, 5))

    with st.spinner("미국 모멘텀 백테스트 구동 중..."):
        df_res, df_trades = cached_run_backtest_us(df_master, start_year, end_year, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e))
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

# 💡 [핵심] 스코어 커스텀 백테스트 탭 추가
with tab4:
    col_title_c, col_check_c = st.columns([1, 4])
    with col_title_c: st.markdown("<h4 style='margin:0;'>⚙️ 스코어 가중치 설정</h4>", unsafe_allow_html=True)
    with col_check_c:
        st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
        apply_timing_c = st.checkbox("🛑 마켓타이밍 적용 (S&P 500 200일선 이탈 시 현금)", value=True, key='t4_chk_main')
    
    with st.form("custom_form_us", border=False):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])
        # 💡 [핵심] 미국 전용 기본 가중치 세팅
        with c1: w1 = st.number_input("📉 1개월 가중치", value=-0.1, step=0.1, format="%.1f")
        with c2: w3 = st.number_input("📈 3개월 가중치", value=0.7, step=0.1, format="%.1f")
        with c3: w6 = st.number_input("📈 6개월 가중치", value=0.4, step=0.1, format="%.1f")
        with c4: w12 = st.number_input("📈 12개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            apply_weights = st.form_submit_button("✅ 실행", use_container_width=True)
            
    st.markdown("<hr style='margin: 15px 0px;'>", unsafe_allow_html=True)
    c6, c7, c8 = st.columns([1, 1, 1])
    with c6: start_year_c, end_year_c = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t4_yr')
    with c7: custom_pct = st.slider("🏅 상위 % 커트라인", 5, 50, 30, step=5)
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위", 1, 30, (1, 10), key='t4_rnk')

    if apply_weights or 'custom_run_us' not in st.session_state: st.session_state['custom_run_us'] = True
    if st.session_state.get('custom_run_us', False):
        with st.spinner("미국 커스텀 시뮬레이션 중..."):
            df_res_c, df_trades_c = cached_run_custom_backtest_us(df_master, start_year_c, end_year_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)
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
