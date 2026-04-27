import streamlit as st
import pandas as pd

def inject_custom_css():
    st.markdown("""
    <style>
    .block-container { padding-top: 2.8rem !important; padding-bottom: 1rem !important; }
    .main-title { font-size: 1.5rem !important; font-weight: bold; margin-bottom: 0.5rem; }
    .strategy-desc { font-size: 0.85rem; color: #9ca3af; margin-bottom: 10px; line-height: 1.2; }
    
    /* 💡 수정된 부분: 라디오 버튼 간격 좁히기 및 한 줄 강제 고정 */
    div[role="radiogroup"] { 
        gap: 8px !important; 
        flex-wrap: nowrap !important; 
        overflow-x: auto; 
        padding-top: 6px; 
    }
    div[data-testid="stWidgetLabel"] { margin-bottom: -10px; }
    
    .settings-box { background-color: #f8fafc; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; margin-bottom: 20px; }
    .title-link:hover { opacity: 0.7; transition: 0.2s; }
    th[data-testid="stTableColumnHeader"] div { white-space: pre-wrap !important; text-align: center !important; }
    </style>
    """, unsafe_allow_html=True)

def apply_k200_styling(row, highlight_codes=None, overlap_codes=None):
    """ 표의 수익률 색상 및 종목명 하이라이트 스타일링 """
    styles = [''] * len(row)
    # V2 구조인 '이번달수익률'로 기준 변경
    if '이번달수익률' in row.index:
        col_idx = row.index.get_loc('이번달수익률')
        val = row['이번달수익률']
        if pd.notna(val) and val > 0: styles[col_idx] = 'color: #D32F2F; font-weight: bold;'
        elif pd.notna(val) and val < 0: styles[col_idx] = 'color: #1976D2; font-weight: bold;'
            
    code = row.get('종목코드')
    if code and '종목명_L' in row.index:
        name_idx = row.index.get_loc('종목명_L')
        if overlap_codes and code in overlap_codes: styles[name_idx] = 'background-color: #FFF59D; color: #D84315; font-weight: bold;'
        elif highlight_codes and code in highlight_codes: styles[name_idx] = 'background-color: #E8F5E9; color: #2E7D32; font-weight: bold;'
    return styles

def style_kospi_ma(df):
    """ 이평선 표 색상(빨강/파랑) 칠하기 """
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

def get_perf_html(title, df, target_month):
    """ 전략별 Top5, Top10, 모두매수 평균 수익률 HTML 생성 """
    if df.empty: return f"### {title} <span style='font-size: 15px; color: gray; font-weight: normal;'>(해당 종목 없음)</span>"
    
    # V2 구조 '이번달수익률' 기준 연산
    all_avg = df['이번달수익률'].mean()
    top5_avg = df.head(5)['이번달수익률'].mean()
    top10_avg = df.head(10)['이번달수익률'].mean()
    
    def format_val(v):
        if pd.isna(v): return "0.00%", "gray"
        color = "#D32F2F" if v > 0 else ("#1976D2" if v < 0 else "#555")
        return f"{v:+.2f}%", color
        
    a_str, a_col = format_val(all_avg)
    t5_str, t5_col = format_val(top5_avg)
    t10_str, t10_col = format_val(top10_avg)
    
    return f"### {title} <span style='font-size: 15px; font-weight: normal; color: #666;'> &nbsp; | &nbsp; 📊 {target_month}월 성적 ➔ Top5: <span style='color:{t5_col}; font-weight:bold;'>{t5_str}</span> &nbsp; Top10: <span style='color:{t10_col}; font-weight:bold;'>{t10_str}</span> &nbsp; 모두매수: <span style='color:{a_col}; font-weight:bold;'>{a_str}</span></span>"
