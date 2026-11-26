"""Keep editable strategy ratios in the browser and make them portable by URL."""
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import streamlit as st

from utils.three_strategy import Allocation, DEFAULT_ALLOCATION


RATIO_PARAM = "ratio"
RATIO_STATE = "three_strategy_ratio"
RATIO_PENDING = "three_strategy_ratio_pending"
PAGE_SLUG = "3전략_조합"
PAGE = f"pages/0_{PAGE_SLUG}.py"

_browser_storage = st.components.v2.component(
    "three_strategy_preferences",
    html="<span hidden></span>",
    css=":host { display: none; }",
    js="""
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
""",
)


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
    url_allocation = _decode(st.query_params.get(RATIO_PARAM))
    if url_allocation is not None and url_allocation.encode() != st.session_state.get(RATIO_STATE):
        st.session_state[RATIO_STATE] = url_allocation.encode()
        st.session_state[RATIO_PENDING] = url_allocation.encode()
    needs_read = RATIO_STATE not in st.session_state
    with st.sidebar:
        result = _browser_storage(data={"read": needs_read, "write": st.session_state.pop(RATIO_PENDING, None)},
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
    path = quote(f"/{PAGE_SLUG}")
    return urlunsplit((current.scheme, current.netloc, path,
                       urlencode({RATIO_PARAM: allocation.encode()}), ""))
