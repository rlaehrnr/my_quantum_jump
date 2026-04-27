import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

st.set_page_config(page_title="KOSPI 200 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS, get_kospi_ma_all, get_strategy_stocks_k200, run_backtest_k200, get_kospi_timing_for_backtest
from utils.ui_components import inject_custom_css, apply_k200_styling, style_kospi_ma, get_perf_html

inject_custom_css()

# --- [상단 타이틀 (네이버 증권 이동 버튼 복원)] ---
st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="https://stock.naver.com/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;">
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
    st.error("🚨 `archive_kospi` 폴더에 데이터가 없습니다!")
    st.stop()

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 조합 백테스트", "🏅 스코어 커스텀 백테스트"])

# ==========================================
# 탭 1: 월별 상세 분석
# ==========================================
with tab1:
    avail_years = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    c_y, c_m, c_info = st.columns([1.2, 7.3, 1.5])
    with c_y: selected_year = st.selectbox("📅 투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y")
    
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    with c_m: selected_month = st.radio("🌙 투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m")

    target_month_str = f"{selected_year}-{selected_month}"
    df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        with c_info: st.markdown(f"<div style='margin-top: 32px; text-align: right; color: #9ca3af;'>💡 <b>종목선정일:</b><br>{base_date}</div>", unsafe_allow_html=True)

        kospi_curr, kospi_mas = get_kospi_ma_all(base_date)
        
        # --- [지수 MA 표 UI 복원] ---
        ma_df = pd.DataFrame([{
            '지수_L': "https://m.stock.naver.com/domestic/index/KOSPI/total#KOSPI",
            '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSPI#{kospi_curr:,.2f}",
            'base_price': round(kospi_curr, 2),
            '4개월선': round(kospi_mas.get(4, 0), 2), '5개월선': round(kospi_mas.get(5, 0), 2),
            '6개월선': round(kospi_mas.get(6, 0), 2), '10개월선': round(kospi_mas.get(10, 0), 2),
            '12개월선': round(kospi_mas.get(12, 0), 2)
        }])
        
        ma_cfg = {
            "지수_L": st.column_config.LinkColumn("지수", display_text=r"#(.+)"),
            "현재가_L": st.column_config.LinkColumn("현재가", display_text=r"#(.+)"),
            "base_price": None 
        }
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        st.markdown("<br>", unsafe_allow_html=True)

        # 전략 데이터 추출
        df_k200_t1, df_perf_t1, df_spec_t1 = get_strategy_stocks_k200(df_monthly)
        
        top5_p = df_perf_t1.head(5)['종목코드'].tolist()
        top5_s = df_spec_t1.head(5)['종목코드'].tolist()
        overlap_codes = set(top5_p).intersection(set(top5_s))
        
        # 링크 컬럼 추가
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

        # --- [전략별 성적 요약 HTML 복원] ---
        c_l, c_r = st.columns(2)
        with c_l:
            st.markdown(get_perf_html("🔥 퍼펙트 상승", df_perf_t1, selected_month), unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">KOSPI 200 중 1, 3, 6, 12개월 수익률이 모두 상위 30% 이내이며 0보다 큰 종목 (3개월 수익률 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_perf_t1.style.apply(apply_k200_styling, highlight_codes=top5_p, overlap_codes=overlap_codes, axis=1), 
                         use_container_width=True, hide_index=True,
                         column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)
        with c_r:
            st.markdown(get_perf_html("🐎 달리는 말", df_spec_t1, selected_month), unsafe_allow_html=True)
            st.markdown('<p class="strategy-desc">KOSPI 200 중 12개월 수익률 상위 30% 이내, 1개월 수익률 상위 10% 이내인 종목 (1개월 수익률 순)</p>', unsafe_allow_html=True)
            st.dataframe(df_spec_t1.style.apply(apply_k200_styling, highlight_codes=top5_s, overlap_codes=overlap_codes, axis=1), 
                         use_container_width=True, hide_index=True,
                         column_order=['통합티커_L', '종목명_L', '1개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)

        st.markdown("---")
        # --- [KOSPI 200 전체 순위 복원] ---
        st.subheader("🏆 KOSPI 200 전체 순위 (과거)")
        st.dataframe(df_k200_t1.style.apply(apply_k200_styling, axis=1), 
                     use_container_width=True, height=600, hide_index=True,
                     column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)

# ==========================================
# 탭 2: 데일리 실시간 순위
# ==========================================
with tab2:
    if os.path.exists(f_daily):
        pass # 데일리 파일 로직 (기존과 동일)
    else:
        st.info("데일리 수집봇(update_daily.py)이 아직 세팅되지 않았습니다. 파일(`data/momentum_data_daily.csv`)이 생성되면 여기에 실시간 순위가 나타납니다.")

# ==========================================
# 탭 3: 전략 조합 백테스트 (기본값 복원)
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
    
    # 기본값 1~6위, 1~2위 복원
    c3, c4 = st.columns(2)
    with c3: rank_p_s, rank_p_e = st.slider("🔥 퍼펙트 상승 매수 순위", 1, 30, (1, 6), key="t3_rp")
    with c4: rank_s_s, rank_s_e = st.slider("🐎 달리는 말 매수 순위", 1, 30, (1, 2), key="t3_rs")

    with st.spinner("엔진 구동 중..."):
        df_res, df_trades = run_backtest_k200(df_master, start_year, end_year, ma_months_t3, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e))
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            fig = px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)")
            st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 탭 4: 스코어 커스텀 백테스트 (풀 로직 복원)
# ==========================================
with tab4:
    st.markdown("<h4 style='margin-top: 5px; margin-bottom: 0px;'>⚙️ 스코어 가중치 설정</h4>", unsafe_allow_html=True)
    with st.form("custom_weight_form_k200", border=False):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])
        with c1: w1 = st.number_input("📉 1개월 가중치", value=0.2, step=0.1, format="%.1f")
        with c2: w3 = st.number_input("📈 3개월 가중치", value=0.8, step=0.1, format="%.1f")
        with c3: w6 = st.number_input("📈 6개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c4: w12 = st.number_input("📈 12개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            apply_weights = st.form_submit_button("✅ 스코어 적용 및 실행", use_container_width=True)
            
    st.markdown("<hr style='margin: 0px 0px 15px 0px;'>", unsafe_allow_html=True)
    
    c6, c7, c8 = st.columns([1.5, 1, 1])
    with c6: start_year_c, end_year_c = st.slider("📅 커스텀 테스트 기간", min_y, max_y, (min_y, max_y), key='t4_yr')
    with c7: custom_pct = st.slider("🏅 커스텀 스코어 상위 %", 5, 50, 30, step=5)
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위 범위", 1, 30, (1, 10), key='t4_rnk')

    if apply_weights or 'custom_run' not in st.session_state:
        st.session_state['custom_run'] = True
        
    if st.session_state.get('custom_run', False):
        with st.spinner("커스텀 가중치 시뮬레이션 연산 중..."):
            records_c = []
            for m_str in df_master['투자월'].dropna().unique():
                m_year = int(m_str.split('-')[0])
                if not (start_year_c <= m_year <= end_year_c): continue
                
                df_calc = df_master[df_master['투자월'] == m_str].copy()
                if df_calc.empty: continue
                
                # 가중치 연산 적용
                df_calc['커스텀스코어'] = (df_calc['1개월(%)']*w1) + (df_calc['3개월(%)']*w3) + (df_calc['6개월(%)']*w6) + (df_calc['12개월(%)']*w12)
                q_val_c = df_calc['커스텀스코어'].quantile(1.0 - (custom_pct / 100.0))
                
                target_group = df_calc[(df_calc['커스텀스코어']>=q_val_c) & (df_calc['1개월(%)']>0)].sort_values('커스텀스코어', ascending=False).iloc[rank_c_s-1 : rank_c_e]
                ret_target = target_group['이번달수익률'].mean() if not target_group.empty else 0.0
                
                records_c.append({'투자월': m_str, f'🏅 커스텀 스코어 ({rank_c_s}~{rank_c_e}위)': ret_target})
                
            df_res_c = pd.DataFrame(records_c).fillna(0.0)
            if not df_res_c.empty:
                col_name = f'🏅 커스텀 스코어 ({rank_c_s}~{rank_c_e}위)'
                df_cum_c = (1 + df_res_c.set_index('투자월')[col_name] / 100).cumprod() * 100
                fig_c = px.line(df_cum_c.reset_index(), x='투자월', y=col_name, log_y=True, title="커스텀 가중치 누적 성과")
                st.plotly_chart(fig_c, use_container_width=True)
