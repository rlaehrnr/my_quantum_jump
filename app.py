import streamlit as st

# 사이트 전체 기본 설정 (반드시 가장 위에 있어야 함)
st.set_page_config(page_title="한국 모멘텀 퀀트 대시보드", layout="wide", page_icon="📈")

st.markdown("""
<div style="margin-bottom: 20px; text-align: center; padding: 50px 0;">
    <h1 style="font-size: 3rem; font-weight: 900;">📈 KOSPI 퀀트 대시보드 V2.0</h1>
    <p style="color: #6b7280; font-size: 1.2rem;">데이터 기반의 냉철한 시스템 트레이딩 보관소입니다.</p>
</div>
""", unsafe_allow_html=True)

st.info("👈 좌측 사이드바(메뉴)에서 원하시는 시장의 모멘텀 전략을 선택해 주세요.")

st.markdown("---")
st.markdown("### 📌 V2.0 업데이트 안내")
st.markdown("""
* **아키텍처 개편:** 연산(로직)과 화면(UI)을 완벽히 분리하여 처리 속도가 대폭 향상되었습니다.
* **Golden Rule 적용:** 모든 파일과 데이터는 **[종목선정일]**과 **[이번달수익률]** 기준으로 통일되어 실전 포트폴리오 운용에 최적화되었습니다.
* **마켓타이밍 고도화:** KOSPI 200 전용 듀얼 모멘텀 (1·3M 100개 하락 + N개월선 이탈) 필터가 정밀하게 적용되었습니다.
""")
