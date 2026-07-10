import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

st.set_page_config(page_title="KOSPI 200 모멘텀", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS, get_kospi_ma_all, get_kosdaq_ma_all, get_strategy_stocks_korea, run_backtest_k200, get_kospi_timing_for_backtest, get_idx_kr, get_gold_returns
from utils.ui_components import inject_custom_css, apply_korea_styling, style_kospi_ma, get_styled_stats, get_mdd_history, get_monthly_heatmap, ma_cfg, main_cfg, generate_excel_report_cached, render_vix_widget
from utils.data_loader import load_archive_data, get_folder_hash, load_daily_data

inject_custom_css()

# 💡 [중복 제거] get_kosdaq_ma_all, generate_excel_report_cached, render_vix_widget 모두 utils로 이동됨


st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="/" target="_self" class="title-link" style="text-decoration: none; color: inherit;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
                <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">🎯 KOSPI 200 모멘텀 터미널</h1>
                <span style="font-size: 0.95rem; color: #3b82f6; background-color: #eff6ff; padding: 4px 10px; border-radius: 6px; border: 1px solid #bfdbfe; white-space: nowrap;">🏠 종합 대시보드</span>
            </div>
        </a>
    </div>
''', unsafe_allow_html=True)

archive_path = "archive_kospi"
f_hash = get_folder_hash(archive_path) 
df_master = load_archive_data(archive_path, f_hash) 
f_daily = 'data/momentum_data_daily.csv'

if df_master.empty:
    st.error("🚨 archive_kospi 폴더에 데이터가 없습니다!")
    st.stop()

df_master['종목코드'] = df_master['종목코드'].astype(str).str.zfill(6)
df_master = df_master[df_master['종목코드'].str.endswith('0')].copy()

target_cols = ['시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '다음달수익률(%)', '이번달수익률']
for col in target_cols:
    if col in df_master.columns:
        df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)

if '시가총액' in df_master.columns and df_master['시가총액'].max() > 1000000000:
    df_master['시가총액'] = df_master['시가총액'] / 100000000

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

@st.cache_data(show_spinner=False)
def cached_run_backtest_korea(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct, trading_cost_pct=0.25, use_gold=False, _gold_returns=None):
    return run_backtest_k200(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct, trading_cost_pct=trading_cost_pct, gold_returns=_gold_returns, use_gold=use_gold)

@st.cache_data(show_spinner=False)
def cached_run_custom_backtest(df, start_year_c, end_year_c, ma_months_t4, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    timing_dict = get_kospi_timing_for_backtest(ma_months_t4)
    records_c, trade_logs_c = [], []
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year_c <= m_yr <= end_year_c): continue
        df_calc = df[df['투자월'] == m_str].copy()
        if df_calc.empty: continue
        
        # 💡 커스텀 백테스트는 MA 이탈만 마켓타이밍으로 사용 (1&3M 하락 100개 조건 미사용)
        # MA 키는 전략조합과 동일하게 '투자월' 사용 (이전엔 종목선정일 기준으로 어긋남)
        is_below_ma = timing_dict.get(m_str, False)
        mult_c = 0.0 if (apply_timing_c and is_below_ma) else 1.0
        
        df_calc['스코어'] = (df_calc['1개월(%)']*w1) + (df_calc['3개월(%)']*w3) + (df_calc['6개월(%)']*w6) + (df_calc['12개월(%)']*w12)
        q_limit = df_calc['스코어'].quantile(1 - (custom_pct / 100.0))
        target = df_calc[df_calc['스코어']>=q_limit].sort_values('스코어', ascending=False).iloc[rank_c_s-1:rank_c_e]
        
        records_c.append({'투자월': m_str, 'invested': mult_c > 0, '커스텀 전략': (target['이번달수익률'].mean() * mult_c) if not target.empty else 0})
        for i, (_, r) in enumerate(target.iterrows()): trade_logs_c.append({'투자월': m_str, '전략': '커스텀', '순위': f"{i+rank_c_s}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
    return pd.DataFrame(records_c), pd.DataFrame(trade_logs_c)

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 조합 백테스트", "🏅 스코어 커스텀 백테스트"])

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

        kospi_curr, kospi_mas = get_kospi_ma_all(base_date)
        kosdaq_curr, kosdaq_mas = get_kosdaq_ma_all(base_date)
        ma_df = pd.DataFrame([
            {'지수_L': "https://m.stock.naver.com/domestic/index/KOSPI/total#KOSPI", '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSPI#{kospi_curr:,.2f}", 'base_price': round(kospi_curr, 2), '4개월선': kospi_mas.get(4, 0), '5개월선': kospi_mas.get(5, 0), '6개월선': kospi_mas.get(6, 0), '10개월선': kospi_mas.get(10, 0), '12개월선': kospi_mas.get(12, 0)},
            {'지수_L': "https://m.stock.naver.com/domestic/index/KOSDAQ/total#KOSDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSDAQ#{kosdaq_curr:,.2f}", 'base_price': round(kosdaq_curr, 2), '4개월선': kosdaq_mas.get(4, 0), '5개월선': kosdaq_mas.get(5, 0), '6개월선': kosdaq_mas.get(6, 0), '10개월선': kosdaq_mas.get(10, 0), '12개월선': kosdaq_mas.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_korea_t1, df_perf_t1, df_spec_t1 = get_strategy_stocks_korea(df_monthly)
        kospi_1m, kospi_3m = get_idx_kr(base_date)
        neg_1m_cnt = (df_korea_t1['1개월(%)'] < 0).sum()
        neg_3m_cnt = (df_korea_t1['3개월(%)'] < 0).sum()
        
        df_perf_t1['순위'] = range(1, len(df_perf_t1) + 1)
        df_spec_t1['순위'] = range(1, len(df_spec_t1) + 1)
        if '시가총액' in df_korea_t1.columns:
            df_korea_t1 = df_korea_t1.sort_values('시가총액', ascending=False)
        df_korea_t1['순위'] = range(1, len(df_korea_t1) + 1)

        cycle_year_t1 = get_cycle_year(int(selected_year))
        bad_m_str_t1 = ", ".join(f"{m}월" for m in PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year_t1, [])) or "없음"
        
        is_bad_market = (neg_1m_cnt >= 100) and (neg_3m_cnt >= 100)
        is_below_ma = (kospi_curr > 0) and (kospi_curr < kospi_mas.get(6, 0))
        status, box_c, text_c = ("🛑 투자 중지 (금 투자)", "#FFEBEE", "#C62828") if (is_bad_market or is_below_ma) else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc = ("하락장" if is_bad_market else "") + (" + " if is_bad_market and is_below_ma else "") + ("6개월선 이탈" if is_below_ma else "")
        if not is_bad_market and not is_below_ma: reason_desc = "안전"

        col1, col2, col3, col4, col5, col6 = st.columns([0.9, 0.9, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric("📈 KOSPI 1M", f"{kospi_1m}%")
        with col2: st.metric("📈 KOSPI 3M", f"{kospi_3m}%")
        with col3: st.metric("📉 1개월 하락", f"{neg_1m_cnt}개")
        with col4: st.metric("📉 3개월 하락", f"{neg_3m_cnt}개")
        with col5: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 12px; font-weight: bold; color: #64748b; margin-bottom: 2px;">🇺🇸대통령 <span style="color:#0047AB;">{cycle_year_t1}년차</span> ({selected_year}년)</div><div style="font-size: 16px; color: #D84315; font-weight:900;">🚨 위험달: {bad_m_str_t1}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_c}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_c}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_c}; font-weight: bold;">최종 판단 ({reason_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_c};">{status}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_perf_t1, df_spec_t1, df_korea_t1]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#KOSPI:{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)

        c_l, c_r = st.columns(2)
        count_p, count_s = len(df_perf_t1), len(df_spec_t1)
        with c_l:
            col_t1, col_i1, col_r1 = st.columns([4, 2, 4])
            with col_t1: st.markdown(f"<h4 style='margin:0;'>🔥 퍼펙트 상승 <span style='font-size:13px; color:gray;'>({count_p}개)</span></h4>", unsafe_allow_html=True)
            with col_i1: top_n_p = st.number_input("p_n", 1, max(1, count_p), min(6, count_p) if count_p > 0 else 1, key="calc_p", label_visibility="collapsed")
            with col_r1:
                avg_ret_p = df_perf_t1.head(top_n_p)['이번달수익률'].mean() if count_p > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_p}개 평균: <span style='color:{'#D32F2F' if avg_ret_p>0 else '#1976D2'};'>{avg_ret_p:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">1,3,6,12M 수익률 모두 상위 30% 이내 & 0보다 큰 종목 (3M 순)</p>', unsafe_allow_html=True)
            
        with c_r:
            col_t2, col_i2, col_r2 = st.columns([4, 2, 4])
            with col_t2: st.markdown(f"<h4 style='margin:0;'>🐎 달리는 말 <span style='font-size:13px; color:gray;'>({count_s}개)</span></h4>", unsafe_allow_html=True)
            with col_i2: top_n_s = st.number_input("s_n", 1, max(1, count_s), min(2, count_s) if count_s > 0 else 1, key="calc_s", label_visibility="collapsed")
            with col_r2:
                avg_ret_s = df_spec_t1.head(top_n_s)['이번달수익률'].mean() if count_s > 0 else 0
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold;'>상위 {top_n_s}개 평균: <span style='color:{'#D32F2F' if avg_ret_s>0 else '#1976D2'};'>{avg_ret_s:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12M 수익률 상위 30% 이내 & 1M 수익률 상위 10% 이내 (1M 순)</p>', unsafe_allow_html=True)

        overlap_codes = set(df_perf_t1.head(top_n_p)['종목코드']).intersection(set(df_spec_t1.head(top_n_s)['종목코드']))
        
        with c_l:
            st.dataframe(df_perf_t1.style.apply(apply_korea_styling, highlight_codes=df_perf_t1.head(top_n_p)['종목코드'].tolist(), overlap_codes=overlap_codes, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)
        with c_r:
            st.dataframe(df_spec_t1.style.apply(apply_korea_styling, highlight_codes=df_spec_t1.head(top_n_s)['종목코드'].tolist(), overlap_codes=overlap_codes, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '1개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)

        st.markdown("---")
        st.markdown(f"### 🏆 전체 시가총액 순위 <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 선정일: {base_date}</span>", unsafe_allow_html=True)
        cols_m = ['순위'] + [c for c in ['통합티커_L', '종목명_L', '시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'] if c in df_korea_t1.columns]
        st.dataframe(df_korea_t1.style.apply(apply_korea_styling, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_m, column_config=main_cfg)

with tab2:
    df_daily = load_daily_data("momentum_data_daily.csv")
    if not df_daily.empty:
        df_daily['종목코드'] = df_daily['종목코드'].astype(str).str.zfill(6)
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        safe_date = b_date_d if b_date_d != "오늘" else datetime.today().strftime('%Y-%m-%d')
        
        for col in ['시가총액', '종가', '거래량']:
            if col in df_daily.columns:
                df_daily[col] = pd.to_numeric(df_daily[col], errors='coerce').fillna(0)
                
        if '시가총액' in df_daily.columns and df_daily['시가총액'].max() > 10000000:
            df_daily['시가총액'] = df_daily['시가총액'] / 100000000
        
        col_hd, col_rf = st.columns([8, 1.2], vertical_alignment="center")
        with col_hd:
            st.markdown(f"<div style='font-size:0.95rem; font-weight:600;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        with col_rf:
            if st.button("🔄 새로고침", key="daily_refresh_k200", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        
        kospi_curr_d, kospi_mas_d = get_kospi_ma_all(safe_date)
        kosdaq_curr_d, kosdaq_mas_d = get_kosdaq_ma_all(safe_date)
        ma_df_d = pd.DataFrame([
            {'지수_L': "https://m.stock.naver.com/domestic/index/KOSPI/total#KOSPI", '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSPI#{kospi_curr_d:,.2f}", 'base_price': round(kospi_curr_d, 2), '4개월선': kospi_mas_d.get(4, 0), '5개월선': kospi_mas_d.get(5, 0), '6개월선': kospi_mas_d.get(6, 0), '10개월선': kospi_mas_d.get(10, 0), '12개월선': kospi_mas_d.get(12, 0)},
            {'지수_L': "https://m.stock.naver.com/domestic/index/KOSDAQ/total#KOSDAQ", '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSDAQ#{kosdaq_curr_d:,.2f}", 'base_price': round(kosdaq_curr_d, 2), '4개월선': kosdaq_mas_d.get(4, 0), '5개월선': kosdaq_mas_d.get(5, 0), '6개월선': kosdaq_mas_d.get(6, 0), '10개월선': kosdaq_mas_d.get(10, 0), '12개월선': kosdaq_mas_d.get(12, 0)}
        ])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_korea_d, df_perf_d, df_spec_d = get_strategy_stocks_korea(df_daily)
        kospi_1m_d, kospi_3m_d = get_idx_kr(safe_date)
        neg_1m_d = (df_korea_d['1개월(%)'] < 0).sum()
        neg_3m_d = (df_korea_d['3개월(%)'] < 0).sum()
        
        df_perf_d['순위'] = range(1, len(df_perf_d) + 1)
        df_spec_d['순위'] = range(1, len(df_spec_d) + 1)
        cap_col_d = '시가총액(억)' if '시가총액(억)' in df_korea_d.columns else '시가총액'
        if cap_col_d in df_korea_d.columns:
            df_korea_d = df_korea_d.sort_values(cap_col_d, ascending=False)
        df_korea_d['순위'] = range(1, len(df_korea_d) + 1)

        is_below_ma_d = (kospi_curr_d > 0) and (kospi_curr_d < kospi_mas_d.get(6, 0))
        is_bad_market_d = (neg_1m_d >= 100) and (neg_3m_d >= 100)
        status_d, box_d, text_d = ("🛑 투자 중지 (금 투자)", "#FFEBEE", "#C62828") if (is_bad_market_d or is_below_ma_d) else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        reason_desc_d = ("하락장" if is_bad_market_d else "") + (" + " if is_bad_market_d and is_below_ma_d else "") + ("6개월선 이탈" if is_below_ma_d else "")
        if not is_bad_market_d and not is_below_ma_d: reason_desc_d = "안전"

        col1d, col2d, col3d, col4d, col5d, col6d = st.columns([0.9, 0.9, 1.0, 1.0, 1.4, 1.6])
        with col1d: st.metric("📈 KOSPI 1M", f"{kospi_1m_d}%")
        with col2d: st.metric("📈 KOSPI 3M", f"{kospi_3m_d}%")
        with col3d: st.metric("📉 1개월 하락", f"{neg_1m_d}개")
        with col4d: st.metric("📉 3개월 하락", f"{neg_3m_d}개")
        with col5d: st.markdown(render_vix_widget(safe_date), unsafe_allow_html=True)
        with col6d: st.markdown(f'<div style="background-color: {box_d}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_d}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_d}; font-weight: bold;">오늘의 시장 상태 ({reason_desc_d})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_d};">{status_d}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_perf_d, df_spec_d, df_korea_d]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#KOSPI:{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)

        c_d1, c_d2 = st.columns(2)
        overlap_d = set(df_perf_d.head(top_n_p)['종목코드']).intersection(set(df_spec_d.head(top_n_s)['종목코드']))
        
        with c_d1:
            st.markdown(f"<h4 style='margin:0;'>🔥 퍼펙트 상승 <span style='font-size:13px; color:gray;'>({len(df_perf_d)}개)</span></h4>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">1,3,6,12M 수익률 모두 상위 30% 이내 & 0보다 큰 종목 (3M 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_perf_d.style.apply(apply_korea_styling, highlight_codes=df_perf_d.head(top_n_p)['종목코드'].tolist(), overlap_codes=overlap_d, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)'], column_config=main_cfg)
        with c_d2:
            st.markdown(f"<h4 style='margin:0;'>🐎 달리는 말 <span style='font-size:13px; color:gray;'>({len(df_spec_d)}개)</span></h4>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12M 수익률 상위 30% 이내 & 1M 수익률 상위 10% 이내 (1M 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_spec_d.style.apply(apply_korea_styling, highlight_codes=df_spec_d.head(top_n_s)['종목코드'].tolist(), overlap_codes=overlap_d, axis=1), use_container_width=True, hide_index=True, column_order=['순위', '통합티커_L', '종목명_L', '1개월(%)', '12개월(%)'], column_config=main_cfg)
            
        st.markdown("---")
        st.markdown(f"### 🏆 전체 시가총액 순위 <span style='font-size: 0.85rem; color: #9ca3af; font-weight:normal;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span>", unsafe_allow_html=True)
        cols_d = ['순위'] + [c for c in ['통합티커_L', '종목명_L', '시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)'] if c in df_korea_d.columns]
        st.dataframe(df_korea_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, height=600, hide_index=True, column_order=cols_d, column_config=main_cfg)
    else:
        st.info("데일리 데이터 파일이 아직 생성되지 않았습니다.")

# ==========================================
# 탭 3. 전략 조합 백테스트
# ==========================================
with tab3:
    head_c, chk_c = st.columns([1.3, 3.0])
    with head_c:
        st.markdown("<h4 style='margin:0; padding-top:6px;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
    with chk_c:
        cca, ccb = st.columns(2)
        with cca: apply_timing = st.checkbox("🛑 마켓타이밍 적용 (1&3M 하락 100개↑ & MA 이탈 시 현금)", value=True, key='t3_chk')
        with ccb: use_gold_t3 = st.checkbox("🥇 방어 시 금 투자 (하락장 1개월 연장)", value=True, key='t3_gold')

    c1, c_ma, c_cost = st.columns([1, 1, 1])
    with c1: start_year, end_year = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr')
    with c_ma: ma_months_t3 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 6, key='t3_ma')
    with c_cost: trading_cost_pct_t3 = st.slider("💰 거래비용(편도%)", 0.0, 0.5, 0.25, 0.05, key='t3_cost')

    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
    c2, c3, c4, c5 = st.columns([1, 1, 1, 1])
    with c2: perf_pct_t3 = st.slider("🔥 퍼펙트 상위 %", 5, 50, 30, step=5)
    with c3: rank_p_s, rank_p_e = st.slider("🔥 퍼펙트 매수 순위", 1, 30, (1, 6))
    with c4: spec_12m_pct_t3 = st.slider("🐎 달리는말 상위 %", 5, 50, 30, step=5)
    with c5: rank_s_s, rank_s_e = st.slider("🐎 달리는말 매수 순위", 1, 30, (1, 2))

    # 🥇 금(KRX 환노출) 월별 수익률 로드 — 방어 구간(무조건 금 보유)용
    gold_returns_t3 = get_gold_returns() if use_gold_t3 else {}
    if use_gold_t3 and not gold_returns_t3:
        st.warning("⚠️ 금 데이터를 불러오지 못해 방어 구간이 현금(0%)으로 처리됩니다. `data/krx_gold_price.csv`(KRX 일별) 또는 FDR(GC=F·USD/KRW)를 확인하세요.")

    with st.spinner("엔진 구동 중..."):
        df_res, df_trades = cached_run_backtest_korea(df_master, start_year, end_year, ma_months_t3, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e), perf_pct_t3, spec_12m_pct_t3, trading_cost_pct=trading_cost_pct_t3, use_gold=use_gold_t3, _gold_returns=gold_returns_t3)
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested', '중지 사유']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            df_cum.loc[(pd.to_datetime(df_res['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
            df_cum = df_cum.sort_index()

            stats = []
            for col in s_cols:
                final_val = df_cum[col].iloc[-1]
                years = len(df_res)/12
                cagr = ((final_val/100)**(1/years)-1)*100 if final_val > 0 else -100
                mdd = ((df_cum[col]/df_cum[col].cummax())-1).min()*100
                
                # 💡 투자월 / 총개월 / 승월 카운트
                total_months = len(df_res)
                invested_months = int(df_res['invested'].sum())
                if invested_months > 0:
                    win_months = int((df_res.loc[df_res['invested'], col] > 0).sum())
                    win_rate = win_months / invested_months * 100
                    avg_ret_str = f"{df_res.loc[df_res['invested'], col].mean():.2f}%"
                else:
                    win_months, win_rate, avg_ret_str = 0, 0.0, "0.00%"
                inv_ratio = invested_months / total_months * 100 if total_months > 0 else 0
                # 💡 전체월 승률: 방어(금/현금) 달 포함, 모든 달 중 +수익 비율
                total_win_months = int((df_res[col] > 0).sum())
                total_win_rate = total_win_months / total_months * 100 if total_months > 0 else 0.0
                
                stats.append({
                    "전략명": col, 
                    "CAGR (연평균)": f"{cagr:.1f}%", 
                    "총 누적수익률": f"{final_val-100:,.1f}%", 
                    "MDD (최대낙폭)": f"{mdd:.1f}%", 
                    "투자월 비율": f"{inv_ratio:.1f}% ({invested_months}/{total_months})", 
                    "투자월 승률": f"{win_rate:.1f}% ({win_months}/{invested_months})", 
                    "전체월 승률": f"{total_win_rate:.1f}% ({total_win_months}/{total_months})", 
                    "평균 수익률": avg_ret_str
                })
            
            stats_df_t3 = pd.DataFrame(stats)
            
            # 💡 [업그레이드] 전략 조합 백테스트 종합 엑셀 리포트 데이터 생성
            settings_dict_t3 = {
                '테스트 시작 연도': f"{start_year}년",
                '테스트 종료 연도': f"{end_year}년",
                '마켓타이밍 (개월선)': f"{ma_months_t3}개월선",
                '마켓타이밍 적용': "적용(현금)" if apply_timing else "미적용",
                '방어 자산': ("금(KRX 환노출, 하락장 1개월 연장)" if use_gold_t3 else "현금"),
                '퍼펙트 상위 %': f"상위 {perf_pct_t3}% 이내",
                '퍼펙트 매수 순위': f"{rank_p_s}위 ~ {rank_p_e}위",
                '달리는말 상위 %': f"상위 {spec_12m_pct_t3}% 이내",
                '달리는말 매수 순위': f"{rank_s_s}위 ~ {rank_s_e}위"
            }
            
            excel_data_t3 = generate_excel_report_cached(tuple(settings_dict_t3.items()), stats_df_t3, df_res, df_cum, df_trades)

            col_t, col_b = st.columns([7.5, 2.5])
            with col_t: st.markdown("#### 📊 전략 핵심 통계 (초기 자본 100 기준)")
            with col_b: 
                st.download_button("📥 종합 엑셀 리포트 다운로드", data=excel_data_t3, file_name="KOSPI_조합_백테스트.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

            st.dataframe(get_styled_stats(stats_df_t3), use_container_width=True, hide_index=True)
            
            st.markdown("#### 🗓️ 상세 분석 (월별 수익률 히트맵 & MDD)")
            analysis_strat_t3 = st.radio("분석할 전략을 선택하세요", s_cols, horizontal=True, index=0, key="analysis_radio_t3")
            col_hm, col_mdd = st.columns([7.5, 2.5])
            with col_hm: st.dataframe(get_monthly_heatmap(df_res, analysis_strat_t3), use_container_width=True)
            with col_mdd: st.dataframe(get_mdd_history(df_cum[analysis_strat_t3]), use_container_width=True, hide_index=True)
            st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)"), use_container_width=True)
            with st.expander("📝 월별 전체 상세 기록 보기"): 
                df_show = df_res.drop(columns=['invested']).set_index('투자월')
                # 수익률 컬럼만 % 포맷 (중지 사유는 문자열이라 제외)
                fmt_cols = {c: "{:.2f}%" for c in df_show.columns if c != '중지 사유'}
                st.dataframe(df_show.style.format(fmt_cols), use_container_width=True)

# ==========================================
# 탭 4. 스코어 커스텀 백테스트
# ==========================================
with tab4:
    current_ma_c = st.session_state.get('t4_ma', 6)
    col_title_c, col_check_c = st.columns([1, 4])
    with col_title_c: st.markdown("<h4 style='margin:0;'>⚙️ 가중치 설정</h4>", unsafe_allow_html=True)
    with col_check_c:
        st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
        apply_timing_c = st.checkbox("🛑 마켓타이밍 적용 (MA 이탈 시 현금)", value=True, key='t4_chk_main')
    
    with st.form("custom_form", border=False):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])
        with c1: w1 = st.number_input("📉 1개월 가중치", value=0.2, step=0.1, format="%.1f")
        with c2: w3 = st.number_input("📈 3개월 가중치", value=0.8, step=0.1, format="%.1f")
        with c3: w6 = st.number_input("📈 6개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c4: w12 = st.number_input("📈 12개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            apply_weights = st.form_submit_button("✅ 실행", use_container_width=True)
            
    st.markdown("<hr style='margin: 15px 0px;'>", unsafe_allow_html=True)
    c6, c_ma_c, c7, c8 = st.columns([1, 0.8, 1, 1])
    with c6: start_year_c, end_year_c = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t4_yr')
    with c_ma_c: ma_months_t4 = st.slider("📉 마켓타이밍", 1, 12, 6, key='t4_ma')
    with c7: custom_pct = st.slider("🏅 상위 %", 5, 50, 30, step=5)
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위", 1, 30, (1, 10), key='t4_rnk')

    if apply_weights or 'custom_run' not in st.session_state: st.session_state['custom_run'] = True
    if st.session_state.get('custom_run', False):
        with st.spinner("커스텀 시뮬레이션 중..."):
            df_res_c, df_trades_c = cached_run_custom_backtest(df_master, start_year_c, end_year_c, ma_months_t4, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)
            if not df_res_c.empty:
                df_cum_c = (1 + df_res_c.set_index('투자월')[['커스텀 전략']] / 100).cumprod() * 100
                df_cum_c.loc[(pd.to_datetime(df_res_c['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
                df_cum_c = df_cum_c.sort_index()

                final_val_c = df_cum_c['커스텀 전략'].iloc[-1]
                years_c = len(df_res_c) / 12
                cagr_c = ((final_val_c/100)**(1/years_c)-1)*100 if final_val_c > 0 else -100
                mdd_c = ((df_cum_c['커스텀 전략']/df_cum_c['커스텀 전략'].cummax())-1).min()*100
                # 💡 투자월 / 총개월 / 승월 카운트
                total_months_c = len(df_res_c)
                invested_months_c = int(df_res_c['invested'].sum())
                if invested_months_c > 0:
                    win_months_c = int((df_res_c.loc[df_res_c['invested'], '커스텀 전략'] > 0).sum())
                    win_rate_c = win_months_c / invested_months_c * 100
                    avg_ret_c_str = f"{df_res_c.loc[df_res_c['invested'], '커스텀 전략'].mean():.2f}%"
                else:
                    win_months_c, win_rate_c, avg_ret_c_str = 0, 0.0, "0.00%"
                inv_ratio_c = invested_months_c / total_months_c * 100 if total_months_c > 0 else 0
                
                stats_c = [{
                    "전략명": "커스텀 스코어",
                    "CAGR (연평균)": f"{cagr_c:.1f}%",
                    "총 누적수익률": f"{final_val_c-100:,.1f}%",
                    "MDD (최대낙폭)": f"{mdd_c:.1f}%",
                    "투자월 비율": f"{inv_ratio_c:.1f}% ({invested_months_c}/{total_months_c})",
                    "월별 승률": f"{win_rate_c:.1f}% ({win_months_c}/{invested_months_c})",
                    "평균 수익률": avg_ret_c_str
                }]
                
                stats_df_t4 = pd.DataFrame(stats_c)
                
                # 💡 [업그레이드] 커스텀 백테스트 종합 엑셀 리포트 데이터 생성
                settings_dict_t4 = {
                    '테스트 시작 연도': f"{start_year_c}년",
                    '테스트 종료 연도': f"{end_year_c}년",
                    '마켓타이밍 (개월선)': f"{ma_months_t4}개월선",
                    '마켓타이밍 적용': "적용(현금)" if apply_timing_c else "미적용",
                    '가중치 설정 (1M, 3M, 6M, 12M)': f"{w1}, {w3}, {w6}, {w12}",
                    '교집합 추출 기준': f"상위 {custom_pct}% 이내",
                    '매수 순위': f"{rank_c_s}위 ~ {rank_c_e}위"
                }
                
                excel_data_t4 = generate_excel_report_cached(tuple(settings_dict_t4.items()), stats_df_t4, df_res_c, df_cum_c, df_trades_c)

                col_tc, col_bc = st.columns([7.5, 2.5])
                with col_tc: st.markdown("#### 📊 전략 핵심 통계")
                with col_bc: 
                    st.download_button("📥 종합 엑셀 리포트 다운로드", data=excel_data_t4, file_name="KOSPI_커스텀_백테스트.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

                st.dataframe(get_styled_stats(stats_df_t4), use_container_width=True, hide_index=True)
                
                col_hm_c, col_mdd_c = st.columns([6, 4])
                with col_hm_c: st.dataframe(get_monthly_heatmap(df_res_c, '커스텀 전략'), use_container_width=True)
                with col_mdd_c: st.dataframe(get_mdd_history(df_cum_c['커스텀 전략']), use_container_width=True, hide_index=True)
                st.plotly_chart(px.line(df_cum_c.reset_index(), x='투자월', y='커스텀 전략', log_y=True, title="커스텀 누적 성과"), use_container_width=True)
                with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res_c.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)
