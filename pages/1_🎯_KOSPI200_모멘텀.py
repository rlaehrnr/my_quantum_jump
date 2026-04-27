import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

st.set_page_config(page_title="KOSPI 200 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS, get_kospi_ma_all, get_strategy_stocks_k200, run_backtest_k200
from utils.ui_components import inject_custom_css, render_kospi_ma_widget

# 1. UI 디자인 일괄 적용 (utils에서 불러옴)
inject_custom_css()

st.markdown('''
<div class="main-title-container">
    <a href="https://stock.naver.com/" target="_blank" style="text-decoration: none; color: inherit;">
        <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 15px;">
            <h1 style="margin: 0; font-size: 2.2rem; font-weight: 900;">🎯 KOSPI 200 모멘텀 터미널</h1>
            <span style="font-size: 0.9rem; color: #3b82f6; background-color: #eff6ff; padding: 5px 12px; border-radius: 8px; border: 1px solid #bfdbfe; font-weight: bold;">LIVE</span>
        </div>
    </a>
</div>
''', unsafe_allow_html=True)

df_master = load_archive_data("archive_kospi")
f_daily = 'data/momentum_data_daily.csv'

if df_master.empty:
    st.warning("⚠️ `archive_kospi` 폴더에 데이터가 없습니다.")
    st.stop()

# 탭 구성 (오타 수정 완)
tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 기록 & 운용현황", "🕒 실시간 데일리 순위", "📈 전략 조합 백테스트", "🏅 스코어 커스텀 백테스트"])

# ==========================================
# 탭 1: 월별 기록 & 운용현황
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
        df_k200_t1, df_perf_t1, df_spec_t1 = get_strategy_stocks_k200(df_monthly)
        
        curr_now = datetime.now()
        is_current_month = (int(selected_year) == curr_now.year and int(selected_month) == curr_now.month)
        label_ret = "실시간 수익률(%)" if is_current_month else "이번달 수익률(%)"
        
        neg_1m_cnt = (df_k200_t1['1개월(%)'] < 0).sum()
        neg_3m_cnt = (df_k200_t1['3개월(%)'] < 0).sum()
        is_bad_market = (neg_1m_cnt >= 100) and (neg_3m_cnt >= 100)
        is_below_4m = (kospi_curr < kospi_mas.get(4, 0)) if kospi_curr > 0 else False

        reasons = []
        if is_bad_market: reasons.append("하락장(1,3M 100개↑)")
        if is_below_4m: reasons.append("4개월선 이탈")

        status, box_c, text_c = ("🛑 투자 중지", "#FFEBEE", "#C62828") if reasons else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        desc = " + ".join(reasons) if reasons else "상승장 & 4개월선 위"
        cycle_y = get_cycle_year(int(selected_year))

        # 이평선 시각화 위젯 호출!
        render_kospi_ma_widget(kospi_curr, kospi_mas, target_ma=4)
        st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        col_m1, col_m2, col_m3, col_m4 = st.columns([1, 1, 1.4, 1.6])
        with col_m1: st.metric("📉 1M 하락종목", f"{neg_1m_cnt}개")
        with col_m2: st.metric("📉 3M 하락종목", f"{neg_3m_cnt}개")
        with col_m3: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 100%; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 13px; font-weight: bold; color: #333;">🇺🇸대통령 <span style="color:#0047AB; font-size:14px;">{cycle_y}년차</span></div></div>', unsafe_allow_html=True)
        with col_m4: st.markdown(f'<div style="background-color: {box_c}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_c}; display: flex; flex-direction: column; justify-content: center; height: 100%;"><p style="margin: 0; font-size: 12px; color: {text_c}; font-weight: bold;">최종 판단 ({desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_c};">{status}</div></div>', unsafe_allow_html=True)

        st.markdown("---")
        
        cfg_t1 = {"종목명": st.column_config.TextColumn("종목명"), "이번달수익률": st.column_config.NumberColumn(label_ret, format="%.2f %%")}

        c_l, c_r = st.columns(2)
        with c_l:
            st.subheader("🔥 퍼펙트 상승")
            st.dataframe(df_perf_t1[['종목명', '1개월(%)', '3개월(%)', '12개월(%)', '이번달수익률']].head(10), use_container_width=True, hide_index=True, column_config=cfg_t1)
        with c_r:
            st.subheader("🐎 달리는 말")
            st.dataframe(df_spec_t1[['종목명', '1개월(%)', '12개월(%)', '이번달수익률']].head(10), use_container_width=True, hide_index=True, column_config=cfg_t1)

# ==========================================
# 탭 2: 실시간 데일리 순위
# ==========================================
with tab2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily, dtype={'종목코드': str})
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        st.subheader(f"🕒 실시간 순위 (기준: {b_date_d})")
        df_k200_d, df_perf_d, df_spec_d = get_strategy_stocks_k200(df_daily)
        
        c1, c2 = st.columns(2)
        with c1: st.dataframe(df_perf_d[['종목명', '1개월(%)', '3개월(%)', '12개월(%)']].head(20), use_container_width=True, hide_index=True)
        with c2: st.dataframe(df_spec_d[['종목명', '1개월(%)', '12개월(%)']].head(20), use_container_width=True, hide_index=True)
    else:
        st.info("데일리 데이터 파일(`data/momentum_data_daily.csv`)이 없습니다.")

# ==========================================
# 탭 3: 전략 조합 백테스트
# ==========================================
with tab3:
    st.subheader("📈 전략 누적 성과 시뮬레이션")
    col_s1, col_s2 = st.columns([1, 2])
    with col_s1: s_yr, e_yr = st.slider("테스트 기간", 2014, 2026, (2014, 2026), key="t3_slider")
    with col_s2: apply_t = st.checkbox("마켓타이밍 적용", value=True, key="t3_chk")
    
    r_p = st.slider("🔥 퍼펙트 상승 매수 순위", 1, 30, (1, 5), key="t3_rp")
    r_s = st.slider("🐎 달리는 말 매수 순위", 1, 30, (1, 5), key="t3_rs")

    with st.spinner("백테스트 계산 중..."):
        df_res, df_logs = run_backtest_k200(df_master, s_yr, e_yr, 4, apply_t, r_p, r_s)
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            
            fig = px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True)
            st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 탭 4: 스코어 커스텀 백테스트
# ==========================================
with tab4:
    st.subheader("🏅 스코어 커스텀 백테스트")
    st.info("이 탭의 세부 로직은 다음 단계에서 고도화할 수 있습니다.")
