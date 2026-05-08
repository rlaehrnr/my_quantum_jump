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

# 전체 순위 하이라이트 스타일 (파스텔 옐로우 - 종목명만)
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
    vix_bg, vix_border, vix_title_c, vix_val_c = ("#FFF0F0", "#FFCDD2", "#C62828", "#D84315") if is_vix_warning else ("#FFFFFF", "#d1d5db", "#64748b", "#333333")
    vix_icon = "🚨" if is_vix_warning else "📊"
    return f'''<a href="https://m.stock.naver.com/worldstock/index/.VIX/total" target="_blank" style="text-decoration: none; color: inherit;">
        <div class="title-link" style="background-color: {vix_bg}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {vix_border}; height: 95px; display: flex; flex-direction: column; justify-content: center;">
            <div style="font-size: 12px; font-weight: bold; color: {vix_title_c}; margin-bottom: 2px;">{vix_icon} VIX 35 돌파</div>
            <div style="font-size: 11px; font-weight: bold; color: {vix_title_c}; margin-bottom: 4px;">VIX {vix_35_high} - {vix_35_date_str} ({days_diff_str})</div>
            <div style="font-size: 15px; color: {vix_val_c}; font-weight:900;">{vix_latest_date_str} 고가: {vix_latest_high}</div>
        </div></a>'''

st.markdown('''<div style="margin-bottom: 20px;"><a href="https://m.stock.naver.com/worldstock/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;"><div style="display: flex; align-items: center; gap: 12px;"><h1 style="margin: 0; font-size: 2.2rem; font-weight: 800;">🇺🇸 USA 300 통합 모멘텀</h1><span style="font-size: 0.95rem; color: #10b981; background-color: #d1fae5; padding: 4px 10px; border-radius: 6px; border: 1px solid #6ee7b7;">🔗 네이버 증권</span></div></a></div>''', unsafe_allow_html=True)

# 💡 [데이터 로드]
archive_path = "archive_usa"
f_hash = get_folder_hash(archive_path) 
df_master_raw = load_archive_data(archive_path, f_hash) 

if df_master_raw.empty:
    st.error(f"🚨 {archive_path} 폴더에 데이터가 없습니다! (C를 눌러 캐시를 비워보세요)")
    st.stop()

df_master = preprocess_us_data(df_master_raw, is_daily=False)
valid_years = df_master['투자연도'].dropna().unique().astype(int).tolist()
years_list = sorted(valid_years)
min_y, max_y = (min(years_list), max(years_list)) if years_list else (2026, 2026)

