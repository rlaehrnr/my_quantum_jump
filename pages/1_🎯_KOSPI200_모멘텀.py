import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

# 우리가 만든 utils 폴더에서 핵심 기능 불러오기!
from utils.data_loader import load_archive_data
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS, get_kospi_ma_status, get_strategy_stocks_k200, run_backtest_k200

# CSS 들여쓰기를 완벽하게 제거하여 버그를 차단했습니다.
st.markdown('''
<style>
.block-container { padding-top: 2rem !important; padding-bottom: 1rem !important; }
.strategy-desc { font-size: 0.85rem; color: #9ca3af; margin-bottom: 10px; line-height: 1.2; }
div[role="radiogroup"] { gap: 15px !important; flex-wrap: wrap; padding-top: 5px; }
th[data-testid="stTableColumnHeader"] div { white-space: pre-wrap !important; text-align: center !important; }
</style>
''', unsafe_allow_html=True)

st.markdown('''
<div style="margin-bottom: 20px;">
<a href="https://stock.naver.com/" target="_blank" style="text-decoration: none; color: inherit;">
<div style="display: flex; align-items: center; flex-wrap: wrap; gap: 12px;">
<h1 style="margin: 0; padding: 0; font-size: 2.2rem; font-weight: 800;">🎯 KOSPI 200 모멘텀</h1>
<span style="font-size: 0.95rem; color: #3b82f6; background-color: #eff6ff; padding: 4px 10px; border-radius: 6px; border: 1px solid #bfdbfe;">🔗 네이버 증권</span>
</div></a></div>
''', unsafe_allow_html=True)

# 1. 데이터 불러오기 (data_loader.py 활용)
df_master = load_archive_data("archive_kospi")

if df_master.empty:
    st.error("🚨 `archive_kospi` 폴더에 데이터가 없습니다!")
    st.stop()

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

tab_detail, tab_summary = st.tabs(["📅 월별 상세 분석", "📈 전략 누적 성과 (백테스트)"])

# ==========================================
# 탭 1: 월별 상세 분석
# ==========================================
with tab_detail:
    sorted_years_str = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    
    col_y, col_m, col_info = st.columns([1.2, 7.3, 1.5])
    with col_y: 
        selected_year = st.selectbox("📅 투자 연도", sorted_years_str, format_func=lambda x: f"{x}년")
    
    available_months = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    with col_m:
        selected_month = st.radio("🌙 투자 월", available_months, horizontal=True, format_func=lambda x: f"{x}월")

    target_month_str = f"{selected_year}-{selected_month}"
    df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
    base_date = df_monthly['종목선정일'].iloc[0]
        
    with col_info:
        st.markdown(f"<div style='margin-top: 32px; text-align: right; color: #9ca3af;'>💡 <b>종목선정일:</b><br>{base_date}</div>", unsafe_allow_html=True)

    kospi_curr, kospi_4m_ma = get_kospi_ma_status(base_date)
    
    # 전략 두뇌(calculator)에서 계산된 KOSPI 200 데이터 받기
    df_k200, df_perf, df_spec = get_strategy_stocks_k200(df_monthly)

    neg_1m_cnt = (df_k200['1개월(%)'] < 0).sum()
    neg_3m_cnt = (df_k200['3개월(%)'] < 0).sum()

    target_year = int(selected_year)
    cycle_year = get_cycle_year(target_year)
    bad_months = PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year, [])
    bad_m_str = ", ".join(f"{m}월" for m in bad_months) if bad_months else "없음"

    is_bad_market = (neg_1m_cnt >= 100) and (neg_3m_cnt >= 100)
    is_below_4m_ma = (kospi_curr > 0) and (kospi_curr < kospi_4m_ma)

    reasons = []
    if is_bad_market: reasons.append("하락장(1,3M 100개↑)")
    if is_below_4m_ma: reasons.append("4개월선 이탈")

    if reasons:
        invest_status, box_color, text_color = "🛑 투자 중지", "#FFEBEE", "#C62828"
        status_desc = " + ".join(reasons)
    else:
        invest_status, box_color, text_color = "✅ 투자 진행", "#E8F5E9", "#2E7D32"
        status_desc = "상승장 & 4개월선 위"

    col3, col4, col5, col6 = st.columns([1.0, 1.0, 1.4, 1.6])
    with col3: st.metric(label="📉 1개월 하락", value=f"{neg_1m_cnt}개")
    with col4: st.metric(label="📉 3개월 하락", value=f"{neg_3m_cnt}개")
    with col5:
        st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 100%; min-height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 13px; font-weight: bold; color: #333; margin-bottom: 4px;">🇺🇸대통령 <span style="color:#0047AB; font-size:14px;">{cycle_year}년차</span> ({target_year}년)</div><div style="font-size: 13px; font-weight: bold; color: #D84315;">위험달: {bad_m_str}</div></div>', unsafe_allow_html=True)
    with col6:
        st.markdown(f'<div style="background-color: {box_color}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_color}; display: flex; flex-direction: column; justify-content: center; height: 100%; min-height: 95px;"><p style="margin: 0; font-size: 12px; color: {text_color}; font-weight: bold;">당시 최종 판단 ({status_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_color};">{invest_status}</div></div>', unsafe_allow_html=True)
        
    st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

    # 네이버 증권 링크 연결
    def add_links(df):
        df['티커_L'] = df.apply(lambda r: f"https://finance.naver.com/item/main.naver?code={r['종목코드']}", axis=1)
        df['종목명_L'] = df.apply(lambda r: f"https://m.stock.naver.com/fchart/domestic/stock/{r['종목코드']}#{r['종목명']}", axis=1)
        return df

    df_perf = add_links(df_perf)
    df_spec = add_links(df_spec)
    
    cfg = {
        "티커_L": st.column_config.LinkColumn("티커", display_text=r"=(\d+)"), 
        "종목명_L": st.column_config.LinkColumn("종목명", display_text=r"#(.+)"),
        "이번달수익률": st.column_config.NumberColumn(f"{selected_month}월 수익률(%)", format="%.2f %%") 
    }

    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown(f"### 🔥 퍼펙트 상승")
        st.markdown('<p class="strategy-desc">KOSPI 200 중 1, 3, 6, 12개월 수익률이 모두 상위 30% 이내이며 0보다 큰 종목</p>', unsafe_allow_html=True)
        st.dataframe(df_perf, use_container_width=True, hide_index=True, column_order=['티커_L', '종목명_L', '1개월(%)', '3개월(%)', '12개월(%)', '이번달수익률'], column_config=cfg)
    with c_right:
        st.markdown(f"### 🐎 달리는 말")
        st.markdown('<p class="strategy-desc">KOSPI 200 중 12개월 수익률 상위 30% 이내, 1개월 수익률 상위 10% 이내 (마이너스 허용)</p>', unsafe_allow_html=True)
        st.dataframe(df_spec, use_container_width=True, hide_index=True, column_order=['티커_L', '종목명_L', '1개월(%)', '12개월(%)', '이번달수익률'], column_config=cfg)

