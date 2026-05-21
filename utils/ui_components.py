import pandas as pd
import streamlit as st
import os

def inject_custom_css():
    st.markdown("""
        <style>
        .block-container { padding-top: 2.8rem !important; padding-bottom: 1rem !important; }
        h1 { font-size: 2.2rem !important; font-weight: 800; margin-bottom: 10px; }
        .strategy-desc { font-size: 0.85rem; color: #9ca3af; margin-bottom: 10px; line-height: 1.2; }
        div[role="radiogroup"] { gap: 12px !important; flex-wrap: wrap; }
        @media (max-width: 768px) {
            div[data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                min-width: 45% !important; flex: 1 1 45% !important; margin-bottom: 5px !important;
            }
        }
        .settings-box { background-color: #f8fafc; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 20px; }
        .title-link:hover { opacity: 0.7; transition: 0.2s; }
        th[data-testid="stTableColumnHeader"] div { white-space: pre-wrap !important; text-align: center !important; }
        </style>
    """, unsafe_allow_html=True)

def apply_korea_styling(row, highlight_codes=None, overlap_codes=None):
    """
    한국 데이터프레임 행에 색상 스타일 적용.
    - 수익률 양수: 빨강 / 음수: 파랑
    - 종목명: 중복(노랑) / 하이라이트(초록)
    
    💡 [안전성 수정] 중복 컬럼 등 예외 상황에 .index().fallback 사용.
    """
    styles = [''] * len(row)
    
    # 수익률 컬럼 색상
    ret_col = None
    if '이번달수익률' in row.index:
        ret_col = '이번달수익률'
    elif '다음달수익률(%)' in row.index:
        ret_col = '다음달수익률(%)'
    
    if ret_col:
        try:
            col_idx = list(row.index).index(ret_col)
            val = row[ret_col]
            if pd.notna(val) and val > 0:
                styles[col_idx] = 'color: #D32F2F; font-weight: bold;'
            elif pd.notna(val) and val < 0:
                styles[col_idx] = 'color: #1976D2; font-weight: bold;'
        except (ValueError, IndexError):
            pass  # 컬럼 못 찾으면 그냥 넘김
    
    # 종목명 배경색
    code = row.get('종목코드')
    if code and '종목명_L' in row.index:
        try:
            name_idx = list(row.index).index('종목명_L')
            if overlap_codes and code in overlap_codes:
                styles[name_idx] = 'background-color: #FFF59D; color: #D84315; font-weight: bold;'
            elif highlight_codes and code in highlight_codes:
                styles[name_idx] = 'background-color: #E8F5E9; color: #2E7D32; font-weight: bold;'
        except (ValueError, IndexError):
            pass
    
    return styles

def style_kospi_ma(df):
    def apply_color(row):
        price = row['base_price']
        styles = [''] * len(row)
        for i, col in enumerate(row.index):
            if '개월선' in col:
                val = row[col]
                if pd.notna(val) and price > val: styles[i] = 'color: #EF4444; font-weight: bold;' 
                elif pd.notna(val) and price < val: styles[i] = 'color: #3B82F6; font-weight: bold;' 
        return styles
    return df.style.apply(apply_color, axis=1)

def style_stats(x):
    if isinstance(x, str) and '%' in x:
        if '-' in x: return 'color: #1976D2; font-weight:bold;'
        elif x != '0.0%': return 'color: #D32F2F; font-weight:bold;'
    return ''

def get_styled_stats(df_stats):
    try: return df_stats.style.map(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])
    except AttributeError: return df_stats.style.applymap(style_stats, subset=['CAGR (연평균)', '총 누적수익률', 'MDD (최대낙폭)'])

