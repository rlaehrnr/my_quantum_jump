import streamlit as st
import pandas as pd
import numpy as np
import os

st.set_page_config(page_title="계절성 · 사이클 분석", layout="wide")

from utils.ui_components import inject_custom_css

inject_custom_css()

st.markdown('''<style>
[data-testid="stPageLink-NavLink"] { padding:0 !important; margin:4px 0 14px 0 !important; }
[data-testid="stPageLink-NavLink"] p { font-size:2.2rem !important; font-weight:800 !important;
    line-height:1.2 !important; margin:0 !important; word-break:keep-all; }
[data-testid="stPageLink-NavLink"]:hover p { color:#93C5FD !important; }
.sec-title { font-size:1.05rem; font-weight:800; margin:18px 0 6px 0; }
.sec-note  { font-size:0.78rem; color:#6B7280; margin:0 0 6px 0; }
</style>''', unsafe_allow_html=True)
st.page_link("app.py", label="📅 계절성 · 사이클 분석")

MONTHS = [f"{m}월" for m in range(1, 13)]
COLS = MONTHS + ["합계"]
INDEXES = [
    ("SP500", "🇺🇸 S&P 500"),
    ("NASDAQ", "🇺🇸 나스닥"),
    ("KOSPI", "🇰🇷 코스피"),
    ("KOSDAQ", "🇰🇷 코스닥"),
]
CSV_PATH = os.path.join("data", "seasonality_monthly.csv")

# 선거해에 해당하는 연차 (사이클 컬럼별)
ELECTION = {"사이클4": {4}, "사이클8": {4, 8}}


# ══════════════════════ 데이터 ══════════════════════
@st.cache_data(ttl="1h", show_spinner=False)
def load_seasonality():
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    for c in MONTHS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # 그 해 누적 수익률 = 존재하는 달만 복리로 곱함 (엑셀 '합계'와 동일)
    df["합계"] = df[MONTHS].add(1).prod(axis=1, min_count=1) - 1
    df["개월수"] = df[MONTHS].notna().sum(axis=1)
    return df


def _winrate(s):
    """승률 = 양수 개월 / (양수 + 음수). 빈칸과 정확히 0인 달은 양쪽에서 제외."""
    pos = int((s > 0).sum())
    neg = int((s < 0).sum())
    return pos / (pos + neg) if (pos + neg) else np.nan


def build_tables(df, cyc):
    g = df.groupby(cyc)
    avg = g[COLS].mean()
    med = g[COLS].median()
    win = g[COLS].agg(_winrate)
    n = g.size().rename("표본")
    for t in (avg, med, win):
        t.index = [f"{int(i)}년차" + (" 🗳" if int(i) in ELECTION[cyc] else "")
                   for i in t.index]
    n.index = avg.index
    return avg, med, win, n


# ══════════════════════ 스타일 ══════════════════════
def _sty_ret(v):
    if pd.isna(v):
        return ""
    return "color:#60A5FA; font-weight:700;" if v < -0.0001 else ""


def _sty_win(v):
    if pd.isna(v):
        return ""
    return "color:#F59E0B; font-weight:700;" if v < 0.4999 else ""


def show(table, fmt, styler):
    st.dataframe(
        table.style.map(styler).format(fmt, na_rep="-"),
        width="stretch",
    )


# ══════════════════════ 화면 ══════════════════════
if not os.path.exists(CSV_PATH):
    st.error(f"🚨 {CSV_PATH} 가 없습니다.")
    st.stop()

data = load_seasonality()

st.markdown(
    "<div class='strategy-desc'>지수별 <b>월간 수익률</b>을 대통령 임기 사이클 연차로 묶어 "
    "평균·중간값·승률을 봅니다. 🗳 표시는 선거해입니다.</div>",
    unsafe_allow_html=True,
)

tabs = st.tabs([label for _, label in INDEXES])

for tab, (code, label) in zip(tabs, INDEXES):
    with tab:
        df = data[data["지수"] == code].copy()
        if df.empty:
            st.warning(f"{label} 데이터가 없습니다.")
            continue

        c1, c2 = st.columns([1.4, 2.6], vertical_alignment="center")
        with c1:
            pick = st.radio(
                "주기", ["8년 주기", "4년 주기"],
                horizontal=True, key=f"cyc_{code}", label_visibility="collapsed",
            )
        cyc = "사이클8" if pick.startswith("8") else "사이클4"

        # 미완성 연도(12개월 미만)는 '합계'만 제외할지 선택
        partial = df[df["개월수"] < 12]["연도"].tolist()
        with c2:
            drop_partial = False
            if partial:
                drop_partial = st.checkbox(
                    f"미완성 연도({', '.join(str(y) for y in partial)}) 합계에서 제외",
                    key=f"dp_{code}",
                )

        view = df.copy()
        if drop_partial:
            view.loc[view["개월수"] < 12, "합계"] = np.nan

        y0, y1 = int(view["연도"].min()), int(view["연도"].max())
        avg, med, win, n = build_tables(view, cyc)

        st.markdown(
            f"<div class='sec-note'>{y0}~{y1} · {len(view)}개 연도 · "
            f"연차별 표본 {', '.join(f'{i}={v}' for i, v in n.items())}</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div class='sec-title'>■ 연차별 평균 수익률</div>", unsafe_allow_html=True)
        show(avg, "{:+.2%}", _sty_ret)

        st.markdown("<div class='sec-title'>■ 연차별 중간값</div>", unsafe_allow_html=True)
        show(med, "{:+.2%}", _sty_ret)

        st.markdown("<div class='sec-title'>■ 연차별 승률</div>", unsafe_allow_html=True)
        show(win, "{:.1%}", _sty_win)

        with st.expander(f"📋 {label} 연도별 원본 월수익률"):
            raw = view.set_index("연도")[[cyc] + COLS].copy()
            raw = raw.rename(columns={cyc: "연차"})
            st.dataframe(
                raw.style
                .map(lambda v: "background-color:#7f1d1d55;" if pd.notna(v) and v > 0.10 else "",
                     subset=COLS)
                .format({**{c: "{:+.2%}" for c in COLS}, "연차": "{:.0f}"}, na_rep=""),
                width="stretch",
                height=max(150, min(640, 38 + 35 * len(raw))),
            )

st.caption(
    "평균·중간값에서 파란 굵은 글씨는 -0.01% 미만, 승률에서 주황 굵은 글씨는 49.9% 미만입니다. "
    "승률은 양수 개월 ÷ (양수 + 음수) 개월이며 빈칸과 정확히 0%인 달은 승·패 양쪽에서 제외합니다. "
    "출처: 인베스팅닷컴 월간 종가 기준."
)
