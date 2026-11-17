import json

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from utils.static_allocation import (
    MARKET_PLANS, PLAN_VERSION, SHEET_TABS, allocate, decimal_value, default_rows, plan_weights, read_settings,
    valid_ticker, write_settings,
)
from utils.static_allocation_quotes import FX_TICKER, fetch_quotes


WEIGHT = "목표 비중 (%)"
SHARES = "매수 (주)"
TICKER = "종목코드"
ROW_HEIGHT = 32
SEASONS = ("11월–4월", "5월–10월")


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
    key = f"static_allocation_settings_{PLAN_VERSION}"
    if key not in st.session_state:
        st.session_state[key] = {
            market: ((None, None, None, {p: default_rows(p) for p in plans}), None, None)
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


def quote_time(quote):
    if pd.isna(quote.timestamp):
        return ""
    if quote.source == "Yahoo 일봉":
        return f"{quote.timestamp:%m-%d}"
    timestamp = quote.timestamp
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("Asia/Seoul")
    return f"{timestamp:%m-%d %H:%M}"


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


def show_plan(rows, budget, quotes, market):
    currency = "USD" if market == "us" else "원"
    result = allocate(budget, rows, {code: quote.price for code, quote in quotes.items()})
    weights = plan_weights(rows)
    if weights is None or sum(weights) != 100:
        total = sum(weights) if weights else sum(row["weight"] or 0 for row in rows)
        st.warning(f"목표 비중 합계 {total:g}%. 비중을 모두 입력하고 합계를 100%로 맞춰 주세요.")
    price_column = f"현재가 ({currency})"
    target_column = f"목표 금액 ({currency})"
    purchase_column = "매수·배정 금액 (USD)" if market == "us" else "매수 금액 (원)"
    table = []
    group_targets = {}
    for index, row in enumerate(rows):
        asset = row["asset"]
        quote = quotes.get(row["ticker"])
        price = row["manual_price"] or (quote.price if quote else None)
        order = result.lines[index] if result else None
        record = {"자산군": asset.group}
        if market == "us":
            record["투자 대상"] = asset.label.split(" (", 1)[0]
            record["ETF"] = row["ticker"]
        else:
            record["ETF/전략"] = (
                f"{asset.label} [{row['ticker']}]"
                if asset.ticker and row["ticker"] != asset.ticker else asset.label
            )
        record.update({
            WEIGHT: row["weight"],
            price_column: price,
            target_column: float(order.target) if order else None,
            SHARES: order.shares if order else None,
            purchase_column: float(order.purchase) if order and order.purchase is not None else None,
            "기준 시각 (KST)": quote_time(quote) if quote and not row["manual_price"] else "",
        })
        table.append(record)
        group_targets[asset.group] = group_targets.get(asset.group, 0) + (row["weight"] or 0)
    money_column = (
        st.column_config.NumberColumn(format="%.2f") if market == "us"
        else st.column_config.NumberColumn(format="localized", step=1)
    )
    st.dataframe(
        pd.DataFrame(table), width="stretch", hide_index=True,
        height=table_height(rows), row_height=ROW_HEIGHT,
        column_config={
            WEIGHT: st.column_config.NumberColumn(format="%.2f"),
            price_column: money_column,
            target_column: money_column,
            SHARES: st.column_config.NumberColumn(format="localized", step=1),
            purchase_column: money_column,
        },
    )
    st.markdown(" · ".join(f"**{group}** {weight:g}%" for group, weight in group_targets.items()))
    if result:
        left, right = st.columns(2)
        def amount(value):
            return f"{value:,.2f} USD" if market == "us" else f"{value:,.0f}원"

        left.metric("예상 매수·배정 합계" if market == "us" else "예상 매수 합계", amount(result.purchase_total))
        right.metric("남는 금액", amount(result.cash_remaining))
        st.caption(
            f"계획 현금 {amount(result.planned_cash)} · 정수 주 잔액 {amount(result.lot_remainder)}"
            f" · 시세 대기 {amount(result.pending)}"
        )
    elif budget is None:
        st.caption("총 자산을 입력하면 목표 금액과 매수 가능 수량이 표시됩니다.")


USD_INPUT = "static_us_dollars"
KRW_INPUT = "static_us_won"
CURRENCY_SOURCE = "static_us_currency_source"


def set_currency_source(key):
    st.session_state[CURRENCY_SOURCE] = key


def render_us_budget(saved_budget, saved_currency, fx_override):
    left, center, right = st.columns(3, vertical_alignment="center")
    quote = market_quotes((), (FX_TICKER,)).get(FX_TICKER) if fx_override is None else None
    rate = decimal_value(fx_override if fx_override is not None else (quote.price if quote else None))
    rate_label = f"원/달러 환율 {rate:,.2f}원" if rate is not None else "원/달러 환율 미확인"
    time = quote_time(quote) if quote else ""
    center.markdown(
        '<div style="text-align:center">'
        f"<strong>{rate_label}</strong>"
        '<div role="img" aria-label="달러와 원화 양방향 환산" '
        'style="font-size:1.75rem;line-height:1.15">⇄</div>'
        + (f"<small>{time} KST</small>" if time else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    if CURRENCY_SOURCE not in st.session_state:
        initial_key = KRW_INPUT if saved_currency == "원" else USD_INPUT
        st.session_state[CURRENCY_SOURCE] = initial_key
        st.session_state.setdefault(initial_key, saved_budget)

    source = st.session_state[CURRENCY_SOURCE]
    amount = decimal_value(st.session_state[source])
    if source == KRW_INPUT:
        st.session_state[USD_INPUT] = (
            float(round(amount / rate, 2)) if amount is not None and rate else None
        )
    else:
        st.session_state[KRW_INPUT] = (
            int(round(amount * rate)) if amount is not None and rate else None
        )

    dollars = left.number_input(
        "총 자산 (USD)", min_value=0.0, value=None, step=10.0, format="%.2f",
        key=USD_INPUT, on_change=set_currency_source, args=(USD_INPUT,),
    )
    won = right.number_input(
        "총 자산 (원)", min_value=0, value=None, step=10_000,
        key=KRW_INPUT, on_change=set_currency_source, args=(KRW_INPUT,),
    )
    if source == KRW_INPUT:
        return dollars, won, "원"
    return dollars, dollars, "USD"

def render_market(market, storage, fx_override=None):
    (saved_budget, saved_currency, _, saved_plans), worksheet, error = storage
    if error:
        st.warning(error)
    if market == "kr":
        manwon = st.number_input(
            "총 자산 (만원)", min_value=0,
            value=None if saved_budget is None else (saved_budget + 5_000) // 10_000,
            step=1, format="%d", key="static_kr_manwon_integer",
            help="예: 1,500만원은 1500으로 입력하세요.",
        )
        budget = None if manwon is None else manwon * 10_000
        saved_amount, currency = budget, "원"
    else:
        budget, saved_amount, currency = render_us_budget(saved_budget, saved_currency, fx_override)
    slots = dict(zip(MARKET_PLANS[market], st.tabs(SEASONS)))
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
                write_settings(worksheet, saved_amount, fx_override, rows_by_plan, currency=currency)
                st.success("저장했습니다. 다른 브라우저에서 페이지를 열면 이 설정을 불러옵니다.")
            except Exception:
                st.error("저장하지 못했습니다. 시트의 연결과 편집 권한을 확인해 주세요.")
    return budget, rows_by_plan, results


def main():
    st.set_page_config(page_title="정적자산배분", layout="wide")
    st.title("정적자산배분")
    st.caption("목표 금액 안에서 살 수 있는 정수 주를 계산합니다. 수수료와 환전 스프레드는 별도로 반영해야 합니다.")
    settings = session_settings()
    if all(worksheet is None and error is None for _, worksheet, error in settings.values()):
        st.caption("Google Sheets 미연결 · 입력은 현재 브라우저 세션에만 유지됩니다.")
    refresh, tools = st.columns(2)
    if refresh.button("시세 새로고침", key="static_refresh_quotes"):
        market_quotes.clear()
    (_, _, saved_fx, _), _, _ = settings["us"]
    with tools.container(horizontal=True, horizontal_alignment="right"):
        with st.popover("환율 설정", icon=":material/tune:", type="tertiary"):
            fx_override = st.number_input(
                "환율 직접 입력", min_value=0.01, value=saved_fx, step=0.01,
                format="%.2f", key="static_us_fx", help="비워두면 미국 탭에 자동 환율을 적용합니다.",
            )
    kr, us = st.tabs(["한국", "미국"])
    markets = {}
    for market, tab in (("kr", kr), ("us", us)):
        with tab:
            markets[market] = render_market(market, settings[market], fx_override if market == "us" else None)
    tickers = {
        market: tuple(sorted({
            row["ticker"] for rows in market_data[1].values() for row in rows
            if row["asset"].ticker and not row["manual_price"] and valid_ticker(row["ticker"], market)
        }))
        for market, market_data in markets.items()
    }
    quotes = market_quotes(tickers["kr"], tickers["us"])
    for market, (budget, rows_by_plan, results) in markets.items():
        for plan, container in results.items():
            with container:
                show_plan(rows_by_plan[plan], budget, quotes, market)


if __name__ == "__main__":
    main()