def get_mdd_history(equity_series):
    df = equity_series.to_frame(name='equity')
    records = []
    peak_date, peak_val = df.index[0], df['equity'].iloc[0]
    trough_date, trough_val = peak_date, peak_val
    in_dd = False
    for date, row in df.iterrows():
        val = row['equity']
        if val >= peak_val:
            if in_dd:
                dd_pct = (trough_val / peak_val - 1) * 100
                if dd_pct < -0.01: records.append({'MDD': dd_pct, '시작일': peak_date, '최저일': trough_date, '회복일': date})
                in_dd = False
            peak_val, peak_date, trough_val, trough_date = val, date, val, date
        else:
            in_dd = True
            if val < trough_val: trough_val, trough_date = val, date
    if in_dd:
        dd_pct = (trough_val / peak_val - 1) * 100
        if dd_pct < -0.01: records.append({'MDD': dd_pct, '시작일': peak_date, '최저일': trough_date, '회복일': '진행중'})
    res_df = pd.DataFrame(records)
    if res_df.empty: return pd.DataFrame(columns=['MDD', '기간', '회복기간'])
    res_df = res_df.sort_values('MDD').head(10).reset_index(drop=True)
    def calc_months(s, e):
        """💡 [수정] 정확한 일수 기반 개월 계산. 1개월 미만은 일 단위로 표시."""
        if e == '진행중':
            return '진행중'
        sd, ed = pd.to_datetime(s), pd.to_datetime(e)
        days = (ed - sd).days
        if days < 30:
            return f"{days}일"
        months = days / 30.44  # 평균 한 달 일수
        return f"{months:.1f}개월"
    res_df['기간'] = res_df.apply(lambda r: f"{r['시작일']} ~ {r['최저일']}", axis=1)
    res_df['회복기간'] = res_df.apply(lambda r: calc_months(r['시작일'], r['회복일']), axis=1)
    res_df['MDD'] = res_df['MDD'].apply(lambda x: f"{x:.2f}%")
    return res_df[['MDD', '기간', '회복기간']]

# 💡 [업그레이드] 연수익률 복리 계산 및 컬럼이 추가된 히트맵 함수
def get_monthly_heatmap(df_res, strategy_col):
    temp = df_res[['투자월', strategy_col]].copy()
    temp['Year'] = temp['투자월'].apply(lambda x: str(x.split('-')[0]))
    temp['Month'] = temp['투자월'].apply(lambda x: int(x.split('-')[1]))
    pivot = temp.pivot(index='Year', columns='Month', values=strategy_col)
    
    # 1~12월 컬럼 강제 생성 및 월별 이름 지정
    for m in range(1, 13):
        if m not in pivot.columns: pivot[m] = float('nan')
    pivot = pivot[list(range(1, 13))]
    pivot.columns = ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월']
    
    # 🏆 연수익률 (복리 누적) 계산 로직 추가
    def calc_yearly_return(row):
        rets = row.dropna() / 100.0
        if len(rets) == 0:
            return float('nan')
        # 복리 누적 계산: (1+r1)*(1+r2)*... - 1
        return ((1 + rets).prod() - 1) * 100
        
    pivot['🏆 연수익률'] = pivot.apply(calc_yearly_return, axis=1)
    
    # '평균' 행 추가
    pivot.loc['평균'] = pivot.mean()
    
    # 컬러 매핑 로직 (다크 모드 유지)
    def color_cells(val):
        if pd.isna(val): return 'background-color: #1e1e26; color: transparent;'
        if val > 0:
            alpha = min(val / 12.0, 1.0) * 0.9 + 0.1
            color = f'rgba(34, 197, 94, {alpha})' 
            text_white = 'white' if alpha > 0.4 else '#e2e8f0'
            return f'background-color: {color}; color: {text_white}; text-align: center; font-weight: bold;'
        elif val < 0:
            alpha = min(abs(val) / 12.0, 1.0) * 0.9 + 0.1
            color = f'rgba(239, 68, 68, {alpha})' 
            text_white = 'white' if alpha > 0.4 else '#e2e8f0'
            return f'background-color: {color}; color: {text_white}; text-align: center; font-weight: bold;'
        return 'text-align: center; color: #94a3b8; background-color: #1e1e26;'
        
    try: styled = pivot.style.format("{:+.2f}%", na_rep="").map(color_cells)
    except AttributeError: styled = pivot.style.format("{:+.2f}%", na_rep="").applymap(color_cells)
    
    return styled

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

main_cfg = {
    "순위": st.column_config.NumberColumn("순위", format="%d위"),
    "통합티커_L": st.column_config.LinkColumn("티커", display_text=r"#(.+)"), 
    "종목명_L": st.column_config.LinkColumn("종목명", display_text=r"#(.+)"), 
    "시가총액": st.column_config.NumberColumn("시가총액(억)", format="%,.0f"),
    "종가": st.column_config.NumberColumn("종가", format="%,.0f"),
    "거래량": st.column_config.NumberColumn("거래량", format="%,.0f"),
    "1개월(%)": st.column_config.NumberColumn(format="%.1f"), 
    "3개월(%)": st.column_config.NumberColumn(format="%.1f"), 
    "6개월(%)": st.column_config.NumberColumn(format="%.1f"), 
    "12개월(%)": st.column_config.NumberColumn(format="%.1f"),
    "이번달수익률": st.column_config.NumberColumn("이번달 수익률(%)", format="%.2f") 
}

