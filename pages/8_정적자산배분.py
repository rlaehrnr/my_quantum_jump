import json

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from utils.static_allocation import (
    MARKET_PLANS, SHEET_TABS, allocate, decimal_value, default_rows, plan_weights, read_settings,
    valid_ticker, write_settings,
)
from utils.static_allocation_quotes import FX_TICKER, fetch_quotes


WEIGHT = "목표 비중 (%)"
TARGET = "목표 금액 (원)"
SHARES = "매수 (주)"
PURCHASE = "매수 금액 (원)"
TICKER = "종목코드"
ROW_HEIGHT = 32
SEASONS = {"kr_winter": "11월–4월", "kr_summer": "5월–10월"}


def open_sheet():
    try:
        sheet_id = st.secrets.get("static_allocation_spreadsheet_id")
    except FileNotFoundError:
        return None
    if not sheet_id:
        return None
    credentials = Credentials.from_service_account_info(
        json.loads(st.secrets["google_credentials"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(credentials).open_by_key(sheet_id)


def session_settings():
    key = "static_allocation_settings"
    if key not in st.session_state:
        st.session_state[key] = {
            market: ((None, None, {p: default_rows(p) for p in plans}), None, None)
            for market, plans in MARKET_PLANS.items()
        }
        try:
            sheet = open_sheet()
        except Exception:
            sheet = None
            st.session_state[key] = {
                market: (settings, None, "Google Sheets 연결을 확인해 주세요.")
                for market, (settings, _, _) in st.session_state[key].items()
            }
        if sheet is not None:
            for market, plans in MARKET_PLANS.items():
                try:
                    worksheet = sheet.worksheet(SHEET_TABS[market])
                    st.session_state[key][market] = (read_settings(worksheet, plans), worksheet, None)
                except Exception:
                    defaults, _, _ = st.session_state[key][market]
                    st.session_state[key][market] = (
                        defaults, None, f"Google Sheets의 {SHEET_TABS[market]} 탭을 불러오지 못했습니다.",
                    )
    return st.session_state[key]


@st.cache_data(ttl=60, show_spinner=False)
def market_quotes(kr_tickers, us_tickers):
    return fetch_quotes(kr_tickers, us_tickers)


def quote_source(quote):
    if pd.isna(quote.timestamp):
        return quote.source
    if quote.source == "Yahoo 일봉":
        return f"{quote.source} {quote.timestamp:%m-%d}"
    timestamp = quote.timestamp
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("Asia/Seoul")
    return f"{quote.source} {timestamp:%m-%d %H:%M}"


def table_height(rows):
    return ROW_HEIGHT * (len(rows) + 1) + 3


def edit_plan(plan, rows, currency):
    manual_price = f"직접 입력 가격 ({currency})"
    frame = pd.DataFrame([{
        "ETF/전략": row["asset"].label,
        TICKER: row["ticker"],
        WEIGHT: row["weight"],
        manual_price: row["manual_price"],
    } for row in rows]).astype({WEIGHT: float, manual_price: float})
    edited = st.data_editor(
        frame, key=f"static_{plan}", width="stretch", hide_index=True,
        height=table_height(rows), row_height=ROW_HEIGHT, disabled=["ETF/전략"],
        column_config={
            "ETF/전략": st.column_config.TextColumn(width="large"),
            WEIGHT: st.column_config.NumberColumn(min_value=0.0, max_value=100.0, required=True),
            manual_price: st.column_config.NumberColumn(min_value=0.01, format="%.2f"),
        },
    )
    return [{
        "asset": row["asset"],
        "ticker": str(values[TICKER] or "").strip().upper() if row["asset"].ticker else "",
        "weight": None if pd.isna(values[WEIGHT]) else float(values[WEIGHT]),
        "manual_price": (
            float(values[manual_price])
            if row["asset"].ticker and pd.notna(values[manual_price]) else None
        ),
    } for row, values in zip(rows, edited.to_dict("records"))]


def show_plan(rows, budget, quotes, market, fx):
    currency = "USD" if market == "us" else "원"
    result = allocate(budget, rows, {code: quote.price for code, quote in quotes.items()}, fx)
    weights = plan_weights(rows)
    if weights is None or sum(weights) != 100:
        total = sum(weights) if weights else sum(row["weight"] or 0 for row in rows)
        st.warning(f"목표 비중 합계 {total:g}%. 비중을 모두 입력하고 합계를 100%로 맞춰 주세요.")
    total_name = f"현재가 ({currency})"
    table = []
    group_targets = {}
    for index, row in enumerate(rows):
        asset = row["asset"]
        quote = quotes.get(row["ticker"])
        price = row["manual_price"] or (quote.price if quote else None)
        source = "직접 입력" if row["manual_price"] else quote_source(quote) if quote else "미확인"
        if not asset.ticker:
            source = "계획 현금" if asset.group == "현금" else "별도 배정"
        order = result.lines[index] if result else None
        label = asset.label
        if asset.ticker and market == "us":
            label = row["ticker"]
        elif asset.ticker and row["ticker"] != asset.ticker:
            label = f"{asset.label} [{row['ticker']}]"
        record = {
            "자산군": asset.group,
            "ETF/전략": label,
            WEIGHT: row["weight"],
            total_name: price,
            TARGET: float(order.target) if order else None,
            SHARES: order.shares if order else None,
            PURCHASE: float(order.purchase) if order and order.purchase is not None else None,
        }
        if market == "us":
            record["매수 금액 (USD)"] = (
                float(order.purchase / decimal_value(fx)) if order and order.purchase is not None else None
            )
        record["시세 기준 (KST)"] = source
        table.append(record)
        group_targets[asset.group] = group_targets.get(asset.group, 0) + (row["weight"] or 0)
    won = st.column_config.NumberColumn(format="localized", step=1)
    st.dataframe(
        pd.DataFrame(table), width="stretch", hide_index=True,
        height=table_height(rows), row_height=ROW_HEIGHT,
        column_config={
            WEIGHT: st.column_config.NumberColumn(format="%.2f"),
            total_name: st.column_config.NumberColumn(format="%.2f") if market == "us" else won,
            TARGET: won,
            SHARES: st.column_config.NumberColumn(format="localized", step=1),
            PURCHASE: won,
            "매수 금액 (USD)": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.markdown(" · ".join(f"**{group}** {weight:g}%" for group, weight in group_targets.items()))
    if result:
        left, right = st.columns(2)
        left.metric("예상 매수 합계", f"{result.purchase_total:,.0f}원")
        right.metric("매수 후 남는 금액", f"{result.cash_remaining:,.0f}원")
        st.caption(
            f"계획 현금 {result.planned_cash:,.0f}원 · 정수 주 잔액 {result.lot_remainder:,.0f}원"
            f" · 시세·환율 대기 {result.pending:,.0f}원 · 별도 배정 {result.external:,.0f}원"
        )
    elif budget is None:
        st.caption("총 자산을 입력하면 목표 금액과 매수 가능 수량이 표시됩니다.")


def render_market(market, storage):
    (saved_budget, saved_fx, saved_plans), worksheet, error = storage
    if error:
        st.warning(error)
    budget = st.number_input(
        "총 자산 (원)", min_value=0, value=saved_budget, step=10_000,
        key=f"static_{market}_assets",
    )
    fx_override = None
    if market == "us":
        fx_display = st.empty()
        with st.expander("환율 직접 입력"):
            fx_override = st.number_input(
                "원/달러 환율 (1 USD당 원)", min_value=0.01, value=saved_fx, step=0.01,
                key="static_us_fx",
            )

    if market == "kr":
        slots = dict(zip(SEASONS, st.tabs(list(SEASONS.values()))))
    else:
        slots = {"us": st.container()}

    rows_by_plan = {}
    results = {}
    for plan, slot in slots.items():
        with slot:
            results[plan] = st.container()
            with st.expander("종목코드·비중·가격 수정"):
                rows_by_plan[plan] = edit_plan(plan, saved_plans[plan], "USD" if market == "us" else "원")

    if worksheet is not None and st.button("Google Sheets에 저장", key=f"static_save_{market}"):
        if any(sum(plan_weights(rows) or ()) != 100 for rows in rows_by_plan.values()):
            st.error("모든 배분표의 목표 비중을 100%로 맞춰 주세요.")
        elif any(
            not valid_ticker(row["ticker"], market)
            for rows in rows_by_plan.values() for row in rows if row["asset"].ticker
        ):
            st.error("종목코드 형식을 확인해 주세요.")
        else:
            try:
                write_settings(worksheet, budget, fx_override, rows_by_plan)
                st.success("저장했습니다. 다른 브라우저에서 페이지를 열면 이 설정을 불러옵니다.")
            except Exception:
                st.error("저장하지 못했습니다. 시트의 연결과 편집 권한을 확인해 주세요.")
    return budget, fx_override, rows_by_plan, results, fx_display if market == "us" else None


def main():
    st.set_page_config(page_title="정적자산배분", layout="wide")
    st.title("정적자산배분")
    st.caption("목표 금액 안에서 살 수 있는 정수 주를 계산합니다. 수수료와 환전 스프레드는 별도로 반영해야 합니다.")
    settings = session_settings()
    if all(worksheet is None and error is None for _, worksheet, error in settings.values()):
        st.caption("Google Sheets 미연결 · 입력은 현재 브라우저 세션에만 유지됩니다.")
    if st.button("시세 새로고침", key="static_refresh_quotes"):
        market_quotes.clear()

    kr, us = st.tabs(["한국", "미국"])
    markets = {}
    for market, tab in (("kr", kr), ("us", us)):
        with tab:
            markets[market] = render_market(market, settings[market])
    tickers = {
        market: tuple(sorted({
            row["ticker"] for rows in market_data[2].values() for row in rows
            if row["asset"].ticker and not row["manual_price"] and valid_ticker(row["ticker"], market)
        }))
        for market, market_data in markets.items()
    }
    quotes = market_quotes(tickers["kr"], tickers["us"])
    for market, (budget, fx_override, rows_by_plan, results, fx_display) in markets.items():
        fx = 1
        if market == "us":
            fx_quote = quotes.get(FX_TICKER)
            fx = fx_override or (fx_quote.price if fx_quote else None)
            source = "직접 입력" if fx_override else (quote_source(fx_quote) if fx_quote else "")
            if fx is None:
                fx_display.warning("원/달러 환율을 확인하지 못했습니다. 환율을 직접 입력해 주세요.")
            else:
                fx_display.caption(f"원/달러 환율 {fx:,.2f}원 · {source}")
        for plan, container in results.items():
            with container:
                show_plan(rows_by_plan[plan], budget, quotes, market, fx)


if __name__ == "__main__":
    main()
