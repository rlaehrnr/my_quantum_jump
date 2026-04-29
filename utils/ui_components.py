import streamlit as st
import pandas as pd

def inject_custom_css():
    st.markdown("""
    <style>
    .block-container { padding-top: 2.8rem !important; padding-bottom: 1rem !important; }
    .main-title { font-size: 1.8rem !important; font-weight: 800; margin-bottom: 1.2rem; }
    
    /* 💡 수정됨: 어두운 색상 강제 지정(color) 제거 -> 원래 하얀색으로 복구! */
    div[data-testid="stSelectbox"] label, div[data-testid="stRadio"] label {
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        margin-bottom: 8px !important;
    }
    
    /* 라디오 버튼 한 줄 고정 및 버튼 높이 미세 조정 */
    div[role="radiogroup"] { 
        gap: 12px !important; 
        flex-wrap: nowrap !important; 
        overflow-x: auto; 
        padding-top: 5px !important; 
    }
    
    .strategy-desc { font-size: 0.85rem; color: #9ca3af; margin-bottom: 8px; line-height: 1.4; }
    .title-link:hover { opacity: 0.7; transition: 0.2s; }
    th[data-testid="stTableColumnHeader"] div { white-space: pre-wrap !important; text-align: center !important; }
    </style>
    """, unsafe_allow_html=True)

def apply_korea_styling(row, highlight_codes=None, overlap_codes=None):
    styles = [''] * len(row)
    if '이번달수익률' in row.index:
        col_idx = row.index.get_loc('이번달수익률')
        val = row['이번달수익률']
        if pd.notna(val) and val > 0: styles[col_idx] = 'color: #D32F2F; font-weight: bold;'
        elif pd.notna(val) and val < 0: styles[col_idx] = 'color: #1976D2; font-weight: bold;'
            
    code = row.get('종목코드')
    if code and '종목명_L' in row.index:
        name_idx = row.index.get_loc('종목명_L')
        if overlap_codes and code in overlap_codes: 
            styles[name_idx] = 'color: #B91C1C; font-weight: 900; background-color: #FEE2E2;'
        elif highlight_codes and code in highlight_codes: 
            styles[name_idx] = 'background-color: #E8F5E9; color: #065F46; font-weight: bold;'
    return styles

def style_kospi_ma(df):
    def apply_color(row):
        price = row['base_price']
        styles = [''] * len(row)
        for i, col in enumerate(row.index):
            if '개월선' in col:
                val = row[col]
                if pd.notna(val):
                    if price > val: styles[i] = 'color: #EF4444; font-weight: bold;' 
                    elif price < val: styles[i] = 'color: #3B82F6; font-weight: bold;' 
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
        if e == '진행중': return '진행중'
        sd, ed = pd.to_datetime(s), pd.to_datetime(e)
        return f"{(ed.year - sd.year) * 12 + (ed.month - sd.month)}개월"
    res_df['기간'] = res_df.apply(lambda r: f"{r['시작일']} ~ {r['최저일']}", axis=1)
    res_df['회복기간'] = res_df.apply(lambda r: calc_months(r['시작일'], r['회복일']), axis=1)
    res_df['MDD'] = res_df['MDD'].apply(lambda x: f"{x:.2f}%")
    return res_df[['MDD', '기간', '회복기간']]

def get_monthly_heatmap(df_res, strategy_col):
    temp = df_res[['투자월', strategy_col]].copy()
    temp['Year'] = temp['투자월'].apply(lambda x: str(x.split('-')[0]))
    temp['Month'] = temp['투자월'].apply(lambda x: int(x.split('-')[1]))
    pivot = temp.pivot(index='Year', columns='Month', values=strategy_col)
    for m in range(1, 13):
        if m not in pivot.columns: pivot[m] = float('nan')
    pivot = pivot[list(range(1, 13))]
    pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    pivot.loc['평균'] = pivot.mean()
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
    try: styled = pivot.style.format("{:+.1f}", na_rep="").map(color_cells)
    except AttributeError: styled = pivot.style.format("{:+.1f}", na_rep="").applymap(color_cells)
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
