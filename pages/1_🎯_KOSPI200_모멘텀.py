import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

# 우리가 만든 utils 폴더에서 핵심 기능 불러오기
from utils.data_loader import load_archive_data
from utils.calculator import (
    get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS, 
    get_kospi_ma_status, get_strategy_stocks_k200, run_backtest_k200
)
# 라이브 주가 확인용 (Tab 1에서 이번 달 수익률 실시간 계산용)
from utils.calculator import fdr 
st.set_page_config(page_title="KOSPI 200 모멘텀 터미널", layout="wide")
# --- [1. 스타일 및 디자인 설정] ---
st.markdown('''
<style>
    /* 상단 여백을 충분히 주어 제목이 잘리지 않게 함 */
    .block-container { padding-top: 3.5rem !important; }
    .main-title-container { margin-bottom: 30px; padding-top: 10px; }
    .strategy-desc { font-size: 0.85rem; color: #9ca3af; margin-bottom: 10px; line-height: 1.2; }
    div[role="radiogroup"] { gap: 15px !important; flex-wrap: wrap; padding-top: 5px; }
    th[data-testid="stTableColumnHeader"] div { white-space: pre-wrap !important; text-align: center !important; }
</style>
''', unsafe_allow_html=True)

# 제목부
st.markdown('''
<div class="main-title-container">
    <a href="https://stock.naver.com/" target="_blank" style="text-decoration: none; color: inherit;">
        <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 15px;">
            <h1 style="margin: 0; font-size: 2.5rem; font-weight: 900;">🎯 KOSPI 200 모멘텀 터미널</h1>
            <span style="font-size: 1rem; color: #3b82f6; background-color: #eff6ff; padding: 5px 12px; border-radius: 8px; border: 1px solid #bfdbfe; font-weight: bold;">LIVE</span>
        </div>
    </a>
</div>
''', unsafe_allow_html=True)

# --- [2. 데이터 로드] ---
df_master = load_archive_data("archive_kospi")
f_daily = 'data/momentum_data_daily.csv' # 데일리 파일 경로

if df_master.empty:
    st.warning("⚠️ `archive_kospi` 폴더에 과거 데이터(CSV)가 없습니다. 데이터를 먼저 업로드해 주세요.")
    st.stop()

# 탭 구성 (선생님 기획 4단 구성)
tab1, tab2, tab3, tab4 = st.tabs([
    "📅 월별 기록 & 운용현황", 
    "🕒 실시간 데일리 순위", 
    "📈 전략 조합 백테스트", 
    "🏅 스코어 커스텀 백테스트"
])

# ==========================================
# 탭 1: 월별 기록 & 운용현황 (진행중인 달 포함)
# ==========================================
with tab1:
    avail_years = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    c_y, c_m, c_info = st.columns([1.2, 7.3, 1.5])
    with c_y: selected_year = st.selectbox("📅 투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y")
    
    # 해당 연도의 월 리스트
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    with c_m: selected_month = st.radio("🌙 투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m")

    target_month_str = f"{selected_year}-{selected_month}"
    df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        with c_info: st.markdown(f"<div style='margin-top: 32px; text-align: right; color: #9ca3af;'>💡 <b>종목선정일:</b><br>{base_date}</div>", unsafe_allow_html=True)

        # 마켓 타이밍 및 상단 지표 계산
        kospi_curr, kospi_4m = get_kospi_ma_status(base_date)
        df_k200_t1, df_perf_t1, df_spec_t1 = get_strategy_stocks_k200(df_monthly)
        
        # 💡 [핵심] 현재 진행 중인 달이면 실시간 수익률 계산
        curr_now = datetime.now()
        is_current_month = (int(selected_year) == curr_now.year and int(selected_month) == curr_now.month)
        
        label_ret = "실시간 수익률(%)" if is_current_month else "이번달 수익률(%)"
        
        # 상단 메트릭
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1: st.metric("📉 1M 하락종목", f"{(df_k200_t1['1개월(%)'] < 0).sum()}개")
        with col_m2: st.metric("📉 3M 하락종목", f"{(df_k200_t1['3개월(%)'] < 0).sum()}개")
        with col_m3:
            cycle_y = get_cycle_year(int(selected_year))
            st.markdown(f"<div style='text-align:center; font-size:14px; color:gray;'>🇺🇸대통령 {cycle_y}년차</div>", unsafe_allow_html=True)
        with col_m4:
            status = "✅ 투자 진행" if (df_k200_t1['1개월(%)'] < 0).sum() < 100 else "🛑 투자 중지"
            st.markdown(f"<h3 style='text-align:center; margin:0;'>{status}</h3>", unsafe_allow_html=True)

        st.markdown("---")
        
        # 테이블 설정
        cfg_t1 = {
            "종목명": st.column_config.TextColumn("종목명"),
            "이번달수익률": st.column_config.NumberColumn(label_ret, format="%.2f %%")
        }

        c_l, c_r = st.columns(2)
        with c_l:
            st.subheader("🔥 퍼펙트 상승")
            st.dataframe(df_perf_t1[['종목명', '1개월(%)', '3개월(%)', '12개월(%)', '이번달수익률']].head(10), use_container_width=True, hide_index=True, column_config=cfg_t1)
        with c_r:
            st.subheader("🐎 달리는 말")
            st.dataframe(df_spec_t1[['종목명', '1개월(%)', '12개월(%)', '이번달수익률']].head(10), use_container_width=True, hide_index=True, column_config=cfg_t1)

