"""제한 공유 구글 시트의 3전략 입력과 수익률."""
import hmac
import json

import pandas as pd
import streamlit as st
from gspread.utils import ValueRenderOption

from utils.three_strategy import LEGS, month_key, parse_history, validate_amounts


# 기존 소형주 포트와 동일한 제한 공유 문서. 탭만 분리한다.
PORTFOLIO_SHEET_URL = "https://docs.google.com/spreadsheets/d/1XTroUdH7iKN40dQSrSjz3nsZ1l1k2mr5skXSzlEfl7Y/edit"
AMOUNT_TAB = "투자배분"
HISTORY_TAB = "3전략 월수익률"
KEY_CELL = "B1"
FIRST_MONTH = pd.Period("2026-11", freq="M")
MAX_ROW = 1000


@st.cache_resource(show_spinner=False)
def portfolio_client():
    import gspread
    from google.oauth2.service_account import Credentials

    secret = st.secrets["google_credentials"]
    config = json.loads(secret) if isinstance(secret, str) else dict(secret)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    client = gspread.authorize(Credentials.from_service_account_info(config, scopes=scopes))
    client.set_timeout((5, 12))
    return client


@st.cache_resource(show_spinner=False, ttl=900)
def portfolio_sheet():
    return portfolio_client().open_by_url(PORTFOLIO_SHEET_URL)


def check_access(code):
    if not isinstance(code, str) or len(code.strip()) != 48:
        return False
    expected = portfolio_sheet().worksheet(AMOUNT_TAB).acell(KEY_CELL).value
    return bool(expected and len(expected) == 48
                and hmac.compare_digest(str(expected).encode(), code.strip().encode()))


def allocation_row(month):
    row = pd.Period(month_key(month), freq="M").ordinal - FIRST_MONTH.ordinal + 4
    if not 4 <= row <= MAX_ROW:
        raise ValueError(f"투자금 입력은 {FIRST_MONTH}부터 지원합니다.")
    return row


def _amount_row(sheet, month):
    row = allocation_row(month)
    address = f"A{row}:G{row}"
    rows = sheet.get(address, value_render_option=ValueRenderOption.unformatted)
    cells = (list(rows[0]) + [""]*7)[:7] if rows else [""]*7
    if cells[0] and str(cells[0]).strip() != month:
        raise ValueError("시트의 투자월과 입력 대상 행이 다릅니다. 투자월 표기를 확인하세요.")
    return address, cells[1:]


def read_amounts(sheet, month):
    _, cells = _amount_row(sheet, month)
    empty = [v is None or str(v).strip() == "" for v in cells]
    if all(empty):
        return None
    if any(empty):
        raise ValueError("투자배분 탭의 여섯 금액 칸을 모두 채워주세요. 미투자 전략은 0입니다.")
    return validate_amounts(dict(zip(LEGS, cells)))


def save_amounts(sheet, month, amounts):
    checked = validate_amounts(amounts)
    address, _ = _amount_row(sheet, month)
    sheet.update(range_name=address, values=[[month, *checked.values()]], raw=True)


@st.cache_data(show_spinner=False, ttl=90)
def load_history():
    tab = portfolio_sheet().worksheet(HISTORY_TAB)
    return parse_history(tab.get("A3:G1500", value_render_option=ValueRenderOption.unformatted))
