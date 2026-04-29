import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import FinanceDataReader as fdr

# 1. 페이지 설정 및 초기화
st.set_page_config(page_title="KOREA 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data, get_folder_hash
from utils.calculator import (
    get_cycle_year, 
    PRESIDENTIAL_DANGEROUS_MONTHS, 
    get_kospi_ma_all, 
    get_strategy_stocks_korea, 
    run_backtest_korea, 
    get_kospi_timing_for_backtest, 
    get_idx_kr
)
from utils.ui_components import inject_custom_css, apply_korea_styling, style_kospi_ma

# CSS 주입
inject_custom_css()

# --- [상단 타이틀] ---
st.markdown('''
    <div style="margin-bottom: 20px;">
        <a href="https://m.stock.naver.com/" target="_blank" class="title-link" style="text-decoration: none; color: inherit;">
            <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
                <h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800; line-height: 1.2; word-break: keep-all;">🇰🇷 KOREA 통합 모멘텀 (P150+D150)</h1>
                <span style="font-size: 0.95rem; color: #3b82f6; background-color: #eff6ff; padding: 4px 10px; border-radius: 6px; border: 1px solid #bfdbfe; white-space: nowrap;">🔗 네이버 증권 이동</span>
            </div>
        </a>
    </div>
''', unsafe_allow_html=True)

# 2. 데이터 로드 (KOREA 경로 설정)
archive_path = "archive_korea"
f_hash = get_folder_hash(archive_path) 
df_master = load_archive_data(archive_path, f_hash) 
f_daily = 'data/momentum_data_daily_korea.csv'

if df_master.empty:
    st.error("🚨 archive_korea 폴더에 정상적인 데이터가 없습니다! (월간 봇을 실행해 파일을 생성해 주세요)")
    st.stop()

# 3. 공통 전처리
df_master['종목코드'] = df_master['종목코드'].astype(str).str.zfill(6)
df_master = df_master[df_master['종목코드'].str.endswith('0')].copy()

# 숫자 데이터 안전 처리
for col in ['시가총액', '종가', '거래량']:
    if col in df_master.columns:
        df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)

# 시가총액 단위 조정 (억 단위)
if '시가총액' in df_master.columns and df_master['시가총액'].max() > 1000000000:
    df_master['시가총액'] = df_master['시가총액'] / 100000000

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

# --- [4. 캐싱 및 헬퍼 함수] ---

