from pathlib import Path

import streamlit as st

from utils.three_strategy_preferences import HOME_ICON, HOME_TITLE, PAGE, PAGE_SLUG, mount_preferences

st.set_page_config(page_title=HOME_TITLE, layout="wide", page_icon=HOME_ICON)

root = Path(__file__).resolve().parent
menu_order = (
    "1_🇰🇷_KOSPI200_모멘텀.py",
    "6 ❄️ 스노우볼 포트.py",
    "5_내 소형주 퀀트 포트.py",
)
pages = sorted((p for p in (root / "pages").glob("*.py") if p.name != Path(PAGE).name),
               key=lambda path: (menu_order.index(path.name) if path.name in menu_order else len(menu_order), path.name))


def redirect_old_combination_link():
    st.switch_page(PAGE, query_params=st.query_params.to_dict())


page = st.navigation([
    st.Page(PAGE, title=HOME_TITLE, icon=HOME_ICON, url_path="home", default=True),
    *(st.Page(page) for page in pages),
    st.Page(redirect_old_combination_link, url_path=PAGE_SLUG, visibility="hidden"),
])
mount_preferences()
page.run()
