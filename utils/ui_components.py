import streamlit as st

def inject_custom_css():
    st.markdown('''
    <style>
        /* 상단 여백 대폭 축소 */
        .block-container { padding-top: 1.5rem !important; padding-bottom: 1rem !important; }
        .main-title-container { margin-bottom: 15px; padding-top: 0px; }
        .strategy-desc { font-size: 0.85rem; color: #9ca3af; margin-bottom: 10px; line-height: 1.2; }
        div[role="radiogroup"] { gap: 15px !important; flex-wrap: wrap; padding-top: 5px; }
        th[data-testid="stTableColumnHeader"] div { white-space: pre-wrap !important; text-align: center !important; }
    </style>
    ''', unsafe_allow_html=True)

def render_kospi_ma_widget(curr_price, mas, target_ma=4):
    """ 코스피 현재가와 4, 5, 6, 10, 12개월선을 시각적으로 예쁘게 표시합니다. """
    cols = st.columns(6)
    
    with cols[0]:
        st.markdown(f"<div style='text-align: center; background-color: #f8fafc; padding: 10px; border-radius: 8px; border: 1px solid #cbd5e1; height: 100%;'>"
                    f"<p style='margin:0; font-size: 12px; font-weight: bold; color: #475569;'>현재 코스피</p>"
                    f"<p style='margin:0; font-size: 16px; font-weight: 900; color: #0f172a;'>{curr_price:,.2f}</p></div>", unsafe_allow_html=True)

    ma_list = [4, 5, 6, 10, 12]
    for i, ma_val in enumerate(ma_list):
        val = mas.get(ma_val, 0)
        is_below = (curr_price < val) if val > 0 else False
        
        # 현재가가 이평선 아래면 빨간색(위험), 위면 초록색(안전)
        color = "#ef4444" if is_below else "#22c55e"
        bg_color = "#fef2f2" if is_below else "#f0fdf4"
        border_color = "#fecaca" if is_below else "#bbf7d0"
        
        # 마켓타이밍 기준으로 선택된 이평선은 테두리를 더 굵게 강조
        border = f"2px solid {color}" if ma_val == target_ma else f"1px solid {border_color}"
        
        with cols[i+1]:
            st.markdown(f"<div style='text-align: center; background-color: {bg_color}; padding: 10px; border-radius: 8px; border: {border}; height: 100%;'>"
                        f"<p style='margin:0; font-size: 12px; font-weight: bold; color: {color};'>{ma_val}개월선</p>"
                        f"<p style='margin:0; font-size: 15px; font-weight: 800; color: {color};'>{val:,.2f}</p></div>", unsafe_allow_html=True)