# ==========================================
# 탭 2: 실시간 데일리 순위 (오늘 기준)
# ==========================================
with tab_2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily, dtype={'종목코드': str})
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        st.subheader(f"🕒 실시간 KOSPI 200 모멘텀 순위 (기준: {b_date_d})")
        
        # 데일리용 전략 추출
        df_k200_d, df_perf_d, df_spec_d = get_strategy_stocks_k200(df_daily)
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 🔥 퍼펙트 상승 (데일리)")
            st.dataframe(df_perf_d[['종목명', '모멘텀스코어', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)']].head(20), use_container_width=True, hide_index=True)
        with c2:
            st.markdown("### 🚀 달리는 말 (데일리)")
            st.dataframe(df_spec_d[['종목명', '모멘텀스코어', '1개월(%)', '12개월(%)']].head(20), use_container_width=True, hide_index=True)
            
        st.markdown("---")
        st.markdown("### 🏆 KOSPI 200 전체 순위 (실시간)")
        st.dataframe(df_k200_d.sort_values('모멘텀스코어', ascending=False), use_container_width=True, height=500)
    else:
        st.info("데일리 데이터 파일(`data/momentum_data_daily.csv`)이 아직 생성되지 않았습니다.")

# ==========================================
# 탭 3: 전략 조합 백테스트 (퍼펙트 + 달리는말)
# ==========================================
with tab3:
    st.subheader("📈 전략 누적 성과 시뮬레이션")
    col_s1, col_s2 = st.columns([1, 2])
    with col_s1:
        s_yr, e_yr = st.slider("테스트 기간", min_y, max_y, (min_y, max_y), key="t3_slider")
    with col_s2:
        apply_t = st.checkbox("마켓타이밍 적용 (1·3M 하락종목 100개↑ 시 현금)", value=True, key="t3_chk")
    
    r_p = st.slider("🔥 퍼펙트 상승 매수 순위", 1, 30, (1, 5), key="t3_rp")
    r_s = st.slider("🐎 달리는 말 매수 순위", 1, 30, (1, 5), key="t3_rs")

    with st.spinner("백테스트 계산 중..."):
        df_res, df_logs = run_backtest_k200(df_master, s_yr, e_yr, 4, apply_t, r_p, r_s)
        
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            
            fig = px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)")
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("#### 📊 전략 핵심 통계")
            stats = []
            for col in s_cols:
                final_v = df_cum[col].iloc[-1]
                cagr = ((final_v / 100) ** (1 / (len(df_res)/12)) - 1) * 100
                mdd = ((df_cum[col] / df_cum[col].cummax()) - 1.0).min() * 100
                stats.append({"전략명": col, "CAGR": f"{cagr:.1f}%", "MDD": f"{mdd:.1f}%", "총수익": f"{final_v-100:.1f}%"})
            st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)

# ==========================================
# 탭 4: 스코어 커스텀 백테스트
# ==========================================
with tab4:
    st.subheader("🏅 내 마음대로 가중치 백테스트")
    with st.form("custom_form"):
        c1, c2, c3, c4 = st.columns(4)
        w1 = c1.number_input("1M 가중치", 0.0, 1.0, 0.2)
        w3 = c2.number_input("3M 가중치", 0.0, 1.0, 0.8)
        w6 = c3.number_input("6M 가중치", 0.0, 1.0, 0.0)
        w12 = c4.number_input("12M 가중치", 0.0, 1.0, 0.0)
        
        submit = st.form_submit_button("🚀 커스텀 백테스트 실행")
    
    if submit:
        # 커스텀 스코어 재계산 및 심플 백테스트 로직 (내부 구현)
        df_c = df_master.copy()
        df_c['CustomScore'] = (df_c['1개월(%)']*w1) + (df_c['3개월(%)']*w3) + (df_c['6개월(%)']*w6) + (df_c['12개월(%)']*w12)
        
        # 투자월별 상위 10개 평균 수익률 계산
        res_c = df_c.groupby('투자월').apply(lambda x: x.sort_values('CustomScore', ascending=False).head(10)['이번달수익률'].mean()).reset_index()
        res_c.columns = ['투자월', '수익률']
        res_c['누적자산'] = (1 + res_c['수익률'] / 100).cumprod() * 100
        
        fig_c = px.line(res_c, x='투자월', y='누적자산', title=f"커스텀 스코어 전략 성과 (가중치: {w1}, {w3}, {w6}, {w12})")
        st.plotly_chart(fig_c, use_container_width=True)
        st.metric("최종 누적 수익률", f"{res_c['누적자산'].iloc[-1]-100:.1f}%")
