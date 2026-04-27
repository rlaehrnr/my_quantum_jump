import streamlit as st
import pandas as pd

def inject_custom_css():
    st.markdown("""
    <style>
    /* 선생님이 맞추신 2.8rem 유지 */
    .block-container { padding-top: 2.8rem !important; padding-bottom: 1rem !important; }
    .main-title { font-size: 1.5rem !important; font-weight: bold; margin-bottom: 0.5rem; }
    .strategy-desc { font-size: 0.85rem; color: #9ca3af; margin-bottom: 5px; line-height: 1.2; }
    
    /* 💡 수정됨: 라디오 버튼 한 줄 고정 및 위로 바짝 붙이기 */
    div[role="radiogroup"] { 
        gap: 8px !important; 
        flex-wrap: nowrap !important; 
        overflow-x: auto; 
        padding-top: 2px !important; 
    }
    
    .settings-box { background-color: #f8fafc; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 20px; }
    .title-link:hover { opacity: 0.7; transition: 0.2s; }
    th[data-testid="stTableColumnHeader"] div { white-space: pre-wrap !important; text-align: center !important; }
    </style>
    """, unsafe_allow_html=True)

def apply_k200_styling(row, highlight_codes=None, overlap_codes=None):
    styles = [''] * len(row)
    if '이번달수익률' in row.index:
        col_idx = row.index.get_loc('이번달수익률')
        val = row['이번달수익률']
        if pd.notna(val) and val > 0: styles[col_idx] = 'color: #D32F2F; font-weight: bold;'
        elif pd.notna(val) and val < 0: styles[col_idx] = 'color: #1976D2; font-weight: bold;'
            
    code = row.get('종목코드')
    if code and '종목명_L' in row.index:
        name_idx = row.index.get_loc('종목명_L')
        # 💡 수정됨: 겹치는 종목은 '보기 좋은 쨍한 빨간색 + 연빨강 배경'으로 강조
        if overlap_codes and code in overlap_codes: 
            styles[name_idx] = 'color: #DC2626; font-weight: 900; background-color: #FEE2E2;'
        elif highlight_codes and code in highlight_codes: 
            styles[name_idx] = 'background-color: #E8F5E9; color: #2E7D32; font-weight: bold;'
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
