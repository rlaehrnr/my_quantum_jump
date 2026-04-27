import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import os

st.set_page_config(page_title="KOSPI 200 모멘텀 터미널", layout="wide")

from utils.data_loader import load_archive_data
from utils.calculator import get_cycle_year, PRESIDENTIAL_DANGEROUS_MONTHS, get_kospi_ma_all, get_strategy_stocks_k200, run_backtest_k200, get_kospi_timing_for_backtest, get_idx_kr
from utils.ui_components import inject_custom_css, apply_k200_styling, style_kospi_ma, get_perf_html

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
    st.error("🚨 `archive_kospi` 폴더에 데이터가 없습니다!")
    st.stop()

years_list = sorted(df_master['투자연도'].unique().astype(int))
min_y, max_y = min(years_list), max(years_list)

# 💡 통계 색상 전용 헬퍼 함수
def style_stats(x):
    if isinstance(x, str) and '%' in x:
        if '-' in x: return 'color: #1976D2; font-weight:bold;'
        elif x != '0.0%': return 'color: #D32F2F; font-weight:bold;'
    return ''

tab1, tab2, tab3, tab4 = st.tabs(["📅 월별 상세 분석", "🕒 실시간 데일리 순위", "📈 전략 조합 백테스트", "🏅 스코어 커스텀 백테스트"])

