import math

import pandas as pd
import streamlit as st


# 엑셀의 ETF별 비중을 사용한다. 한국 5~10월 원본은 합계 105%다.
KR_WINTER = [
    ("선진국 주식", "한국 주식", "KODEX 200", 15),
    ("선진국 주식", "미국 가치주", "KODEX 미국S&P500에너지(합성)", 3),
    ("선진국 주식", "미국 가치주", "ACE 미국대형가치주", 4),
    ("선진국 주식", "미국 성장주", "KODEX 미국나스닥 100", 8),
    ("개도국 주식", "중국 주식", "KODEX 차이나 CSI 300", 10),
    ("개도국 주식", "중국 주식", "TIGER 차이나항셍테크", 5),
    ("개도국 주식", "인도 주식", "TIGER 인도니프티50", 5),
    ("채권", "한국 채권", "RISE KIS 국고채 30년 Enhanced", 12.5),
    ("채권", "미국 채권", "ACE 미국 30년 국채액티브", 12.5),
    ("실물자산", "금", "ACE KRX금현물 (금프 없으면)", 15),
    ("실물자산", "은", "TIGER 은액티브", 5),
    ("실물자산", "구리", "TIGER 구리실물", 5),
]
KR_SUMMER = [
    ("선진국 주식", "한국 주식", "KODEX 200", 10),
    ("선진국 주식", "미국 가치주", "KODEX 미국S&P500에너지(합성)", 3),
    ("선진국 주식", "미국 가치주", "ACE 미국대형가치주", 4),
    ("선진국 주식", "미국 성장주", "KODEX 미국나스닥 100", 8),
    ("개도국 주식", "중국 주식", "KODEX 차이나 CSI 300", 5),
    ("개도국 주식", "중국 주식", "KODEX 차이나항셍테크", 2),
    ("개도국 주식", "인도 주식", "TIGER 인도니프티50", 3),
    ("채권", "한국 채권", "RISE KIS 국고채 30년 Enhanced", 7.5),
    ("채권", "미국 채권", "PLUS 미국채 30년 액티브", 7.5),
    ("실물자산", "금", "ACE KRX금현물 (금프 없으면)", 10),
    ("실물자산", "은", "TIGER 은액티브", 3),
    ("실물자산", "구리", "TIGER 구리실물", 2),
    ("현금", "현금", "", 40),
]
US_ALL_WEATHER = [
    ("선진국 주식", "한국 주식", "EWY / FLKR", 10),
    ("선진국 주식", "미국 가치주", "XLE", 3),
    ("선진국 주식", "미국 성장주", "QQQ / QQQM", 9),
    ("선진국 주식", "미국 배당주", "SCHD", 4),
    ("선진국 주식", "폴란드 주식", "EPOL", 4),
    ("개도국 주식", "중국 주식", "ASHR", 7),
    ("개도국 주식", "중국 주식", "FXI", 3),
    ("개도국 주식", "칠레 주식", "ECH", 3),
    ("개도국 주식", "브라질 주식", "EWZ / FLBR", 4),
    ("개도국 주식", "인도네시아 주식", "EIDO", 3),
    ("채권", "미국 채권", "TLT / VGLT", 15),
    ("채권", "GRVT", "GRVT", 10),
    ("실물자산", "금", "GLD / GLDM", 12),
    ("실물자산", "은", "SLV / SIVR", 4),
    ("실물자산", "구리", "COPX", 4),
    ("실물자산", "종합원자재", "PDBC", 5),
]

WEIGHT = "목표 비중 (%)"
AMOUNT_KRW = "목표 금액 (원)"
AMOUNT_USD = "목표 금액 (USD)"
QUANTITY = "목표 수량 (주)"


def budget_inputs(market):
    assets = st.number_input(
        "총 자산 (원)", min_value=0, value=None, step=10_000,
        key=f"{market}_assets",
    )
    allocation = st.number_input(
        "정적 배분 비율 (%)", min_value=0.0, max_value=100.0, value=100.0,
        step=1.0, key=f"{market}_allocation",
    )
    return None if assets is None else assets * allocation / 100


def render_allocation(rows, budget, key, currency, fx=None):
    price = f"가격 ({currency})"
    holdings = pd.DataFrame(rows, columns=["자산군", "자산", "ETF/전략", WEIGHT])
    holdings[WEIGHT] = holdings[WEIGHT].astype(float)
    holdings[price] = float("nan")
    edited = st.data_editor(
        holdings, key=key, width="stretch", hide_index=True,
        disabled=["자산군", "자산"],
        column_config={
            "ETF/전략": st.column_config.TextColumn(width="large"),
            WEIGHT: st.column_config.NumberColumn(
                min_value=0.0, max_value=100.0, format="%.2f", required=True,
            ),
            price: st.column_config.NumberColumn(
                min_value=0.0, format="localized" if currency == "원" else "%.2f",
            ),
        },
    )
    weights = edited[WEIGHT]
    total_weight = weights.sum()
    if weights.isna().any() or not math.isclose(total_weight, 100, abs_tol=1e-8):
        st.warning(f"목표 비중 합계가 {total_weight:g}%입니다. 모든 비중을 입력하고 합계를 100%로 맞춰 주세요.")
        return
    if budget is None:
        st.caption("총 자산을 입력하면 목표 금액이 표시됩니다.")
        return

    st.subheader("목표 배분")
    st.caption(f"정적 배분 금액 {budget:,.0f}원 · 수량은 소수점 기준")
    result = edited[["자산", "ETF/전략"]].copy()
    result[AMOUNT_KRW] = budget * weights / 100
    quantity_amount = result[AMOUNT_KRW]
    if currency == "USD":
        result[AMOUNT_USD] = result[AMOUNT_KRW] / fx if fx else float("nan")
        quantity_amount = result[AMOUNT_USD]
        if fx is None:
            st.caption("환율을 입력하면 달러 목표 금액과 수량을 계산합니다.")
    unit_prices = edited[price].where(edited[price].gt(0) & edited["자산군"].ne("현금"))
    result[QUANTITY] = quantity_amount / unit_prices
    st.dataframe(
        result, width="stretch", hide_index=True,
        column_config={
            "ETF/전략": st.column_config.TextColumn(width="large"),
            AMOUNT_KRW: st.column_config.NumberColumn(format="localized", step=1),
            AMOUNT_USD: st.column_config.NumberColumn(format="%.2f"),
            QUANTITY: st.column_config.NumberColumn(format="%.4f"),
        },
    )


st.set_page_config(page_title="정적자산배분", layout="wide")
st.title("정적자산배분")
st.caption("목표 비중과 가격을 표에서 수정하세요. 가격을 입력한 종목의 목표 수량을 계산합니다.")

korea, usa = st.tabs(["한국", "미국"])
with korea:
    kr_budget = budget_inputs("kr")
    winter, summer = st.tabs(["11월–4월", "5월–10월"])
    with winter:
        render_allocation(KR_WINTER, kr_budget, "kr_winter", "원")
    with summer:
        render_allocation(KR_SUMMER, kr_budget, "kr_summer", "원")
with usa:
    us_budget = budget_inputs("us")
    fx = st.number_input(
        "원/달러 환율 (1 USD당 원)", min_value=0.01, value=None, step=0.01,
        key="us_fx",
    )
    render_allocation(US_ALL_WEATHER, us_budget, "us_all_weather", "USD", fx)