# 1. 전체 순위 하이라이트 스타일 (파스텔 옐로우 - 종목명만)
def apply_custom_total_styling(row, top_codes):
    styles = []
    is_top = row['종목코드'] in top_codes
    for col, val in row.items():
        style = ''
        if is_top and col == '종목명_L':
            style += 'background-color: #FFF9C4; font-weight: bold; color: #333;' 
        if isinstance(col, str) and ('(%)' in col or col == '커스텀스코어' or '수익률' in col):
            try:
                v = float(val)
                if v > 0: style += 'color: #D32F2F;'
                elif v < 0: style += 'color: #1976D2;'
            except: pass
        styles.append(style)
    return styles

# 2. VIX 공포지수 위젯 렌더링
def render_vix_widget(safe_date):
    vix_file = 'data/vix data.csv'
    vix_latest_high, vix_latest_date_str = "데이터없음", ""
    vix_35_date_str, vix_35_high, days_diff_str = "-", "-", "-"
    is_vix_warning = False

    if os.path.exists(vix_file):
        try:
            vix_df = pd.read_csv(vix_file)
            vix_df['날짜'] = pd.to_datetime(vix_df['날짜'])
            vix_df = vix_df.sort_values('날짜')
            if not vix_df.empty:
                latest_row = vix_df.iloc[-1]
                vix_latest_high = f"{latest_row['고가']:.2f}"
                vix_latest_date = latest_row['날짜']
                vix_latest_date_str = f"{vix_latest_date.month}/{vix_latest_date.day}"
                
                high_35_df = vix_df[vix_df['고가'] >= 35.0]
                if not high_35_df.empty:
                    last_35_row = high_35_df.iloc[-1]
                    vix_35_date_str = last_35_row['날짜'].strftime('%y/%m/%d')
                    vix_35_high = f"{last_35_row['고가']:.2f}"
                    days_diff = (pd.to_datetime(safe_date) - last_35_row['날짜']).days
                    days_diff_str = f"{days_diff}일 경과"
                    if 0 <= days_diff <= 20: is_vix_warning = True
        except: pass
        
    vix_bg = "#FFF0F0" if is_vix_warning else "#FFFFFF"
    vix_border = "#FFCDD2" if is_vix_warning else "#d1d5db"
    vix_title_color = "#C62828" if is_vix_warning else "#64748b"
    vix_val_color = "#D84315" if is_vix_warning else "#333333"
    vix_icon = "🚨" if is_vix_warning else "📊"
    vix_label = f"전일 ({vix_latest_date_str}일) 고가:" if vix_latest_date_str else "전일 고가:"
    
    return f'''<a href="https://m.stock.naver.com/worldstock/index/.VIX/total" target="_blank" style="text-decoration: none; color: inherit;">
        <div class="title-link" style="background-color: {vix_bg}; padding: 10px; border-radius: 10px; text-align: center; border: 1px solid {vix_border}; height: 95px; display: flex; flex-direction: column; justify-content: center;">
            <div style="font-size: 12px; font-weight: bold; color: {vix_title_color}; margin-bottom: 2px;">{vix_icon} VIX 35 돌파</div>
            <div style="font-size: 11px; font-weight: bold; color: {vix_title_color}; margin-bottom: 4px;">VIX {vix_35_high} - {vix_35_date_str}돌파 ({days_diff_str})</div>
            <div style="font-size: 15px; color: {vix_val_color}; font-weight:900;">{vix_label} {vix_latest_high}</div>
        </div></a>'''

# 3. 미국 전용 데이터프레임 컬럼 및 순서 설정
us_main_cfg = main_cfg.copy()
us_main_cfg.update({
    '12-1개월(%)': st.column_config.NumberColumn('12-1개월(%)', format="%.2f%%"),
    '6-1개월(%)': st.column_config.NumberColumn('6-1개월(%)', format="%.2f%%"),
    '3-1개월(%)': st.column_config.NumberColumn('3-1개월(%)', format="%.2f%%"),
    '커스텀스코어': st.column_config.NumberColumn('커스텀스코어', format="%.2f"),
    '종가': st.column_config.NumberColumn('종가', format="%.2f"),
    '시가총액': st.column_config.NumberColumn('시가총액', format="%d")
})

col_order_strat1 = ['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)', '이번달수익률']
col_order_strat2 = ['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)', '이번달수익률']
col_order_d1 = ['순위', '통합티커_L', '종목명_L', '12-1개월(%)', '6-1개월(%)']
col_order_d2 = ['순위', '통합티커_L', '종목명_L', '6-1개월(%)', '3-1개월(%)']
cols_m = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '커스텀스코어', '이번달수익률']
cols_d = ['순위', '통합티커_L', '종목명_L', '시가총액', '종가', '거래량', '1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '12-1개월(%)', '6-1개월(%)', '3-1개월(%)', '커스텀스코어']
