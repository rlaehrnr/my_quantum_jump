from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pandas as pd
import requests
import yfinance as yf

from utils.static_allocation import decimal_value


FX_TICKER = "KRW=X"
NAVER_STOCKS = "https://polling.finance.naver.com/api/realtime/domestic/stock/"


@dataclass(frozen=True)
class Quote:
    price: float
    timestamp: pd.Timestamp | None
    source: str


def naver_quotes(tickers):
    if not tickers:
        return {}
    response = requests.get(NAVER_STOCKS + ",".join(tickers), timeout=5)
    response.raise_for_status()
    quotes = {}
    for row in response.json().get("datas", []):
        ticker = row.get("itemCode")
        price = decimal_value(str(row.get("closePrice", "")).replace(",", ""))
        raw_time = row.get("localTradedAt")
        timestamp = pd.to_datetime(raw_time, errors="coerce") if raw_time else None
        if ticker in tickers and price is not None and price > 0:
            source = "네이버 현재가" if row.get("marketStatus") == "OPEN" else "네이버 최근가"
            quotes[ticker] = Quote(float(price), timestamp, source)
    return quotes


def yahoo_quote(symbol):
    ticker = yf.Ticker(symbol)
    for period, interval, label in (("5d", "1m", "1분봉"), ("5d", "1d", "일봉")):
        try:
            history = ticker.history(period=period, interval=interval, auto_adjust=False, timeout=5)
            if history.empty or "Close" not in history:
                continue
            closes = history["Close"].dropna()
            if not closes.empty:
                price = decimal_value(closes.iloc[-1])
                if price is not None and price > 0:
                    unit_digits = 0 if symbol.endswith(".KS") else 2
                    return Quote(round(float(price), unit_digits), closes.index[-1], f"Yahoo {label}")
        except Exception:
            continue
    return None


def fetch_quotes(kr_tickers, us_tickers):
    try:
        quotes = naver_quotes(kr_tickers)
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        quotes = {}
    yahoo_codes = {code: code + ".KS" for code in kr_tickers if code not in quotes}
    yahoo_codes.update({code: code for code in (*us_tickers, FX_TICKER)})
    with ThreadPoolExecutor(max_workers=8) as pool:
        for code, quote in zip(yahoo_codes, pool.map(yahoo_quote, yahoo_codes.values())):
            if quote is not None:
                quotes[code] = quote
    return quotes