us_main_cfg = main_cfg.copy()
us_main_cfg.update({'12-1개월(%)': st.column_config.NumberColumn('12-1개월(%)', format="%.2f%%"), '6-1개월(%)': st.column_config.NumberColumn('6-1개월(%)', format="%.2f%%"), '3-1개월(%)': st.column_config.NumberColumn('3-1개월(%)', format="%.2f%%"), '커스텀스코어': st.column_config.NumberColumn('커스텀스코어', format="%.2f"), '종가': st.column_config.NumberColumn('종가', format="%.2f"), '시가총액': st.column_config.NumberColumn('시가총액', format="%d")})

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
    c_y, c_m = st.columns([1.2, 8.8])
    with c_y: 
        selected_year = st.selectbox("투자 연도", [str(y) for y in sorted(years_list, reverse=True)], key="t1_y_usa")
    safe_year = int(selected_year)
    m_list = sorted(df_master[df_master['투자연도'] == safe_year]['투자월'].str.split('-').str[1].unique())
    with c_m:
        selected_month = st.radio("투자 월", m_list, horizontal=True, key="t1_m_usa", index=len(m_list)-1)
        df_monthly = df_master[df_master['투자월'] == f"{safe_year}-{selected_month}"].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        spx_curr, spx_mas = robust_get_us_ma_all(base_date, '^GSPC')
        ndx_curr, ndx_mas = robust_get_us_ma_all(base_date, '^IXIC')
        ma_df = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.IXIC#{ndx_curr:,.2f}", 'base_price': round(ndx_curr, 2), '4개월선': ndx_mas.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_monthly = add_naver_links(df_monthly)
        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us_custom(df_monthly)
        
        df_us_t1['커스텀스코어'] = (-0.1 * df_us_t1['1개월(%)']) + (0.7 * df_us_t1['3개월(%)']) + (0.4 * df_us_t1['6개월(%)'])
        df_us_t1 = df_us_t1.sort_values('커스텀스코어', ascending=False)
        df_us_t1['순위'] = range(1, len(df_us_t1) + 1)
        
        spx_1m, spx_3m = robust_get_us_idx_return(base_date, '^GSPC')
        ndx_1m, ndx_3m = robust_get_us_idx_return(base_date, '^IXIC')

        col1, col2, col3, col4, col5, col6 = st.columns([1.0, 1.0, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric("📈 S&P 500 1M", f"{spx_1m}%")
        with col2: st.metric("📈 S&P 500 3M", f"{spx_3m}%")
        with col3: st.metric("📈 NASDAQ 1M", f"{ndx_1m}%")
        with col4: st.metric("📈 NASDAQ 3M", f"{ndx_3m}%")
        with col5: 
            cy = get_cycle_year(safe_year)
            bad_m = ", ".join(f"{m}월" for m in PRESIDENTIAL_DANGEROUS_MONTHS.get(cy, []))
            st.markdown(f'<div style="background-color:#f0f2f6; padding:10px; border-radius:10px; text-align:center; border:1px solid #d1d5db; height:95px; display:flex; flex-direction:column; justify-content:center;"><div style="font-size:12px; color:#64748b;">대통령 {cy}년차</div><div style="font-size:15px; color:#D84315; font-weight:900;">🚨 위험: {bad_m}</div></div>', unsafe_allow_html=True)
        with col6:
            is_below = (spx_curr > 0) and (spx_curr < spx_mas.get(10, 0))
            status, box_c, text_c = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
            st.markdown(f'<div style="background-color:{box_c}; padding:10px; border-radius:10px; text-align:center; border:1px solid {text_c}; height:95px; display:flex; flex-direction:column; justify-content:center;"><div style="font-size:12px; color:{text_c};">최종 판단</div><div style="font-size:1.5rem; font-weight:900; color:{text_c};">{status}</div></div>', unsafe_allow_html=True)

        st.markdown("<hr>", unsafe_allow_html=True)
        c_l, c_r = st.columns(2)
        with c_l:
            col_t1, col_i1, col_r1 = st.columns([5.3, 2.8, 3.9])
            with col_t1: st.markdown(f"#### 🔥 12-1M & 6-1M <span style='font-size:13px; color:gray;'>({len(df_strat1_t1)}개)</span>", unsafe_allow_html=True)
            with col_i1: top_n_p = st.number_input("p_n", 1, max(1, len(df_strat1_t1)), 5, key="calc_p_usa", label_visibility="collapsed")
            with col_r1:
                avg_ret_p = df_strat1_t1.head(top_n_p)['이번달수익률'].mean()
                st.markdown(f"<div style='margin-top:8px; font-weight:bold;'>상위 {top_n_p}개 평균: <span style='color:{'red' if avg_ret_p>0 else 'blue'};'>{avg_ret_p:+.2f}%</span></div>", unsafe_allow_html=True)
            st.dataframe(df_strat1_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat1, column_config=us_main_cfg)
            
        with c_r:
            col_t2, col_i2, col_r2 = st.columns([5.3, 2.8, 3.9])
            with col_t2: st.markdown(f"#### 🐎 6-1M & 3-1M <span style='font-size:13px; color:gray;'>({len(df_strat2_t1)}개)</span>", unsafe_allow_html=True)
            with col_i2: top_n_s = st.number_input("s_n", 1, max(1, len(df_strat2_t1)), 5, key="calc_s_usa", label_visibility="collapsed")
            with col_r2:
                avg_ret_s = df_strat2_t1.head(top_n_s)['이번달수익률'].mean()
                st.markdown(f"<div style='margin-top:8px; font-weight:bold;'>상위 {top_n_s}개 평균: <span style='color:{'red' if avg_ret_s>0 else 'blue'};'>{avg_ret_s:+.2f}%</span></div>", unsafe_allow_html=True)
            st.dataframe(df_strat2_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat2, column_config=us_main_cfg)

        st.markdown("---")
        col_total_t, col_total_i, col_total_r = st.columns([6, 2.5, 3.5])
        with col_total_t: st.markdown("### 🌐 USA 300 전체 순위")
        with col_total_i: top_n_total = st.number_input("N위 하이라이트", 1, len(df_us_t1), 10, key="top_n_usa", label_visibility="collapsed")
        with col_total_r:
            avg_ret_total = df_us_t1.head(top_n_total)['이번달수익률'].mean()
            st.markdown(f"<div style='margin-top:8px; font-weight:bold;'>상위 {top_n_total}개 평균: <span style='color:{'red' if avg_ret_total>0 else 'blue'};'>{avg_ret_total:+.2f}%</span></div>", unsafe_allow_html=True)
            
        top_codes = df_us_t1.head(top_n_total)['종목코드'].tolist()
        st.dataframe(df_us_t1.style.apply(apply_custom_total_styling, top_codes=top_codes, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_m, column_config=us_main_cfg)

# ==========================================
# 탭 2. 실시간 데일리 순위
# ==========================================
with tab2:
    f_daily_path = 'data/momentum_data_daily_usa300.csv'
    if os.path.exists(f_daily_path):
        df_daily_raw = pd.read_csv(f_daily_path)
        df_daily = preprocess_us_data(df_daily_raw, is_daily=True)
        b_date_d = pd.to_datetime(df_daily['기준일'].iloc[0]).strftime('%Y-%m-%d') if '기준일' in df_daily.columns else "오늘"
        st.markdown(f"**🕒 데일리 기준일:** {b_date_d}")
        
        spx_curr_d, spx_mas_d = robust_get_us_ma_all(b_date_d, '^GSPC')
        ma_df_d = pd.DataFrame([{'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr_d:,.2f}", 'base_price': round(spx_curr_d, 2), '4개월선': spx_mas_d.get(4, 0), '5개월선': spx_mas_d.get(5, 0), '6개월선': spx_mas_d.get(6, 0), '10개월선': spx_mas_d.get(10, 0), '12개월선': spx_mas_d.get(12, 0)}])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_daily = add_naver_links(df_daily)
        df_us_d, df_strat1_d, df_strat2_d = get_strategy_stocks_us_custom(df_daily)
        
        c_d1, c_d2 = st.columns(2)
        with c_d1:
            st.markdown("#### 🔥 12-1M & 6-1M")
            st.dataframe(df_strat1_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_d1, column_config=us_main_cfg)
        with c_d2:
            st.markdown("#### 🐎 6-1M & 3-1M")
            st.dataframe(df_strat2_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_d2, column_config=us_main_cfg)
            
        st.markdown("---")
        top_n_d = st.session_state.get("top_n_usa", 10)
        st.markdown(f"### 🌐 USA 300 전체 순위 (하이라이트 {top_n_d}위 연동)")
        top_codes_d = df_us_d.head(top_n_d)['종목코드'].tolist()
        st.dataframe(df_us_d.style.apply(apply_custom_total_styling, top_codes=top_codes_d, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_d, column_config=us_main_cfg)
    else:
        st.info("데일리 데이터(`data/momentum_data_daily_usa300.csv`)가 없습니다.")

# ==========================================
# 탭 3. 전략 백테스트
# ==========================================
with tab3:
    with st.form("bt_form_usa", border=False):
        c1, c2, c3 = st.columns([1.5, 1, 1.5])
        with c1: start_y, end_y = st.slider("📅 기간", min_y, max_y, (min_y, max_y), key='bt_yr_usa')
        with c2: ma_m = st.slider("📉 마켓타이밍", 1, 12, 10, key='bt_ma_usa')
        with c3:
            st.markdown("<div style='margin-top:35px;'></div>", unsafe_allow_html=True)
            apply_t = st.checkbox("🛑 마켓타이밍 적용", value=True, key='bt_chk_usa')
        
        c_rnk1, c_rnk2, c_btn = st.columns([1, 1, 0.8])
        with c_rnk1: r1_s, r1_e = st.slider("🔥 12-1&6-1 순위", 1, 30, (1, 5))
        with c_rnk2: r2_s, r2_e = st.slider("🐎 6-1&3-1 순위", 1, 30, (1, 5))
        with c_btn:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            run_bt = st.form_submit_button("✅ 백테스트 실행", use_container_width=True)

    if run_bt or 'bt_run_usa' not in st.session_state:
        st.session_state['bt_run_usa'] = True
        spx_hist = get_spx_history_cached()
        with st.spinner("시뮬레이션 중..."):
            df_res, df_trades = run_backtest_us_fast(df_master, start_y, end_y, ma_m, apply_t, (r1_s, r1_e), (r2_s, r2_e), 150, 150, 150, spx_hist)
            if not df_res.empty:
                s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
                df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
                
                stats = []
                for col in s_cols:
                    fv = df_cum[col].iloc[-1]
                    cagr = ((fv/100)**(1/(len(df_res)/12))-1)*100 if fv > 0 else -100
                    mdd = ((df_cum[col]/df_cum[col].cummax())-1).min()*100
                    stats.append({"전략명": col, "CAGR": f"{cagr:.1f}%", "누적": f"{fv-100:,.1f}%", "MDD": f"{mdd:.1f}%"})
                
                st.dataframe(get_styled_stats(pd.DataFrame(stats)), use_container_width=True, hide_index=True)
                st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 수익률 곡선"), use_container_width=True)

# ==========================================
# 탭 4. 스코어 커스텀 백테스트
# ==========================================
with tab4:
    with st.form("custom_form_usa", border=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1: w1 = st.number_input("📉 1M 가중치", value=-0.1, step=0.1)
        with c2: w3 = st.number_input("📈 3M 가중치", value=0.7, step=0.1)
        with c3: w6 = st.number_input("📈 6M 가중치", value=0.4, step=0.1)
        with c4: w12 = st.number_input("📈 12M 가중치", value=0.0, step=0.1)
        
        c5, c6, c7 = st.columns([1, 1, 0.8])
        with c5: pct = st.slider("🏅 상위 %", 5, 50, 30, step=5)
        with c6: r_s, r_e = st.slider("🏅 매수 순위", 1, 30, (1, 10))
        with c7:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            run_c = st.form_submit_button("✅ 실행", use_container_width=True)

    if run_c or 'custom_run_usa' not in st.session_state:
        st.session_state['custom_run_usa'] = True
        with st.spinner("커스텀 시뮬레이션 중..."):
            df_res_c, df_trades_c = cached_run_custom_backtest_us(df_master, min_y, max_y, 10, True, w1, w3, w6, w12, pct, r_s, r_e)
            if not df_res_c.empty:
                df_cum_c = (1 + df_res_c.set_index('투자월')[['커스텀 전략']] / 100).cumprod() * 100
                fv_c = df_cum_c['커스텀 전략'].iloc[-1]
                cagr_c = ((fv_c/100)**(1/(len(df_res_c)/12))-1)*100 if fv_c > 0 else -100
                mdd_c = ((df_cum_c['커스텀 전략']/df_cum_c['커스텀 전략'].cummax())-1).min()*100
                
                st.metric("연평균 수익률(CAGR)", f"{cagr_c:.1f}%", f"MDD: {mdd_c:.1f}%")
                st.plotly_chart(px.line(df_cum_c.reset_index(), x='투자월', y='커스텀 전략', log_y=True, title="커스텀 전략 성과"), use_container_width=True)
