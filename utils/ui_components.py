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
