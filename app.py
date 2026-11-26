from pathlib import Path

import streamlit as st

from utils.three_strategy_preferences import mount_preferences

st.set_page_config(page_title="종합 대시보드", layout="wide", page_icon="📊")

root = Path(__file__).resolve().parent
menu_order = (
    "0_3전략_조합.py",
    "1_🇰🇷_KOSPI200_모멘텀.py",
    "6 ❄️ 스노우볼 포트.py",
    "5_내 소형주 퀀트 포트.py",
)
home = "00_종합_대시보드.py"
pages = sorted((p for p in (root / "pages").glob("*.py") if p.name != home),
               key=lambda path: (menu_order.index(path.name) if path.name in menu_order else len(menu_order), path.name))
page = st.navigation([
    st.Page(f"pages/{home}", title="종합 대시보드", icon="📊", default=True),
    *(st.Page(page) for page in pages),
])
mount_preferences()
page.run()
