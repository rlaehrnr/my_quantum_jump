"""스노우볼 통합 포트의 브라우저별 마지막 제출 잔액."""
import streamlit as st


def normalize_balance_amounts(values):
    """계좌 네 개의 만원 단위 잔액 또는 유효하지 않을 때 None."""
    if (isinstance(values, (list, tuple)) and len(values) == 4
            and all(type(value) is int and 0 <= value <= (1 << 53) - 1 for value in values)):
        return tuple(values)
    return None


browser_balance_storage = st.components.v2.component(
    "snowball_balance_storage",
    html='<span hidden></span>',
    js="""
    export default function ({ data, setStateValue }) {
        const storageKey = "my-quantum-jump:snowball:submitted-balances:v1";
        if (data.save !== null) {
            let saved = true;
            try {
                window.localStorage.setItem(storageKey, JSON.stringify(data.save));
            } catch {
                saved = false;
            }
            setStateValue("write_ok", saved);
        }
        if (data.restore) {
            let amounts = null;
            try {
                amounts = JSON.parse(window.localStorage.getItem(storageKey));
            } catch {
                // 저장소가 차단됐거나 이전 값이 손상되면 기존 기본값을 사용한다.
            }
            setStateValue("loaded", { amounts });
        }
    }
    """,
)