# ==========================================
# 탭 2: 전략 장기 백테스트
# ==========================================
with tab_summary:
    st.markdown("<h4 style='margin-top: 5px; margin-bottom: 0px;'>⚙️ 시뮬레이션 설정</h4>", unsafe_allow_html=True)
        
    c1, c_ma, c_chk = st.columns([1, 1, 1.5])
    with c1: start_year, end_year = st.slider("📅 테스트 기간 (연도)", min_y, max_y, (min_y, max_y))
    with c_ma: ma_months_t2 = st.slider("📉 마켓타이밍 (개월선)", 1, 12, 4)
    with c_chk:
        st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
        apply_timing = st.checkbox("🛑 마켓타이밍 적용 (선택 이평선 이탈 OR 1·3M 하락종목 100개↑ 시 현금)", value=True)
        
    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
    
    c3, c5 = st.columns(2)
    with c3: rank_p_start, rank_p_end = st.slider("🔥 퍼펙트 상승 (매수 순위)", 1, 30, (1, 5))
    with c5: rank_s_start, rank_s_end = st.slider("🐎 달리는 말 (매수 순위)", 1, 30, (1, 5))

    with st.spinner("수익률 연산 중..."):
        # 💡 보일러실(calculator.py)에서 연산 결과만 쏙 받아옵니다!
        df_res, df_trades = run_backtest_k200(df_master, start_year, end_year, ma_months_t2, apply_timing, (rank_p_start, rank_p_end), (rank_s_start, rank_s_end))
        
        if not df_res.empty:
            strategy_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[strategy_cols] / 100).cumprod() * 100
            
            first_m_str = (pd.to_datetime(df_res['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')
            df_cum.loc[first_m_str] = 100
            df_cum = df_cum.sort_index()

            st.markdown(f"### 📈 {start_year}년 ~ {end_year}년 누적 자산 성장 곡선 (Log Scale)")
            df_melt = df_cum.reset_index().melt(id_vars='투자월', var_name='전략', value_name='누적수익률')
            fig = px.line(df_melt, x='투자월', y='누적수익률', color='전략', log_y=True)
            st.plotly_chart(fig, use_container_width=True)
            
            # 한글 깨짐 방지 다운로드
            st.download_button("📥 백테스트 매수 상세 내역 전체 다운로드 (CSV)", data=df_trades.to_csv(index=False).encode('utf-8-sig'), file_name="KOSPI200_백테스트.csv", mime="text/csv")
            
            st.markdown("#### 📊 전략별 핵심 통계 (초기 자본 100 기준)")
            stats = []
            total_months = len(df_res)
            invested_months = df_res['invested'].sum()

            for col in strategy_cols:
                final_val = df_cum[col].iloc[-1]
                cagr = ((final_val / 100) ** (1 / (total_months/12)) - 1) * 100 if final_val > 0 else -100.0
                win_rate = ((df_res.loc[df_res['invested'], col] > 0).sum() / invested_months * 100) if invested_months > 0 else 0
                mdd = ((df_cum[col] / df_cum[col].cummax()) - 1.0).min() * 100
                
                stats.append({"전략명": col, "CAGR (연평균)": f"{cagr:.1f}%", "MDD (최대낙폭)": f"{mdd:.1f}%", "승률": f"{win_rate:.1f}%"})
                
            st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)
