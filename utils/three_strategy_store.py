"""제한 공유 구글 시트의 연결과 월 수익률 원장 조회."""
import json

import pandas as pd
import streamlit as st
from gspread.utils import ValueRenderOption

from utils.data_loader import normalize_stock_code
from utils.three_strategy import parse_history


# 기존 소형주 포트와 동일한 제한 공유 문서. 탭만 분리한다.
PORTFOLIO_SHEET_URL = "https://docs.google.com/spreadsheets/d/1XTroUdH7iKN40dQSrSjz3nsZ1l1k2mr5skXSzlEfl7Y/edit"
HISTORY_TAB = "3전략 월수익률"
POSITION_COLUMNS = ["종목명", "종목코드", "매수단가", "수량"]
SMALLCAP_ACCOUNTS = {"ddo": "또", "sso": "쏘", "mom": "맘"}


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


@st.cache_data(show_spinner=False, ttl=90)
def load_history():
    tab = portfolio_sheet().worksheet(HISTORY_TAB)
    return parse_history(tab.get("A3:G1500", value_render_option=ValueRenderOption.unformatted))


def read_positions(sheet, name):
    rows = sheet.worksheet(name).get_all_values()
    if not rows:
        return pd.DataFrame(columns=POSITION_COLUMNS)
    positions = pd.DataFrame(rows[1:], columns=rows[0])
    positions.columns = positions.columns.str.strip()
    positions["종목코드"] = positions["종목코드"].apply(normalize_stock_code)
    positions = positions.loc[positions["종목코드"].ne("")].reindex(columns=POSITION_COLUMNS)
    positions["종목명"] = positions["종목명"].fillna("")
    for column in ("매수단가", "수량"):
        clean = positions[column].astype(str).str.replace(r"[^0-9.-]", "", regex=True)
        positions[column] = pd.to_numeric(clean, errors="coerce").fillna(0).astype(int)
    return positions


@st.cache_data(show_spinner=False, ttl=90)
def smallcap_positions():
    sheet = portfolio_sheet()
    frames, unread = [], []
    for tab, name in SMALLCAP_ACCOUNTS.items():
        try:
            frames.append(read_positions(sheet, tab).assign(계좌=name))
        except Exception:
            unread.append(name)
    if not frames:
        return pd.DataFrame(columns=[*POSITION_COLUMNS, "계좌"]), unread
    return pd.concat(frames, ignore_index=True), unread