@st.cache_data(show_spinner=False)
def cached_run_backtest_korea_tab3(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    # KOREA 전용 백테스트 호출 (MA만 참고하는 로직)
    return run_backtest_korea(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct)

@st.cache_data(show_spinner=False)
def cached_run_custom_backtest_tab4(df, start_year_c, end_year_c, ma_months_t4, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e):
    # 1. 마켓타이밍 데이터 가져오기
    timing_df_t4 = get_kospi_timing_for_backtest(ma_months_t4)
    records_c, trade_logs_c = [], []
    
    for m_str in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m_str.split('-')[0])
        if not (start_year_c <= m_yr <= end_year_c): continue
        
        df_calc = df[df['투자월'] == m_str].copy()
        if df_calc.empty: continue
        
        base_ym_c = pd.to_datetime(df_calc['종목선정일'].iloc[0]).strftime('%Y-%m')
        is_below_ma = timing_df_t4.loc[base_ym_c, 'is_below_ma'] if base_ym_c in timing_df_t4.index else False
        
        # 💡 [핵심 수정] KOREA 통합은 하락 종목 수 체크 없이 '이동평균선'만 봅니다.
        mult_c = 0.0 if (apply_timing_c and is_below_ma) else 1.0
        
        # 스코어 계산 및 필터링
        df_calc['스코어'] = (df_calc['1개월(%)']*w1) + (df_calc['3개월(%)']*w3) + (df_calc['6개월(%)']*w6) + (df_calc['12개월(%)']*w12)
        q_limit = df_calc['스코어'].quantile(1 - (custom_pct / 100.0))
        target = df_calc[df_calc['스코어'] >= q_limit].sort_values('스코어', ascending=False).iloc[rank_c_s-1 : rank_c_e]
        
        avg_ret = target['이번달수익률'].mean() if not target.empty else 0
        records_c.append({'투자월': m_str, 'invested': mult_c > 0, '커스텀 전략': avg_ret * mult_c})
        
        if mult_c > 0:
            for i, (_, r) in enumerate(target.iterrows()):
                trade_logs_c.append({'투자월': m_str, '전략': '커스텀', '순위': f"{i+rank_c_s}위", '종목명': r['종목명'], '수익률(%)': r['이번달수익률']})
        else:
            trade_logs_c.append({'투자월': m_str, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records_c), pd.DataFrame(trade_logs_c)

# 통계 스타일링 함수
def get_styled_stats_local(df_stats):
    def style_stats(x):
        if isinstance(x, str) and '%' in x:
            if '-' in x: return 'color: #1976D2; font-weight:bold;'
            elif x != '0.0%': return 'color: #D32F2F; font-weight:bold;'
        return ''
    try: return df_stats.style.map(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
    except AttributeError: return df_stats.style.applymap(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])

# 5. 컬럼 설정 및 테이블 설정
ma_cfg = {
    "지수_L": st.column_config.LinkColumn("지수", display_text=r"#(.+)"),
    "현재가_L": st.column_config.LinkColumn("현재가", display_text=r"#(.+)"),
    "4개월선": st.column_config.NumberColumn("4개월선", format="%.2f"),
    "5개월선": st.column_config.NumberColumn("5개월선", format="%.2f"),
    "6개월선": st.column_config.NumberColumn("6개월선", format="%.2f"),
    "10개월선": st.column_config.NumberColumn("10개월선", format="%.2f"),
    "12개월선": st.column_config.NumberColumn("12개월선", format="%.2f"),
}

main_cfg = {
    "통합티커_L": st.column_config.LinkColumn("티커", display_text=r"#(.+)"), 
    "종목명_L": st.column_config.LinkColumn("종목명", display_text=r"#(.+)"), 
    "시가총액": st.column_config.NumberColumn("시가총액(억)", format="%,.0f"),
    "종가": st.column_config.NumberColumn("종가(선정일)", format="%,.0f"),
    "1개월(%)": st.column_config.NumberColumn(format="%.1f"), 
    "3개월(%)": st.column_config.NumberColumn(format="%.1f"), 
    "6개월(%)": st.column_config.NumberColumn(format="%.1f"), 
    "12개월(%)": st.column_config.NumberColumn(format="%.1f"),
    "이번달수익률": st.column_config.NumberColumn("이번달 수익률(%)", format="%.2f") 
}

# --- [6. 탭 구성 시작] ---
tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 조합 백테스트", "🏅 스코어 커스텀 백테스트"])

# ==========================================
# 탭 1: 월별 상세 분석
# ==========================================
with tab1:
    avail_years = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    c_y, c_m = st.columns([1.2, 8.8])
    with c_y: 
        selected_year = st.selectbox("투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y")
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    with c_m:
        selected_month = st.radio("투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m")

    target_month_str = f"{selected_year}-{selected_month}"
    df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        kospi_curr, kospi_mas = get_kospi_ma_all(base_date)
        ma_df = pd.DataFrame([{'지수_L': "https://m.stock.naver.com/domestic/index/KOSPI/total#KOSPI", '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSPI#{kospi_curr:,.2f}", 'base_price': round(kospi_curr, 2), '4개월선': kospi_mas.get(4, 0), '5개월선': kospi_mas.get(5, 0), '6개월선': kospi_mas.get(6, 0), '10개월선': kospi_mas.get(10, 0), '12개월선': kospi_mas.get(12, 0)}])
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        _, df_perf_t1, df_spec_t1 = get_strategy_stocks_korea(df_monthly)
        kospi_1m, kospi_3m = get_idx_kr(base_date)
        
        is_below_ma = (kospi_curr > 0) and (kospi_curr < kospi_mas.get(6, 0))
        status, box_c, text_c = ("🛑 투자 중지", "#FFEBEE", "#C62828") if is_below_ma else ("✅ 투자 진행", "#E8F5E9", "#2E7D32")
        
        col1, col2, col3, col4, col5, col6 = st.columns([0.9, 0.9, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric("📈 KOSPI 1M", f"{kospi_1m}%")
        with col2: st.metric("📈 KOSPI 3M", f"{kospi_3m}%")
        with col3: st.metric("📉 1개월 하락", f"{(df_monthly['1개월(%)'] < 0).sum()}개")
        with col4: st.metric("📉 3개월 하락", f"{(df_monthly['3개월(%)'] < 0).sum()}개")
        with col5: 
            cycle_yr = get_cycle_year(int(selected_year))
            bad_m = ", ".join(f"{m}월" for m in PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_yr, []))
            st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 12px; font-weight: bold; color: #64748b;">🇺🇸대통령 <span style="color:#0047AB;">{cycle_yr}년차</span></div><div style="font-size: 16px; color: #D84315; font-weight:900;">🚨 위험달: {bad_m or "없음"}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_c}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_c}; height: 95px; display: flex; flex-direction: column; justify-content: center;"><p style="margin: 0; font-size: 12px; color: {text_c}; font-weight: bold;">최종 판단</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_c};">{status}</div></div>', unsafe_allow_html=True)
        
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        for df in [df_perf_t1, df_spec_t1, df_monthly]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#KOSPI:{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)

        c_l, c_r = st.columns(2)
        with c_l:
            top_n_p = st.number_input("p_n", 1, max(1, len(df_perf_t1)), 6, key="calc_p")
            st.dataframe(df_perf_t1.style.apply(apply_korea_styling, highlight_codes=df_perf_t1.head(top_n_p)['종목코드'].tolist(), axis=1), use_container_width=True, hide_index=True, column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)
        with c_r:
            top_n_s = st.number_input("s_n", 1, max(1, len(df_spec_t1)), 2, key="calc_s")
            st.dataframe(df_spec_t1.style.apply(apply_korea_styling, highlight_codes=df_spec_t1.head(top_n_s)['종목코드'].tolist(), axis=1), use_container_width=True, hide_index=True, column_order=['통합티커_L', '종목명_L', '1개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)

# ==========================================
# 탭 2: 데일리 실시간 순위
# ==========================================
with tab2:
    if os.path.exists(f_daily):
        df_daily = pd.read_csv(f_daily, dtype={'종목코드': str})
        df_daily['종목코드'] = df_daily['종목코드'].astype(str).str.zfill(6)
        b_date_d = df_daily['기준일'].iloc[0] if '기준일' in df_daily.columns else "오늘"
        
        for col in ['시가총액', '종가']:
            if col in df_daily.columns: df_daily[col] = pd.to_numeric(df_daily[col], errors='coerce').fillna(0)
        
        st.markdown(f"### 🕒 데일리 실시간 순위 (기준: {b_date_d})")
        df_k, df_p_d, df_s_d = get_strategy_stocks_korea(df_daily)
        
        for df in [df_p_d, df_s_d, df_k]:
            df['통합티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}#KOSPI:{r['종목코드']}", axis=1)
            df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)

        c_d1, c_d2 = st.columns(2)
        with c_d1: st.dataframe(df_p_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)'], column_config=main_cfg)
        with c_d2: st.dataframe(df_s_d.style.apply(apply_korea_styling, axis=1), use_container_width=True, hide_index=True, column_order=['통합티커_L', '종목명_L', '1개월(%)', '12개월(%)'], column_config=main_cfg)
    else:
        st.info("데일리 데이터 파일이 아직 생성되지 않았습니다.")

# ==========================================
# 탭 3: 전략 조합 백테스트
# ==========================================
with tab3:
    st.markdown("<h4 style='margin:0;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
    c1, c_ma, c_chk = st.columns([1, 1, 1.5])
    with c1: start_year, end_year = st.slider("📅 테스트 기간", min_y, max_y, (min_y, max_y), key='t3_yr')
    with c_ma: ma_months_t3 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 6, key='t3_ma')
    with c_chk:
        st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
        apply_timing = st.checkbox(f"🛑 마켓타이밍 적용 ({ma_months_t3}개월선 이탈 시 현금)", value=True, key='t3_chk')
    
    c2, c3, c4, c5 = st.columns([1, 1, 1, 1])
    with c2: perf_pct_t3 = st.slider("🔥 퍼펙트 상위 %", 5, 50, 30, step=5)
    with c3: rank_p_s, rank_p_e = st.slider("🔥 퍼펙트 순위", 1, 30, (1, 6))
    with c4: spec_12m_pct_t3 = st.slider("🐎 달리는말 상위 %", 5, 50, 30, step=5)
    with c5: rank_s_s, rank_s_e = st.slider("🐎 달리는말 순위", 1, 30, (1, 2))

    with st.spinner("백테스트 계산 중..."):
        df_res, df_trades = cached_run_backtest_korea_tab3(
            df_master, start_year, end_year, ma_months_t3, apply_timing, 
            (rank_p_s, rank_p_e), (rank_s_s, rank_s_e), perf_pct_t3, spec_12m_pct_t3
        )
        
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            
            # 통계 테이블 출력
            stats = []
            for col in s_cols:
                final = df_cum[col].iloc[-1]
                years = len(df_res)/12
                cagr = ((final/100)**(1/years)-1)*100
                mdd = ((df_cum[col]/df_cum[col].cummax())-1).min()*100
                stats.append({"전략명": col, "CAGR (연평균)": f"{cagr:.1f}%", "총 누적수익률": f"{final-100:,.1f}%", "MDD (최대낙폭)": f"{mdd:.1f}%"})
            
            st.dataframe(get_styled_stats_local(pd.DataFrame(stats)), use_container_width=True, hide_index=True)
            st.plotly_chart(px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 수익률 곡선 (Log Scale)"), use_container_width=True)

# ==========================================
# 탭 4: 스코어 커스텀 백테스트
# ==========================================
with tab4:
    st.markdown("<h4 style='margin-top: 5px;'>⚙️ 가중치 설정</h4>", unsafe_allow_html=True)
    apply_timing_c = st.checkbox("🛑 마켓타이밍 적용 (MA 이탈 시 현금)", value=True, key='t4_chk_main')
    
    with st.form("custom_form"):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])
        with c1: w1 = st.number_input("📉 1개월 가중치", value=0.2, step=0.1)
        with c2: w3 = st.number_input("📈 3개월 가중치", value=0.8, step=0.1)
        with c3: w6 = st.number_input("📈 6개월 가중치", value=0.0, step=0.1)
        with c4: w12 = st.number_input("📈 12개월 가중치", value=0.0, step=0.1)
        with c5:
            st.markdown("<div style='margin-top: 28px;'></div>")
            apply_weights = st.form_submit_button("✅ 실행", use_container_width=True)
            
    c6, c_ma_c, c7, c8 = st.columns([1, 0.8, 1, 1])
    with c6: start_year_c, end_year_c = st.slider("📅 테스트 기간 ", min_y, max_y, (min_y, max_y), key='t4_yr')
    with c_ma_c: ma_months_t4 = st.slider("📉 마켓타이밍 ", 1, 12, 6, key='t4_ma')
    with c7: custom_pct = st.slider("🏅 상위 %", 5, 50, 30, step=5)
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위", 1, 30, (1, 10))

    if apply_weights:
        df_res_c, df_trades_c = cached_run_custom_backtest_tab4(df_master, start_year_c, end_year_c, ma_months_t4, apply_timing_c, w1, w3, w6, w12, custom_pct, rank_c_s, rank_c_e)
        if not df_res_c.empty:
            df_cum_c = (1 + df_res_c.set_index('투자월')[['커스텀 전략']] / 100).cumprod() * 100
            st.plotly_chart(px.line(df_cum_c.reset_index(), x='투자월', y='커스텀 전략', log_y=True, title="커스텀 전략 성과"), use_container_width=True)
            with st.expander("📝 월별 전체 상세 기록 보기"): st.dataframe(df_res_c.drop(columns=['invested']).set_index('투자월').style.format("{:.2f}%"), use_container_width=True)
