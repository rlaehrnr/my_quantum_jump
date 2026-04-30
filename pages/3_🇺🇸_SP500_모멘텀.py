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
from utils.calculator import get_us_ma_all, get_us_idx_return, calc_us_momentum, get_strategy_stocks_us, map_english_columns, run_backtest_us, run_custom_backtest_us

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

archive_path, f_daily = "archive_sp500", 'data/momentum_data_daily_sp500.csv'
df_master = load_archive_data(archive_path, get_folder_hash(archive_path))

if df_master.empty: 
    st.error("🚨 archive_sp500 폴더에 데이터가 없습니다!")
    st.stop()

# 💡 1. 영어 컬럼 -> 한글 매핑
df_master = map_english_columns(df_master)

# 💡 2. [핵심 수정] 에러 방지: 필요한 컬럼이 없으면 0으로라도 만들어줌
target_cols = ['시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']
for col in target_cols:
    if col in df_master.columns:
        df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)
    else:
        df_master[col] = 0 # 컬럼이 아예 없으면 0으로 초기화하여 KeyError 방지

# 💡 3. 실시간 종목 정보 & NASDAQ:SNDK 형식 생성
@st.cache_resource
def get_us_stock_info_fast():
    try:
        df_sp = fdr.StockListing('S&P500')
        df_sp['Symbol'] = df_sp['Symbol'].str.replace('.', '-', regex=False)
        name_map = dict(zip(df_sp['Symbol'], df_sp['Name']))
        exch_map = {row['Symbol']: f"{row.get('Exchange', 'US')}:{row['Symbol']}" for _, row in df_sp.iterrows()}
        return name_map, exch_map
    except: return {}, {}

name_map, exch_map = get_us_stock_info_fast()
df_master['종목명'] = df_master['종목코드'].map(name_map).fillna(df_master['종목코드'])
df_master['통합티커'] = df_master['종목코드'].map(exch_map).fillna(df_master['종목코드'])

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

us_main_cfg = main_cfg.copy()
us_main_cfg.update({'종가': st.column_config.NumberColumn('종가', format="%.2f"), '시가총액': st.column_config.NumberColumn('시가총액', format="%d")})
col_order_us = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '이번달수익률']

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트", "🏅 스코어 커스텀 백테스트"])

with tab1:
    c_y, c_m = st.columns([1.2, 8.8])
    avail_years = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    selected_year = c_y.selectbox("투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y")
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    selected_month = c_m.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m", index=len(m_list)-1)
    df_monthly = df_master[df_master['투자월'] == f"{selected_year}-{selected_month}"].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        spx_curr, spx_mas = get_us_ma_all(base_date, '^GSPC')
        ndx_curr, ndx_mas = get_us_ma_all(base_date, '^IXIC')
        ma_df = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#{ndx_curr:,.2f}", 'base_price': round(ndx_curr, 2), '4개월선': ndx_mas.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us(df_monthly, 30)
        for df in [df_strat1_t1, df_strat2_t1, df_us_t1]:
            df['순위'] = range(1, len(df)+1)
            df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['종목명']}", axis=1)

        st.columns(6)[0].metric("📈 S&P 500 1M", f"{get_us_idx_return(base_date, '^GSPC')[0]}%")
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)
        c_l, c_r = st.columns(2)
        c_l.markdown("#### 🔥 12-1M & 6-1M")
        c_l.dataframe(df_strat1_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_us, column_config=us_main_cfg)
        c_r.markdown("#### 🐎 6-1M & 3-1M (정렬: 6-1M)")
        c_r.dataframe(df_strat2_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_us, column_config=us_main_cfg)

