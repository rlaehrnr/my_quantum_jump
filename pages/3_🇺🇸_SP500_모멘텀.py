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

df_master = map_english_columns(df_master)

target_cols = ['시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']
for col in target_cols:
    if col in df_master.columns: df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)
    else: df_master[col] = 0

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

# 💡 [핵심] 네이버 증권 예외 규칙 사전 정의 (.O 기본, 지정 종목은 .K)
naver_exceptions = {'CIEN': '.K', 'COHR': '.K', 'EQNR': '.K', 'DELL': '.K'}

def get_naver_ticker(code):
    suffix = naver_exceptions.get(code, '.O')
    return f"{code}{suffix}"

@st.cache_data(show_spinner=False)
def cached_run_backtest_us(df, start_year, end_year, ma_months, apply_timing, rank_s1, rank_s2):
    return run_backtest_us(df, start_year, end_year, ma_months, apply_timing, rank_s1, rank_s2, top_pct=30)

@st.cache_data(show_spinner=False)
def cached_run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    return run_custom_backtest_us(df, start_year_c, end_year_c, ma_months_c, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)

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
        
        # 💡 [핵심] 지수(Index) 링크 처리: 지수_L은 total로, 현재가_L은 fchart로
        ma_df = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr:,.2f}", 'base_price': round(spx_curr, 2), '4개월선': spx_mas.get(4, 0), '5개월선': spx_mas.get(5, 0), '6개월선': spx_mas.get(6, 0), '10개월선': spx_mas.get(10, 0), '12개월선': spx_mas.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.IXIC#{ndx_curr:,.2f}", 'base_price': round(ndx_curr, 2), '4개월선': ndx_mas.get(4, 0), '5개월선': ndx_mas.get(5, 0), '6개월선': ndx_mas.get(6, 0), '10개월선': ndx_mas.get(10, 0), '12개월선': ndx_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_us_t1, df_strat1_t1, df_strat2_t1 = get_strategy_stocks_us(df_monthly, 30)
        for df in [df_strat1_t1, df_strat2_t1, df_us_t1]:
            df['순위'] = range(1, len(df)+1)
            # 💡 [핵심] 개별 종목 링크 처리: 티커_L은 total로, 종목명_L은 fchart로 (.O / .K 규칙 적용)
            df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{get_naver_ticker(r['종목코드'])}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/foreign/stock/{get_naver_ticker(r['종목코드'])}#{r['종목명']}", axis=1)

        st.columns(6)[0].metric("📈 S&P 500 1M", f"{get_us_idx_return(base_date, '^GSPC')[0]}%")
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)
        c_l, c_r = st.columns(2)
        c_l.markdown("#### 🔥 12-1M & 6-1M")
        c_l.dataframe(df_strat1_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat1, column_config=us_main_cfg)
        c_r.markdown("#### 🐎 6-1M & 3-1M (정렬: 6-1M)")
        c_r.dataframe(df_strat2_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_strat2, column_config=us_main_cfg)

with tab2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily)
        df_daily = map_english_columns(df_daily)
        if name_map: df_daily['종목명'] = df_daily['종목코드'].map(name_map).fillna(df_daily['종목명'])
        if exch_map: df_daily['통합티커'] = df_daily['종목코드'].map(exch_map).fillna(df_daily['종목코드'])
        else: df_daily['통합티커'] = df_daily['종목코드']
        
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        safe_date = b_date_d if b_date_d != "오늘" else datetime.today().strftime('%Y-%m-%d')
        
        for col in target_cols:
            if col in df_daily.columns: df_daily[col] = pd.to_numeric(df_daily[col], errors='coerce').fillna(0)
            else: df_daily[col] = 0
        
        st.markdown(f"<div style='margin-bottom: 5px; font-size:0.95rem; font-weight:600;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        
        spx_curr_d, spx_mas_d = get_us_ma_all(safe_date, '^GSPC')
        ndx_curr_d, ndx_mas_d = get_us_ma_all(safe_date, '^IXIC')
        ma_df_d = pd.DataFrame([
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.INX/total#S&P500", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.INX#{spx_curr_d:,.2f}", 'base_price': round(spx_curr_d, 2), '4개월선': spx_mas_d.get(4, 0), '5개월선': spx_mas_d.get(5, 0), '6개월선': spx_mas_d.get(6, 0), '10개월선': spx_mas_d.get(10, 0), '12개월선': spx_mas_d.get(12, 0)},
            {'지수_L': f"https://m.stock.naver.com/worldstock/index/.IXIC/total#NASDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/foreign/index/.IXIC#{ndx_curr_d:,.2f}", 'base_price': round(ndx_curr_d, 2), '4개월선': ndx_mas_d.get(4, 0), '5개월선': ndx_mas_d.get(5, 0), '6개월선': ndx_mas_d.get(6, 0), '10개월선': ndx_mas_d.get(10, 0), '12개월선': ndx_mas_d.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_us_d, df_strat1_d, df_strat2_d = get_strategy_stocks_us(df_daily, 30)
        for df in [df_strat1_d, df_strat2_d, df_us_d]:
            df['순위'] = range(1, len(df)+1)
            # 💡 [핵심] 데일리 탭에도 네이버 예외 규칙(.O / .K) 완벽 반영
            df['통합티커_L'] = df.apply(lambda r: f"https://m.stock.naver.com/worldstock/stock/{get_naver_ticker(r['종목코드'])}/total#{r.get('통합티커', r['종목코드'])}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/foreign/stock/{get_naver_ticker(r['종목코드'])}#{r['종목명']}", axis=1)

        c_d1, c_d2 = st.columns(2)
        c_d1.markdown("#### 🔥 12-1M & 6-1M")
        c_d1.dataframe(df_strat1_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_d1, column_config=us_main_cfg)
        c_d2.markdown("#### 🐎 6-1M & 3-1M (정렬: 6-1M)")
        c_d2.dataframe(df_strat2_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=col_order_d2, column_config=us_main_cfg)

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
        df_res, df_trades = cached_run_backtest_us(df_master, start_year, end_year, ma_months_t3, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e))
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
            analysis_strat_t3 = st.radio("분석할 전략을 선택하세요", s_cols_raw, horizontal=True, index=0, key="analysis_radio_t3_us")
            
            col_hm, col_mdd = st.columns([6, 4])
            with col_hm: st.dataframe(get_monthly_heatmap(df_res, analysis_strat_t3), use_container_width=True)
            with col_mdd: st.dataframe(get_mdd_history(df_cum[analysis_strat_t3]), use_container_width=True, hide_index=True)
            
            st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)"), use_container_width=True)
            with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)

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
            df_res_c, df_trades_c = cached_run_custom_backtest_us(df_master, start_year_c, end_year_c, ma_months_t4, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)
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
