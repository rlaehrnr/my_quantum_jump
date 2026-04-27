import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os

st.set_page_config(page_title="KOSPI 200 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS, get_kospi_ma_all, get_strategy_stocks_k200, run_backtest_k200, get_kospi_timing_for_backtest, get_idx_kr
from utils.ui_components import inject_custom_css, apply_k200_styling, style_kospi_ma

inject_custom_css()

# --- [상단 타이틀] ---
st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="https://m.stock.naver.com/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
                <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">🎯 KOSPI 200 모멘텀 터미널</h1>
                <span style="font-size: 0.95rem; color: #3b82f6; background-color: #eff6ff; padding: 4px 10px; border-radius: 6px; border: 1px solid #bfdbfe; white-space: nowrap;">🔗 네이버 증권 이동</span>
            </div>
        </a>
    </div>
''', unsafe_allow_html=True)

df_master = load_archive_data("archive_kospi")
f_daily = 'data/momentum_data_daily.csv'

if df_master.empty:
    st.error("🚨 archive_kospi 폴더에 데이터가 없습니다!")
    st.stop()

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

def style_stats(x):
    if isinstance(x, str) and '%' in x:
        if '-' in x: return 'color: #1976D2; font-weight:bold;'
        elif x != '0.0%': return 'color: #D32F2F; font-weight:bold;'
    return ''

# 💡 공통 MA 컬럼 설정 (탭1, 탭2 모두 사용)
ma_cfg = {
    "지수_L": st.column_config.LinkColumn("지수", display_text=r"#(.+)"),
    "현재가_L": st.column_config.LinkColumn("현재가", display_text=r"#(.+)"),
    "4개월선": st.column_config.NumberColumn("4개월선", format="%.2f"),
    "5개월선": st.column_config.NumberColumn("5개월선", format="%.2f"),
    "6개월선": st.column_config.NumberColumn("6개월선", format="%.2f"),
    "10개월선": st.column_config.NumberColumn("10개월선", format="%.2f"),
    "12개월선": st.column_config.NumberColumn("12개월선", format="%.2f"),
    "base_price": None 
}

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 조합 백테스트", "🏅 스코어 커스텀 백테스트"])

# ==========================================
# 탭 1: 월별 상세 분석
# ==========================================
with tab1:
    avail_years = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    c_y, c_m = st.columns([1.2, 8.8])
    
    with c_y: 
        selected_year = st.selectbox("📅 투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y")
    
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    default_m_index = len(m_list) - 1 

    with c_m:
        month_label = st.empty()
        selected_month = st.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m", label_visibility="collapsed", index=default_m_index)

    target_month_str = f"{selected_year}-{selected_month}"
    df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        
        month_label.markdown(f"<div style='margin-bottom: 5px;'><b>🌙 투자 월</b> <span style='font-size: 0.85rem; color: #9ca3af;'>&nbsp;&nbsp;💡 선정일: {base_date}</span></div>", unsafe_allow_html=True)

        kospi_curr, kospi_mas = get_kospi_ma_all(base_date)
        
        ma_df = pd.DataFrame([{
            '지수_L': "https://m.stock.naver.com/domestic/index/KOSPI/total#KOSPI",
            '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSPI#{kospi_curr:,.2f}",
            'base_price': round(kospi_curr, 2),
            '4개월선': kospi_mas.get(4, 0), '5개월선': kospi_mas.get(5, 0),
            '6개월선': kospi_mas.get(6, 0), '10개월선': kospi_mas.get(10, 0),
            '12개월선': kospi_mas.get(12, 0)
        }])
        
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_k200_t1, df_perf_t1, df_spec_t1 = get_strategy_stocks_k200(df_monthly)
        kospi_1m, kospi_3m = get_idx_kr(base_date)
        neg_1m_cnt = (df_k200_t1['1개월(%)'] < 0).sum()
        neg_3m_cnt = (df_k200_t1['3개월(%)'] < 0).sum()
        
        target_year_bt = int(selected_year)
        cycle_year = get_cycle_year(target_year_bt)
        bad_months_this_year = PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year, [])
        bad_m_str = ", ".join(f"{m}월" for m in bad_months_this_year) if bad_months_this_year else "없음"

        is_bad_market = (neg_1m_cnt >= 100) and (neg_3m_cnt >= 100)
        is_below_4m_ma = (kospi_curr > 0) and (kospi_curr < kospi_mas.get(4, 0))

        if is_bad_market or is_below_4m_ma:
            invest_status, box_color, text_color = "🛑 투자 중지", "#FFEBEE", "#C62828"
            status_desc = ("하락장" if is_bad_market else "") + (" + " if is_bad_market and is_below_4m_ma else "") + ("4개월선 이탈" if is_below_4m_ma else "")
        else:
            invest_status, box_color, text_color, status_desc = "✅ 투자 진행", "#E8F5E9", "#2E7D32", "상승장 & 4개월선 위"

        col1, col2, col3, col4, col5, col6 = st.columns([0.9, 0.9, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric(label="📈 KOSPI 1M", value=f"{kospi_1m}%")
        with col2: st.metric(label="📈 KOSPI 3M", value=f"{kospi_3m}%")
        with col3: st.metric(label="📉 1개월 하락", value=f"{neg_1m_cnt}개")
        with col4: st.metric(label="📉 3개월 하락", value=f"{neg_3m_cnt}개")
        with col5: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 100%; min-height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 13px; font-weight: bold; color: #333; margin-bottom: 4px;">🇺🇸대통령 <span style="color:#0047AB; font-size:14px;">{cycle_year}년차</span> ({target_year_bt}년)</div><div style="font-size: 13px; font-weight: bold; color: #D84315;">위험달: {bad_m_str}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_color}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_color}; display: flex; flex-direction: column; justify-content: center; height: 100%; min-height: 95px;"><p style="margin: 0; font-size: 12px; color: {text_color}; font-weight: bold;">최종 판단 ({status_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_color};">{invest_status}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_perf_t1, df_spec_t1, df_k200_t1]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#KOSPI:{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)

        main_cfg = {
            "통합티커_L": st.column_config.LinkColumn("티커", display_text=r"#(.+)"), 
            "종목명_L": st.column_config.LinkColumn("종목명", display_text=r"#(.+)"), 
            "1개월(%)": st.column_config.NumberColumn(format="%.1f"), 
            "3개월(%)": st.column_config.NumberColumn(format="%.1f"), 
            "6개월(%)": st.column_config.NumberColumn(format="%.1f"), 
            "12개월(%)": st.column_config.NumberColumn(format="%.1f"),
            "이번달수익률": st.column_config.NumberColumn(f"{selected_month}월 수익률(%)", format="%.2f") 
        }

        c_l, c_r = st.columns(2)
        count_p = len(df_perf_t1)
        count_s = len(df_spec_t1)
        
        with c_l:
            col_t1, col_i1, col_r1 = st.columns([4.0, 2.0, 4.0])
            with col_t1: st.markdown(f"<h4 style='margin-bottom:0; margin-top:2px;'>🔥 퍼펙트 상승 <span style='font-size:13px; color:gray; font-weight:normal;'>({count_p}개)</span></h4>", unsafe_allow_html=True)
            with col_i1: top_n_p = st.number_input("p_n", 1, max(1, count_p), min(5, count_p) if count_p > 0 else 1, key="calc_p", label_visibility="collapsed")
            with col_r1:
                avg_ret_p = df_perf_t1.head(top_n_p)['이번달수익률'].mean() if count_p > 0 else 0
                avg_color_p = "#D32F2F" if avg_ret_p > 0 else "#1976D2"
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:#475569;'>상위 {top_n_p}개 평균: <span style='color:{avg_color_p};'>{avg_ret_p:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">1,3,6,12M 수익률 모두 상위 30% 이내 & 0보다 큰 종목 (3M 순)</p>', unsafe_allow_html=True)
            
        with c_r:
            col_t2, col_i2, col_r2 = st.columns([4.0, 2.0, 4.0])
            with col_t2: st.markdown(f"<h4 style='margin-bottom:0; margin-top:2px;'>🐎 달리는 말 <span style='font-size:13px; color:gray; font-weight:normal;'>({count_s}개)</span></h4>", unsafe_allow_html=True)
            with col_i2: top_n_s = st.number_input("s_n", 1, max(1, count_s), min(5, count_s) if count_s > 0 else 1, key="calc_s", label_visibility="collapsed")
            with col_r2:
                avg_ret_s = df_spec_t1.head(top_n_s)['이번달수익률'].mean() if count_s > 0 else 0
                avg_color_s = "#D32F2F" if avg_ret_s > 0 else "#1976D2"
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:#475569;'>상위 {top_n_s}개 평균: <span style='color:{avg_color_s};'>{avg_ret_s:+.2f}%</span></div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12M 수익률 상위 30% 이내 & 1M 수익률 상위 10% 이내 (1M 순)</p>', unsafe_allow_html=True)

        top_list_p = df_perf_t1.head(top_n_p)['종목코드'].tolist() if count_p > 0 else []
        top_list_s = df_spec_t1.head(top_n_s)['종목코드'].tolist() if count_s > 0 else []
        overlap_codes = set(top_list_p).intersection(set(top_list_s))

        with c_l:
            st.dataframe(df_perf_t1.style.apply(apply_k200_styling, highlight_codes=top_list_p, overlap_codes=overlap_codes, axis=1), 
                         use_container_width=True, hide_index=True,
                         column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)
        with c_r:
            st.dataframe(df_spec_t1.style.apply(apply_k200_styling, highlight_codes=top_list_s, overlap_codes=overlap_codes, axis=1), 
                         use_container_width=True, hide_index=True,
                         column_order=['통합티커_L', '종목명_L', '1개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)

        st.markdown("---")
        st.subheader("🏆 KOSPI 200 전체 순위 (과거)")
        st.dataframe(df_k200_t1.style.apply(apply_k200_styling, axis=1), 
                     use_container_width=True, height=600, hide_index=True,
                     column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)

# ==========================================
# 탭 2: 데일리 실시간 순위
# ==========================================
with tab2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily, dtype={'종목코드': str})
        df_daily['종목코드'] = df_daily['종목코드'].astype(str).str.zfill(6)
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        
        st.markdown(f"<div style='margin-bottom: 5px;'><b>🕒 실시간 데일리 순위</b> <span style='font-size: 0.85rem; color: #9ca3af;'>&nbsp;&nbsp;💡 기준일: {b_date_d}</span></div>", unsafe_allow_html=True)
        
        kospi_curr_d, kospi_mas_d = get_kospi_ma_all(b_date_d)
        
        ma_df_d = pd.DataFrame([{
            '지수_L': "https://m.stock.naver.com/domestic/index/KOSPI/total#KOSPI",
            '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSPI#{kospi_curr_d:,.2f}",
            'base_price': round(kospi_curr_d, 2),
            '4개월선': kospi_mas_d.get(4, 0), '5개월선': kospi_mas_d.get(5, 0),
            '6개월선': kospi_mas_d.get(6, 0), '10개월선': kospi_mas_d.get(10, 0),
            '12개월선': kospi_mas_d.get(12, 0)
        }])
        st.dataframe(style_kospi_ma(ma_df_d), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_k200_d, df_perf_d, df_spec_d = get_strategy_stocks_k200(df_daily)
        kospi_1m_d, kospi_3m_d = get_idx_kr(b_date_d)
        neg_1m_cnt_d = (df_k200_d['1개월(%)'] < 0).sum()
        neg_3m_cnt_d = (df_k200_d['3개월(%)'] < 0).sum()
        
        target_year_d = int(b_date_d.split('-')[0])
        cycle_year_d = get_cycle_year(target_year_d)
        bad_months_d = PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year_d, [])
        bad_m_str_d = ", ".join(f"{m}월" for m in bad_months_d) if bad_months_d else "없음"

        is_bad_market_d = (neg_1m_cnt_d >= 100) and (neg_3m_cnt_d >= 100)
        is_below_4m_ma_d = (kospi_curr_d > 0) and (kospi_curr_d < kospi_mas_d.get(4, 0))

        if is_bad_market_d or is_below_4m_ma_d:
            invest_status_d, box_color_d, text_color_d = "🛑 투자 중지", "#FFEBEE", "#C62828"
            status_desc_d = ("하락장" if is_bad_market_d else "") + (" + " if is_bad_market_d and is_below_4m_ma_d else "") + ("4개월선 이탈" if is_below_4m_ma_d else "")
        else:
            invest_status_d, box_color_d, text_color_d, status_desc_d = "✅ 투자 진행", "#E8F5E9", "#2E7D32", "상승장 & 4개월선 위"

        col1_d, col2_d, col3_d, col4_d, col5_d, col6_d = st.columns([0.9, 0.9, 1.0, 1.0, 1.4, 1.6])
        with col1_d: st.metric(label="📈 KOSPI 1M", value=f"{kospi_1m_d}%")
        with col2_d: st.metric(label="📈 KOSPI 3M", value=f"{kospi_3m_d}%")
        with col3_d: st.metric(label="📉 1개월 하락", value=f"{neg_1m_cnt_d}개")
        with col4_d: st.metric(label="📉 3개월 하락", value=f"{neg_3m_cnt_d}개")
        with col5_d: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 100%; min-height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 13px; font-weight: bold; color: #333; margin-bottom: 4px;">🇺🇸대통령 <span style="color:#0047AB; font-size:14px;">{cycle_year_d}년차</span> ({target_year_d}년)</div><div style="font-size: 13px; font-weight: bold; color: #D84315;">위험달: {bad_m_str_d}</div></div>', unsafe_allow_html=True)
        with col6_d: st.markdown(f'<div style="background-color: {box_color_d}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_color_d}; display: flex; flex-direction: column; justify-content: center; height: 100%; min-height: 95px;"><p style="margin: 0; font-size: 12px; color: {text_color_d}; font-weight: bold;">최종 판단 ({status_desc_d})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_color_d};">{invest_status_d}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_perf_d, df_spec_d, df_k200_d]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#KOSPI:{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)

        daily_cfg = {
            "통합티커_L": st.column_config.LinkColumn("티커", display_text=r"#(.+)"), 
            "종목명_L": st.column_config.LinkColumn("종목명", display_text=r"#(.+)"), 
            "1개월(%)": st.column_config.NumberColumn(format="%.1f"), 
            "3개월(%)": st.column_config.NumberColumn(format="%.1f"), 
            "6개월(%)": st.column_config.NumberColumn(format="%.1f"), 
            "12개월(%)": st.column_config.NumberColumn(format="%.1f")
        }

        c_d1, c_d2 = st.columns(2)
        count_p_d = len(df_perf_d)
        count_s_d = len(df_spec_d)

        with c_d1:
            col_t1_d, col_i1_d, col_r1_d = st.columns([4.0, 2.0, 4.0])
            with col_t1_d: st.markdown(f"<h4 style='margin-bottom:0; margin-top:2px;'>🔥 퍼펙트 상승 <span style='font-size:13px; color:gray; font-weight:normal;'>({count_p_d}개)</span></h4>", unsafe_allow_html=True)
            with col_i1_d: top_n_p_d = st.number_input("p_n_d", 1, max(1, count_p_d), min(5, count_p_d) if count_p_d > 0 else 1, key="calc_p_d", label_visibility="collapsed")
            with col_r1_d:
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:#475569;'>상위 {top_n_p_d}개 선택됨</div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">1,3,6,12M 수익률 모두 상위 30% 이내 & 0보다 큰 종목 (3M 순)</p>', unsafe_allow_html=True)
            
        with c_d2:
            col_t2_d, col_i2_d, col_r2_d = st.columns([4.0, 2.0, 4.0])
            with col_t2_d: st.markdown(f"<h4 style='margin-bottom:0; margin-top:2px;'>🐎 달리는 말 <span style='font-size:13px; color:gray; font-weight:normal;'>({count_s_d}개)</span></h4>", unsafe_allow_html=True)
            with col_i2_d: top_n_s_d = st.number_input("s_n_d", 1, max(1, count_s_d), min(5, count_s_d) if count_s_d > 0 else 1, key="calc_s_d", label_visibility="collapsed")
            with col_r2_d:
                st.markdown(f"<div style='margin-top:8px; font-size:0.85rem; font-weight:bold; color:#475569;'>상위 {top_n_s_d}개 선택됨</div>", unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">12M 수익률 상위 30% 이내 & 1M 수익률 상위 10% 이내 (1M 순)</p>', unsafe_allow_html=True)

        top_list_p_d = df_perf_d.head(top_n_p_d)['종목코드'].tolist() if count_p_d > 0 else []
        top_list_s_d = df_spec_d.head(top_n_s_d)['종목코드'].tolist() if count_s_d > 0 else []
        overlap_codes_d = set(top_list_p_d).intersection(set(top_list_s_d))

        with c_d1:
            st.dataframe(df_perf_d.style.apply(apply_k200_styling, highlight_codes=top_list_p_d, overlap_codes=overlap_codes_d, axis=1), 
                         use_container_width=True, hide_index=True,
                         column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)'], column_config=daily_cfg)
        with c_d2:
            st.dataframe(df_spec_d.style.apply(apply_k200_styling, highlight_codes=top_list_s_d, overlap_codes=overlap_codes_d, axis=1), 
                         use_container_width=True, hide_index=True,
                         column_order=['통합티커_L', '종목명_L', '1개월(%)', '12개월(%)'], column_config=daily_cfg)

        st.markdown("---")
        st.subheader("🏆 KOSPI 200 전체 순위 (오늘)")
        st.dataframe(df_k200_d.style.apply(apply_k200_styling, axis=1), 
                     use_container_width=True, height=600, hide_index=True,
                     column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)'], column_config=daily_cfg)
    else:
        st.info("데일리 수집봇(update_daily.py)이 아직 세팅되지 않았습니다. 파일(`data/momentum_data_daily.csv`)이 생성되면 여기에 실시간 순위가 나타납니다.")

# ==========================================
# 탭 3: 전략 조합 백테스트
# ==========================================
with tab3:
    st.markdown("<h4 style='margin-top: 5px; margin-bottom: 0px;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
    c1, c_ma, c_chk = st.columns([1, 1, 1.5])
    with c1: start_year, end_year = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr')
    with c_ma: ma_months_t3 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 4, key='t3_ma')
    with c_chk:
        st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
        apply_timing = st.checkbox("🛑 마켓타이밍 적용 (선택 이평선 이탈 OR 1·3M 하락종목 100개↑ 시 현금)", value=True, key='t3_chk')
        
    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
    c2, c3, c4, c5 = st.columns([1, 1, 1, 1])
    with c2: perf_pct_t3 = st.slider("🔥 퍼펙트 상승 상위 %", 5, 50, 30, step=5, key="p3_p")
    with c3: rank_p_s, rank_p_e = st.slider("🔥 퍼펙트 상승 매수 순위", 1, 30, (1, 6), key="t3_rp")
    with c4: spec_12m_pct_t3 = st.slider("🐎 달리는 말 상위 %", 5, 50, 30, step=5, key="p3_s")
    with c5: rank_s_s, rank_s_e = st.slider("🐎 달리는 말 매수 순위", 1, 30, (1, 2), key="t3_rs")

    with st.spinner("엔진 구동 중..."):
        df_res, df_trades = run_backtest_k200(df_master, start_year, end_year, ma_months_t3, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e), perf_pct=perf_pct_t3, spec_12m=spec_12m_pct_t3)
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            df_cum.loc[(pd.to_datetime(df_res['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
            df_cum = df_cum.sort_index()

            col_stat_title, col_stat_btn = st.columns([8.5, 1.5])
            with col_stat_title:
                st.markdown("#### 📊 전략 핵심 통계 (초기 자본 100 기준)")
            with col_stat_btn:
                st.download_button(
                    label="📥 상세내역 다운로드",
                    data=df_trades.to_csv(index=False).encode('utf-8-sig'),
                    file_name=f"KOSPI200_백테스트_{datetime.today().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

            stats = []
            for col in s_cols:
                final_val = df_cum[col].iloc[-1]
                total_ret = final_val - 100
                years = len(df_res) / 12
                cagr = ((final_val / 100) ** (1 / years) - 1) * 100 if final_val > 0 else -100.0
                win_rate = (df_res.loc[df_res['invested'], col] > 0).mean() * 100 if df_res['invested'].any() else 0
                avg_ret = df_res.loc[df_res['invested'], col].mean() if df_res['invested'].any() else 0
                mdd = ((df_cum[col] / df_cum[col].cummax()) - 1.0).min() * 100
                invest_ratio = (df_res['invested'].sum() / len(df_res)) * 100 if len(df_res) > 0 else 0
                
                stats.append({"전략명": col, "CAGR (연평균)": f"{cagr:.1f}%", "총 누적수익률": f"{total_ret:,.1f}%", "MDD (최대낙폭)": f"{mdd:.1f}%", "투자월 비율": f"{invest_ratio:.1f}%", "월별 승률": f"{win_rate:.1f}%", "평균 수익률": f"{avg_ret:.2f}%"})
            
            df_stats = pd.DataFrame(stats)
            try: styled_stats = df_stats.style.map(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
            except AttributeError: styled_stats = df_stats.style.applymap(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
            st.dataframe(styled_stats, use_container_width=True, hide_index=True)

            fig = px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)")
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander(f"📝 {start_year}~{end_year}년 ({len(df_res)}개월) 월별 수익률 상세 기록 보기"):
                st.dataframe(df_res.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)

# ==========================================
# 탭 4: 스코어 커스텀 백테스트
# ==========================================
with tab4:
    col_title, col_check = st.columns([1, 4])
    with col_title: st.markdown("<h4 style='margin-top: 5px; margin-bottom: 0px;'>⚙️ 스코어 가중치 설정</h4>", unsafe_allow_html=True)
    with col_check:
        st.markdown("<div style='margin-top: 8px;'>", unsafe_allow_html=True)
        apply_timing_c = st.checkbox("🛑 마켓타이밍 적용", value=True, key='t4_chk')
        st.markdown("</div>", unsafe_allow_html=True)
        
    with st.form("custom_form", border=False):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])
        with c1: w1 = st.number_input("📉 1개월 가중치", value=0.2, step=0.1, format="%.1f")
        with c2: w3 = st.number_input("📈 3개월 가중치", value=0.8, step=0.1, format="%.1f")
        with c3: w6 = st.number_input("📈 6개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c4: w12 = st.number_input("📈 12개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            apply_weights = st.form_submit_button("✅ 실행", use_container_width=True)
            
    st.markdown("<hr style='margin: 0px 0px 15px 0px;'>", unsafe_allow_html=True)
    c6, c_ma_c, c7, c8 = st.columns([1, 0.8, 1, 1])
    with c6: start_year_c, end_year_c = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t4_yr')
    with c_ma_c: ma_months_t4 = st.slider("📉 마켓타이밍", 1, 12, 4, key='t4_ma')
    with c7: custom_pct = st.slider("🏅 상위 %", 5, 50, 30, step=5)
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위", 1, 30, (1, 10), key='t4_rnk')

    if apply_weights or 'custom_run' not in st.session_state:
        st.session_state['custom_run'] = True
        
    if st.session_state.get('custom_run', False):
        with st.spinner("커스텀 시뮬레이션 중..."):
            timing_df_t4 = get_kospi_timing_for_backtest(ma_months_t4)
            records_c, trade_logs_c = [], []
            for m_str in sorted(df_master['투자월'].dropna().unique()):
                m_yr = int(m_str.split('-')[0])
                if not (start_year_c <= m_yr <= end_year_c): continue
                df_calc = df_master[df_master['투자월'] == m_str].copy()
                if df_calc.empty: continue
                base_date_c = df_calc['종목선정일'].iloc[0]
                base_ym_c = pd.to_datetime(base_date_c).strftime('%Y-%m')
                is_below_ma = timing_df_t4.loc[base_ym_c, 'is_below_ma'] if base_ym_c in timing_df_t4.index else False
                
                mult_c = 0.0 if (apply_timing_c and ((df_calc['1개월(%)'] < 0).sum() >= 100 or is_below_ma)) else 1.0
                
                df_calc['스코어'] = (df_calc['1개월(%)']*w1) + (df_calc['3개월(%)']*w3) + (df_calc['6개월(%)']*w6) + (df_calc['12개월(%)']*w12)
                target = df_calc[df_calc['스코어']>=df_calc['스코어'].quantile(1-(custom_pct/100))].sort_values('스코어', ascending=False).iloc[rank_c_s-1:rank_c_e]
                ret = (target['이번달수익률'].mean() * mult_c) if not target.empty else 0.0
                records_c.append({'투자월': m_str, 'invested': mult_c > 0, '커스텀 전략': ret})
                
                if mult_c == 0: trade_logs_c.append({'투자월': m_str, '전략': '마켓타이밍 작동', '매수순위': '-', '종목명': '현금 (투자중지)', '종목코드': '-', '수익률(%)': 0.0})
                else: 
                    for i, (_, r) in enumerate(target.iterrows()): trade_logs_c.append({'투자월': m_str, '전략': '커스텀 스코어', '매수순위': f"{i + rank_c_s}위", '종목명': r['종목명'], '종목코드': r['종목코드'], '수익률(%)': r['이번달수익률']})

            df_res_c = pd.DataFrame(records_c)
            if not df_res_c.empty:
                df_cum_c = (1 + df_res_c.set_index('투자월')[['커스텀 전략']] / 100).cumprod() * 100
                df_cum_c.loc[(pd.to_datetime(df_res_c['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')] = 100
                df_cum_c = df_cum_c.sort_index()

                col_stat_title_c, col_stat_btn_c = st.columns([8.5, 1.5])
                with col_stat_title_c:
                    st.markdown("#### 📊 전략 핵심 통계")
                with col_stat_btn_c:
                    st.download_button(
                        label="📥 상세내역 다운로드",
                        data=pd.DataFrame(trade_logs_c).to_csv(index=False).encode('utf-8-sig'),
                        file_name=f"K200_커스텀_{datetime.today().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

                final_val_c = df_cum_c['커스텀 전략'].iloc[-1]
                years_c = len(df_res_c) / 12
                cagr_c = ((final_val_c / 100) ** (1 / years_c) - 1) * 100
                mdd_c = ((df_cum_c['커스텀 전략'] / df_cum_c['커스텀 전략'].cummax()) - 1.0).min() * 100
                invest_ratio_c = (df_res_c['invested'].sum() / len(df_res_c)) * 100 if len(df_res_c) > 0 else 0
                
                stats_c = [{"전략명": "커스텀 스코어", "CAGR (연평균)": f"{cagr_c:.1f}%", "총 누적수익률": f"{final_val_c-100:,.1f}%", "MDD (최대낙폭)": f"{mdd_c:.1f}%", "투자월 비율": f"{invest_ratio_c:.1f}%", "월별 승률": f"{(df_res_c.loc[df_res_c['invested'], '커스텀 전략'] > 0).mean()*100:.1f}%", "평균 수익률": f"{df_res_c.loc[df_res_c['invested'], '커스텀 전략'].mean():.2f}%"}]
                
                df_stats_c = pd.DataFrame(stats_c)
                try: styled_stats_c = df_stats_c.style.map(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
                except AttributeError: styled_stats_c = df_stats_c.style.applymap(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
                st.dataframe(styled_stats_c, use_container_width=True, hide_index=True)

                st.plotly_chart(px.line(df_cum_c.reset_index(), x='투자월', y='커스텀 전략', log_y=True, title="커스텀 누적 성과"), use_container_width=True)
                
                with st.expander("📝 월별 상세 기록"):
                    st.dataframe(df_res_c.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)