with tab2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily)
        df_daily = map_english_columns(df_daily)
        if name_map: df_daily['종목명'] = df_daily['종목코드'].map(name_map).fillna(df_daily['종목명'])
        if exch_map: df_daily['통합티커'] = df_daily['종목코드'].map(exch_map).fillna(df_daily['종목코드'])
        
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        safe_date = b_date_d if b_date_d != "오늘" else datetime.today().strftime('%Y-%m-%d')
        
        for col in target_cols:
            if col in df_daily.columns:
                df_daily[col] = pd.to_numeric(df_daily[col], errors='coerce').fillna(0)
        
        st.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        
        spx_curr_d, spx_mas_d = get_us_ma_all(safe_date, '^GSPC')
        ndx_curr_d, ndx_mas_d = get_us_ma_all(safe_date, '^IXIC')
        ma_df_d = pd.DataFrame([
            {'지수_L': "https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#{spx_curr_d:,.2f}", 'base_price': round(spx_curr_d, 2), '4개월선': spx_mas_d.get(4, 0), '5개월선': spx_mas_d.get(5, 0), '6개월선': spx_mas_d.get(6, 0), '10개월선': spx_mas_d.get(10, 0), '12개월선': spx_mas_d.get(12, 0)},
            {'지수_L': "https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#{ndx_curr_d:,.2f}", 'base_price': round(ndx_curr_d, 2), '4개월선': ndx_mas_d.get(4, 0), '5개월선': ndx_mas_d.get(5, 0), '6개월선': ndx_mas_d.get(6, 0), '10개월선': ndx_mas_d.get(10, 0), '12개월선': ndx_mas_d.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_us_d, df_strat1_d, df_strat2_d = get_strategy_stocks_us(df_daily, 30)
        for df in [df_strat1_d, df_strat2_d, df_us_d]:
            df['순위'] = range(1, len(df)+1)
            df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['종목명']}", axis=1)

        c_d1, c_d2 = st.columns(2)
        c_d1.markdown("#### 🔥 12-1M & 6-1M")
        c_d1.dataframe(df_strat1_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_us, column_config=us_main_cfg)
        c_d2.markdown("#### 🐎 6-1M & 3-1M (정렬: 6-1M)")
        c_d2.dataframe(df_strat2_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_us, column_config=us_main_cfg)

with tab3:
    st.markdown("<h4 style='margin:0;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
    c1, c_ma_us, c_chk = st.columns([1.5, 1, 1.5])
    with c1: start_year, end_year = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr_us')
    with c_ma_us: ma_months_t3 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 10, key='t3_ma_us')
    with c_chk:
        st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
        apply_timing = st.checkbox("🛑 마켓타이밍 적용 (이탈 시 현금)", value=True, key='t3_chk_us')
    
    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
    c3, c5 = st.columns([1, 1])
    with c3: rank_p_s, rank_p_e = st.slider("🔥 12-1&6-1 전략 (매수 순위)", 1, 30, (1, 5), key='t3_rnk1_us')
    with c5: rank_s_s, rank_s_e = st.slider("🐎 6-1&3-1 전략 (매수 순위)", 1, 30, (1, 5), key='t3_rnk2_us')

    with st.spinner("미국 모멘텀 백테스트 구동 중..."):
        df_res, _ = run_backtest_us(df_master, start_year, end_year, ma_months_t3, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e))
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 성과 (Log Scale)"), use_container_width=True)

with tab4:
    c1, c2, c3, c4 = st.columns(4)
    with c1: w1 = st.number_input("1M 가중치", value=-0.1)
    with c2: w3 = st.number_input("3M 가중치", value=0.7)
    with c3: w6 = st.number_input("6M 가중치", value=0.4)
    with c4: w12 = st.number_input("12M 가중치", value=0.0)
    ma_months_t4 = st.slider("📉 마켓타이밍 (개월선) ", 1, 12, 10, key='t4_ma_us')
    df_res_c, _ = run_custom_backtest_us(df_master, min_y, max_y, ma_months_t4, True, w1, w3, w6, w12, 30, 1, 10)
    if not df_res_c.empty: st.write("✅ 시뮬레이션 완료. 결과 차트를 생성할 수 있습니다.")
