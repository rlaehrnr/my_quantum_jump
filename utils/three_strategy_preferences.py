"""Keep editable strategy ratios in the browser and make them portable by URL."""
from urllib.parse import urlencode, urlsplit, urlunsplit

import streamlit as st

from utils.three_strategy import Allocation, DEFAULT_ALLOCATION


RATIO_PARAM = "ratio"
RATIO_STATE = "three_strategy_ratio"
RATIO_PENDING = "three_strategy_ratio_pending"
PAGE_SLUG = "3전략_조합"
PAGE = f"pages/0_{PAGE_SLUG}.py"
HOME_TITLE = "3전략 조합"
HOME_ICON = "🧩"
STRATEGY_TAB_PARAM = "strategy"
STRATEGY_PAGES = {
    "kospi": ("코스피", "pages/1_🇰🇷_KOSPI200_모멘텀.py", "KOSPI 200 모멘텀"),
    "snowball": ("스노우볼", "pages/6 ❄️ 스노우볼 포트.py", "스노우볼 포트"),
    "small": ("소형주", "pages/5_내 소형주 퀀트 포트.py", "내 퀀트 포트폴리오"),
}

_PREFERENCES_SCRIPT = """
export default ({data, setStateValue}) => {
    const key = "my-quantum-jump.three-strategy-ratio.v1";
    try {
        if (data.write) {
            localStorage.setItem(key, data.write);
        } else if (data.read) {
            const saved = localStorage.getItem(key);
            if (saved) setStateValue("ratio", saved);
        }
    } catch {
        // The current session and share link also work when storage is blocked.
    }
};
"""


def _decode(token):
    try:
        return Allocation.decode(token)
    except ValueError:
        return None


def current_allocation():
    return (_decode(st.query_params.get(RATIO_PARAM))
            or _decode(st.session_state.get(RATIO_STATE))
            or DEFAULT_ALLOCATION)


def mount_preferences():
    """Mount once in the router so sidebar navigation shares the same preference."""
    browser_storage = st.components.v2.component(
        "three_strategy_preferences", html="<span hidden></span>",
        css=":host { display: none; }", js=_PREFERENCES_SCRIPT,
    )
    url_allocation = _decode(st.query_params.get(RATIO_PARAM))
    if url_allocation is not None and url_allocation.encode() != st.session_state.get(RATIO_STATE):
        st.session_state[RATIO_STATE] = url_allocation.encode()
        st.session_state[RATIO_PENDING] = url_allocation.encode()
    needs_read = RATIO_STATE not in st.session_state
    with st.sidebar:
        result = browser_storage(data={"read": needs_read, "write": st.session_state.pop(RATIO_PENDING, None)},
                                 on_ratio_change=lambda: None, key="three_ratio_browser_storage")
    if needs_read:
        saved = _decode(result.ratio)
        if saved is not None:
            st.session_state[RATIO_STATE] = saved.encode()


def save_preferences(allocation):
    token = allocation.encode()
    st.session_state[RATIO_STATE] = token
    st.session_state[RATIO_PENDING] = token
    st.query_params[RATIO_PARAM] = token


def share_url(allocation):
    current = urlsplit(st.context.url or "")
    if not current.netloc:
        return None
    return urlunsplit((current.scheme, current.netloc, current.path or "/",
                       urlencode({RATIO_PARAM: allocation.encode()}), ""))
