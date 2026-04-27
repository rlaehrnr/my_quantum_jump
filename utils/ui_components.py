import streamlit as st
import pandas as pd

def inject_custom_css():
    st.markdown("""
    <style>
    /* 상단 여백을 충분히 주어 제목이 잘리지 않게 함 */
    .block-container { padding-top: 4rem !important; padding-bottom: 1rem !important; }
    .main-title { font-size: 1.8rem !important; font-weight: 800; margin-bottom: 1.5rem; }
    
    /* 투자연도와 투자월의 라벨 폰트 및 높이 통일 */
    div[data-testid="stSelectbox"] label, div[data-testid="stRadio"] label {
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        color: #334155 !important;
        margin-bottom: 10px !important;
        display: inline-block !important;
        height: 24px;
    }
    
    /* 라디오 버튼 간격 및 한 줄 고정, 위로 정렬 */
    div[role="radiogroup"] { 
        gap: 10px !important; 
        flex-wrap: nowrap !important; 
        overflow-x: auto; 
        padding-top: 2px !important; 
    }
    
    /* 백테스트 섹션 헤더 스타일 */
    .bt-header { font-size: 1.1rem; font-weight: 700; color: #1e293b; margin-bottom: 8px; }

    .strategy-desc { font-size: 0.85rem; color: #64748b; margin-bottom: 8px; line-height: 1.4; }
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
        # 겹치는 종목 강조 (진한 빨강 글씨 + 부드러운 빨강 배경)
        if overlap_codes and code in overlap_codes: 
            styles[name_idx] = 'color: #B91C1C; font-weight: 900; background-color: #FEE2E2; border: 1px solid #FECACA;'
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