# ==========================================
# 탭 1: 월별 상세 분석
# ==========================================
with tab1:
    avail_years = sorted(df_master['투자연도'].unique().astype(str), reverse=True)
    
    # 💡 1. 컬럼 비율 수정: 가운데 '월 선택' 영역(7.0 -> 7.5)을 넓혀서 12월이 밀리지 않게 공간 확보
    c_y, c_m, c_info = st.columns([1.2, 7.5, 1.7])
    
    with c_y: selected_year = st.selectbox("📅 투자 연도", avail_years, format_func=lambda x: f"{x}년", key="t1_y")
    
    m_list = sorted(df_master[df_master['투자연도'] == int(selected_year)]['투자월'].apply(lambda x: x.split('-')[1]).unique())
    with c_m: selected_month = st.radio("🌙 투자 월", m_list, horizontal=True, format_func=lambda x: f"{x}월", key="t1_m")

    target_month_str = f"{selected_year}-{selected_month}"
    df_monthly = df_master[df_master['투자월'] == target_month_str].copy()
    
    if not df_monthly.empty:
        base_date = df_monthly['종목선정일'].iloc[0]
        
        # 💡 2. 높이 일치 및 한 줄 고정: margin-top: 38px, font-size: 0.85rem, white-space: nowrap 적용
        with c_info: st.markdown(f"<div style='margin-top: 38px; text-align: right; color: #9ca3af; font-size: 0.85rem; white-space: nowrap;'>💡 <b>선정일:</b> {base_date}</div>", unsafe_allow_html=True)

        kospi_curr, kospi_mas = get_kospi_ma_all(base_date)
        
        ma_df = pd.DataFrame([{
            '지수_L': "https://m.stock.naver.com/domestic/index/KOSPI/total#KOSPI",
            '현재가_L': f"https://m.stock.naver.com/fchart/domestic/index/KOSPI#{kospi_curr:,.2f}",
            'base_price': round(kospi_curr, 2),
            '4개월선': kospi_mas.get(4, 0), '5개월선': kospi_mas.get(5, 0),
            '6개월선': kospi_mas.get(6, 0), '10개월선': kospi_mas.get(10, 0),
            '12개월선': kospi_mas.get(12, 0)
        }])
        
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
        st.dataframe(style_kospi_ma(ma_df), use_container_width=True, hide_index=True, column_config=ma_cfg)
        
        df_k200_t1, df_perf_t1, df_spec_t1 = get_strategy_stocks_k200(df_monthly)
        kospi_1m, kospi_3m = get_idx_kr(base_date)
        neg_1m_cnt = (df_k200_t1['1개월(%)'] < 0).sum()
        neg_3m_cnt = (df_k200_t1['3개월(%)'] < 0).sum()
        
        base_dt = pd.to_datetime(base_date)
        target_dt = base_dt + pd.DateOffset(months=1)
        target_year = target_dt.year
        cycle_year = get_cycle_year(target_year)
        bad_months_this_year = PRESIDENTIAL_DANGEROUS_MONTHS.get(cycle_year, [])
        bad_m_str = ", ".join(f"{m}월" for m in bad_months_this_year) if bad_months_this_year else "없음"

        is_bad_market = (neg_1m_cnt >= 100) and (neg_3m_cnt >= 100)
        is_below_4m_ma = (kospi_curr > 0) and (kospi_curr < kospi_mas.get(4, 0))

        reasons = []
        if is_bad_market: reasons.append("하락장(1,3M 100개↑)")
        if is_below_4m_ma: reasons.append("4개월선 이탈")

        if reasons:
            invest_status, box_color, text_color, status_desc = "🛑 투자 중지", "#FFEBEE", "#C62828", " + ".join(reasons)
        else:
            invest_status, box_color, text_color, status_desc = "✅ 투자 진행", "#E8F5E9", "#2E7D32", "상승장 & 4개월선 위"

        col1, col2, col3, col4, col5, col6 = st.columns([0.9, 0.9, 1.0, 1.0, 1.4, 1.6])
        with col1: st.metric(label="📈 KOSPI 1M", value=f"{kospi_1m}%")
        with col2: st.metric(label="📈 KOSPI 3M", value=f"{kospi_3m}%")
        with col3: st.metric(label="📉 1개월 하락", value=f"{neg_1m_cnt}개")
        with col4: st.metric(label="📉 3개월 하락", value=f"{neg_3m_cnt}개")
        with col5: st.markdown(f'<div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid #d1d5db; height: 100%; min-height: 95px; display: flex; flex-direction: column; justify-content: center;"><div style="font-size: 13px; font-weight: bold; color: #333; margin-bottom: 4px;">🇺🇸대통령 <span style="color:#0047AB; font-size:14px;">{cycle_year}년차</span> ({target_year}년)</div><div style="font-size: 13px; font-weight: bold; color: #D84315;">위험달: {bad_m_str}</div></div>', unsafe_allow_html=True)
        with col6: st.markdown(f'<div style="background-color: {box_color}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {text_color}; display: flex; flex-direction: column; justify-content: center; height: 100%; min-height: 95px;"><p style="margin: 0; font-size: 12px; color: {text_color}; font-weight: bold;">당시 최종 판단 ({status_desc})</p><div style="margin: 4px 0 0 0; font-size: 1.5rem; font-weight: 900; color: {text_color};">{invest_status}</div></div>', unsafe_allow_html=True)
        st.markdown("<hr style='margin: 1rem 0;'>", unsafe_allow_html=True)

        top5_p = df_perf_t1.head(5)['종목코드'].tolist()
        top5_s = df_spec_t1.head(5)['종목코드'].tolist()
        overlap_codes = set(top5_p).intersection(set(top5_s))
        
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
        st.subheader("🏆 KOSPI 200 전체 순위 (과거)")
        st.dataframe(df_k200_t1.style.apply(apply_k200_styling, axis=1), 
                     use_container_width=True, height=600, hide_index=True,
                     column_order=['통합티커_L', '종목명_L', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'], column_config=main_cfg)

# ==========================================
# 탭 2: 데일리 실시간 순위
# ==========================================
with tab2:
    if os.path.exists(f_daily):
        pass 
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
    st.markdown("##### 🔥 전략 상세 조건 필터")
    
    # 💡 4) 상위 % 설정 슬라이더 복원!
    c2, c3, c4, c5 = st.columns([1, 1, 1, 1])
    with c2: perf_pct = st.slider("🔥 퍼펙트 상승 (1,3,6,12M 상위 %)", 5, 50, 30, step=5)
    with c3: rank_p_s, rank_p_e = st.slider("🔥 퍼펙트 상승 매수 순위", 1, 30, (1, 6), key="t3_rp")
    with c4: spec_12m_pct = st.slider("🐎 달리는 말 (12M 상위 %, 1M은 10%)", 5, 50, 30, step=5)
    with c5: rank_s_s, rank_s_e = st.slider("🐎 달리는 말 매수 순위", 1, 30, (1, 2), key="t3_rs")

    with st.spinner("엔진 구동 중..."):
        # 엔진에 슬라이더 변수(perf_pct, spec_12m_pct) 전달
        df_res, df_trades = run_backtest_k200(df_master, start_year, end_year, ma_months_t3, apply_timing, (rank_p_s, rank_p_e), (rank_s_s, rank_s_e), perf_pct=perf_pct, spec_12m=spec_12m_pct)
        if not df_res.empty:
            s_cols = [c for c in df_res.columns if c not in ['투자월', 'invested']]
            df_cum = (1 + df_res.set_index('투자월')[s_cols] / 100).cumprod() * 100
            
            first_m_str = (pd.to_datetime(df_res['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')
            df_cum.loc[first_m_str] = 100
            df_cum = df_cum.sort_index()
            
            fig = px.line(df_cum.reset_index().melt(id_vars='투자월'), x='투자월', y='value', color='variable', log_y=True, title="누적 자산 성장 곡선 (Log Scale)")
            st.plotly_chart(fig, use_container_width=True)
            
            # 💡 2) 다운로드 버튼 복원!
            st.download_button(
                label="📥 백테스트 매수 상세 내역 전체 다운로드 (CSV)",
                data=df_trades.to_csv(index=False).encode('utf-8-sig'),
                file_name=f"KOSPI200_백테스트_매수내역_{datetime.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            
            st.markdown("#### 📊 전략 핵심 통계 (초기 자본 100 기준)")
            stats = []
            total_months = len(df_res)
            invested_months = df_res['invested'].sum()
            invest_ratio = (invested_months / total_months) * 100 if total_months > 0 else 0

            for col in s_cols:
                final_val = df_cum[col].iloc[-1]
                total_ret = final_val - 100
                years = total_months / 12
                cagr = ((final_val / 100) ** (1 / years) - 1) * 100 if final_val > 0 else -100.0
                
                if invested_months > 0:
                    win_months = (df_res.loc[df_res['invested'], col] > 0).sum()
                    win_rate = (win_months / invested_months) * 100
                    avg_ret = df_res.loc[df_res['invested'], col].mean()
                else: win_months = 0; win_rate = 0.0; avg_ret = 0.0
                
                roll_max = df_cum[col].cummax()
                mdd = ((df_cum[col] / roll_max) - 1.0).min() * 100
                
                stats.append({"전략명": col, "CAGR (연평균)": f"{cagr:.1f}%", "총 누적수익률": f"{total_ret:,.1f}%", "MDD (최대낙폭)": f"{mdd:.1f}%", "투자월 비율": f"{invest_ratio:.1f}%", "월별 승률": f"{win_rate:.1f}%", "평균 수익률(투자월)": f"{avg_ret:.2f}%"})
                
            # 💡 1) 통계 색상 반영 (style_stats 호출)
            df_stats = pd.DataFrame(stats)
            try: styled_stats = df_stats.style.map(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
            except AttributeError: styled_stats = df_stats.style.applymap(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
            st.dataframe(styled_stats, use_container_width=True, hide_index=True)
            
            # 💡 2) 월별 수익률 상세 기록 보기 (Expander) 복원!
            with st.expander(f"📝 {start_year}~{end_year}년 ({total_months}개월) 월별 수익률 상세 기록 보기"):
                display_df = df_res.drop(columns=['invested']).set_index('투자월')
                st.dataframe(display_df.style.format("{:.2f}%"), use_container_width=True)

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
        
    with st.form("custom_weight_form_k200", border=False):
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])
        with c1: w1 = st.number_input("📉 1개월 가중치", value=0.2, step=0.1, format="%.1f")
        with c2: w3 = st.number_input("📈 3개월 가중치", value=0.8, step=0.1, format="%.1f")
        with c3: w6 = st.number_input("📈 6개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c4: w12 = st.number_input("📈 12개월 가중치", value=0.0, step=0.1, format="%.1f")
        with c5:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            apply_weights = st.form_submit_button("✅ 스코어 적용", use_container_width=True)
            
    st.markdown("<hr style='margin: 0px 0px 15px 0px;'>", unsafe_allow_html=True)
    
    c6, c_ma_c, c7, c8 = st.columns([1, 0.8, 1, 1])
    with c6: start_year_c, end_year_c = st.slider("📅 커스텀 테스트 기간", min_y, max_y, (min_y, max_y), key='t4_yr')
    with c_ma_c: ma_months_t4 = st.slider("📉 마켓타이밍 (개월선) ", 1, 12, 4, key='t4_ma')
    with c7: custom_pct = st.slider("🏅 커스텀 스코어 상위 %", 5, 50, 30, step=5)
    with c8: rank_c_s, rank_c_e = st.slider("🏅 매수 순위 범위", 1, 30, (1, 10), key='t4_rnk')

    if apply_weights or 'custom_run' not in st.session_state:
        st.session_state['custom_run'] = True
        
    if st.session_state.get('custom_run', False):
        with st.spinner("커스텀 가중치 시뮬레이션 연산 중..."):
            timing_df_t4 = get_kospi_timing_for_backtest(ma_months_t4)
            records_c = []
            trade_logs_c = [] # 💡 매수 내역 저장용 리스트 추가!
            
            for m_str in sorted(df_master['투자월'].dropna().unique()):
                m_year = int(m_str.split('-')[0])
                if not (start_year_c <= m_year <= end_year_c): continue
                
                df_calc = df_master[df_master['투자월'] == m_str].copy()
                if df_calc.empty: continue
                
                base_date_c = df_calc['종목선정일'].iloc[0]
                base_ym_c = pd.to_datetime(base_date_c).strftime('%Y-%m')
                
                neg_1m = (df_calc['1개월(%)'] < 0).sum()
                neg_3m = (df_calc['3개월(%)'] < 0).sum()
                is_bad_market = (neg_1m >= 100 and neg_3m >= 100)
                is_below_ma = timing_df_t4.loc[base_ym_c, 'is_below_ma'] if base_ym_c in timing_df_t4.index else False
                
                mult_c = 0.0 if (apply_timing_c and (is_bad_market or is_below_ma)) else 1.0
                
                df_calc['커스텀스코어'] = (df_calc['1개월(%)']*w1) + (df_calc['3개월(%)']*w3) + (df_calc['6개월(%)']*w6) + (df_calc['12개월(%)']*w12)
                q_val_c = df_calc['커스텀스코어'].quantile(1.0 - (custom_pct / 100.0))
                
                target_group = df_calc[(df_calc['커스텀스코어']>=q_val_c) & (df_calc['1개월(%)']>0)].sort_values('커스텀스코어', ascending=False).iloc[rank_c_s-1 : rank_c_e]
                ret_target = (target_group['이번달수익률'].mean() * mult_c) if not target_group.empty else 0.0
                
                records_c.append({'투자월': m_str, 'invested': mult_c > 0.0, f'🏅 커스텀 스코어 ({rank_c_s}~{rank_c_e}위)': ret_target})
                
                # 💡 매수 내역 기록 로직 추가
                if mult_c == 0.0:
                    trade_logs_c.append({'투자월': m_str, '전략': '마켓타이밍 작동', '매수순위': '-', '종목명': '현금 (투자중지)', '종목코드': '-', '수익률(%)': 0.0})
                else:
                    for i, (_, row) in enumerate(target_group.iterrows()):
                        trade_logs_c.append({'투자월': m_str, '전략': '커스텀 스코어', '매수순위': f"{i + rank_c_s}위", '종목명': row['종목명'], '종목코드': row['종목코드'], '수익률(%)': row['이번달수익률']})

            df_res_c = pd.DataFrame(records_c).fillna(0.0)
            if not df_res_c.empty:
                col_name = f'🏅 커스텀 스코어 ({rank_c_s}~{rank_c_e}위)'
                df_cum_c = (1 + df_res_c.set_index('투자월')[[col_name]] / 100).cumprod() * 100
                
                first_m_str_c = (pd.to_datetime(df_res_c['투자월'].iloc[0]) - pd.DateOffset(months=1)).strftime('%Y-%m')
                df_cum_c.loc[first_m_str_c] = 100
                df_cum_c = df_cum_c.sort_index()

                fig_c = px.line(df_cum_c.reset_index(), x='투자월', y=col_name, log_y=True, title="커스텀 가중치 누적 성과")
                st.plotly_chart(fig_c, use_container_width=True)
                
                # 💡 다운로드 버튼 추가!
                df_trades_c = pd.DataFrame(trade_logs_c)
                st.download_button(
                    label="📥 커스텀 백테스트 매수 상세 내역 다운로드 (CSV)",
                    data=df_trades_c.to_csv(index=False).encode('utf-8-sig'),
                    file_name=f"KOSPI200_커스텀_백테스트_{datetime.today().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
                
                st.markdown("#### 📊 전략 핵심 통계")
                stats_c = []
                total_months_c = len(df_res_c)
                invested_months_c = df_res_c['invested'].sum()
                invest_ratio_c = (invested_months_c / total_months_c) * 100 if total_months_c > 0 else 0

                final_val_c = df_cum_c[col_name].iloc[-1]
                total_ret_c = final_val_c - 100
                years_c = total_months_c / 12
                cagr_c = ((final_val_c / 100) ** (1 / years_c) - 1) * 100 if final_val_c > 0 else -100.0
                
                if invested_months_c > 0:
                    win_months_c = (df_res_c.loc[df_res_c['invested'], col_name] > 0).sum()
                    win_rate_c = (win_months_c / invested_months_c) * 100
                    avg_ret_c = df_res_c.loc[df_res_c['invested'], col_name].mean()
                else: win_months_c = 0; win_rate_c = 0.0; avg_ret_c = 0.0
                
                roll_max_c = df_cum_c[col_name].cummax()
                mdd_c = ((df_cum_c[col_name] / roll_max_c) - 1.0).min() * 100
                
                stats_c.append({"전략명": col_name, "CAGR (연평균)": f"{cagr_c:.1f}%", "총 누적수익률": f"{total_ret_c:,.1f}%", "MDD (최대낙폭)": f"{mdd_c:.1f}%", "투자월 비율": f"{invest_ratio_c:.1f}%", "월별 승률": f"{win_rate_c:.1f}%", "평균 수익률": f"{avg_ret_c:.2f}%"})
                
                df_stats_c = pd.DataFrame(stats_c)
                try: styled_stats_c = df_stats_c.style.map(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
                except AttributeError: styled_stats_c = df_stats_c.style.applymap(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
                st.dataframe(styled_stats_c, use_container_width=True, hide_index=True)
                
                with st.expander(f"📝 {start_year_c}~{end_year_c}년 ({total_months_c}개월) 월별 수익률 상세 기록 보기"):
                    display_df_c = df_res_c.drop(columns=['invested']).set_index('투자월')
                    st.dataframe(display_df_c.style.format("{:.2f}%"), use_container_width=True)
