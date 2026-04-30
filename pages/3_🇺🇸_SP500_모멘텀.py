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
df_master = map_english_columns(load_archive_data(archive_path, get_folder_hash(archive_path)))

if df_master.empty: st.error("🚨 archive_sp500 폴더에 데이터가 없습니다!"); st.stop()

# 💡 [개선] 실시간 종목 정보 & NASDAQ:SNDK 형식 생성
@st.cache_resource
def get_us_stock_info_fast():
    try:
        df_sp = fdr.StockListing('S&P500')
        df_sp['Symbol'] = df_sp['Symbol'].str.replace('.', '-', regex=False)
        name_map = dict(zip(df_sp['Symbol'], df_sp['Name']))
        # 거래소 정보(있으면) 포함하여 NASDAQ:SNDK 형식 생성
        exch_map = {row['Symbol']: f"{row.get('Exchange', 'US')}:{row['Symbol']}" for _, row in df_sp.iterrows()}
        return name_map, exch_map
    except: return {}, {}

name_map, exch_map = get_us_stock_info_fast()
df_master['종목명'] = df_master['종목코드'].map(name_map).fillna(df_master['종목코드'])
df_master['통합티커'] = df_master['종목코드'].map(exch_map).fillna(df_master['종목코드'])

target_cols = ['시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']
for col in target_cols: df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

# 💡 [개선] 시가총액 전진, 종가 소수점 2자리 설정
us_main_cfg = main_cfg.copy()
us_main_cfg.update({'종가': st.column_config.NumberColumn('종가', format="%.2f"), '시가총액': st.column_config.NumberColumn('시가총액', format="%d")})
col_order_us = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '이번달수익률']

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 백테스트", "🏅 스코어 커스텀 백테스트"])

with tab1:
    c_y, c_m = st.columns([1.2, 8.8])
    selected_year = c_y.selectbox("투자 연도", sorted(df_master['투자연도'].unique().astype(str), reverse=True), format_func=lambda x: f"{x}년", key="t1_y")
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    selected_month = c_m.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m", index=len(m_list)-1)
    df_monthly = df_master[df_master['투자월'] == f"{selected_year}-{selected_month}"].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        spx_curr, spx_mas = get_us_ma_all(base_date, '^GSPC')
        ndx_curr, ndx_mas = get_us_ma_all(base_date, '^IXIC')
        # 💡 지수 이름 링크 복구
        ma_df = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#{ndx_curr:,.2f}", 'base_price': round(ndx_curr, 2), '4개월선': ndx_mas.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us(df_monthly, 30)
        for df in [df_strat1_t1, df_strat2_t1, df_us_t1]:
            df['순위'] = range(1, len(df)+1)
            # 💡 네이버 링크 & NASDAQ:SNDK 적용
            df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['통합티커']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{r['종목코드']}/total#{r['종목명']}", axis=1)

        st.columns(6)[0].metric("📈 S&P 500 1M", f"{get_us_idx_return(base_date, '^GSPC')[0]}%")
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)
        c_l, c_r = st.columns(2)
        c_l.markdown("#### 🔥 12-1M & 6-1M")
        c_l.dataframe(df_strat1_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_us, column_config=us_main_cfg)
        c_r.markdown("#### 🐎 6-1M & 3-1M (정렬: 6-1M)")
        c_r.dataframe(df_strat2_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_us, column_config=us_main_cfg)

with tab3:
    c1, c_ma, c_chk = st.columns([1.5, 1, 1.5])
    start_year, end_year = c1.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr_us')
    # 💡 마켓타이밍 n개월선 조절 추가
    ma_months_t3 = c_ma.slider("📉 마켓타이밍 (개월선)", 1, 12, 10, key='t3_ma_us')
    apply_timing = c_chk.checkbox("🛑 마켓타이밍 적용 (이탈 시 현금)", value=True, key='t3_chk_us')
    df_res, _ = run_backtest_us(df_master, start_year, end_year, ma_months_t3, apply_timing, (1, 5), (1, 5))
    if not df_res.empty: st.dataframe(get_styled_stats(pd.DataFrame([{"전략명": c, "CAGR": f"{(( (1+df_res.set_index('투자월')[c]/100).cumprod().iloc[-1]/1 )**(1/(len(df_res)/12))-1)*100:.1f}%"} for c in df_res.columns if c not in ['투자월', 'invested']])), use_container_width=True)

with tab4:
    # 💡 커스텀 탭에도 n개월 조절 추가 및 가중치 세팅
    c1, c2, c3, c4 = st.columns(4)
    w1, w3, w6, w12 = c1.number_input("1M", -0.1), c2.number_input("3M", 0.7), c3.number_input("6M", 0.4), c4.number_input("12M", 0.0)
    ma_months_t4 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 10, key='t4_ma_us')
    df_res_c, _ = run_custom_backtest_us(df_master, min_y, max_y, ma_months_t4, True, w1, w3, w6, w12, 30, 1, 10)
    if not df_res_c.empty: st.write("시뮬레이션 완료")
