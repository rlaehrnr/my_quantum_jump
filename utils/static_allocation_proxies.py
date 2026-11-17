import pandas as pd

from utils.static_allocation_history import load_price_history
from utils.static_allocation_quotes import FX_TICKER


# 미국 상장 대체 ETF는 미국의 직전 종가를 원화로 환산한다.
KOREAN_PROXIES = {
    "218420": ("us", "XLE", "미국 S&P 500 에너지"),
    "0127M0": ("us", "VTV", "미국 대형 가치주"),
    "379810": ("us", "QQQ", "나스닥100"),
    "283580": ("us", "ASHR", "중국 CSI 300"),
    "371160": ("us", "KWEB", "중국 인터넷주 · 항셍테크 대용"),
    "372330": ("us", "KWEB", "중국 인터넷주 · 항셍테크 대용"),
    "453870": ("us", "INDY", "인도 Nifty 50"),
    "385560": ("kr", "148070", "KIWOOM 국고채10년 · 30년 Enhanced 대용"),
    "476760": ("us", "TLT", "미국 장기 국채"),
    "464470": ("us", "TLT", "미국 장기 국채"),
    "411060": ("us", "GLD", "금 현물 · KRX 금 프리미엄 미반영"),
    "0189B0": ("us", "SLV", "은 현물"),
}


def load_proxy_prices(tickers, cutoff):
    sources = {"kr": set(), "us": set()}
    for ticker in set(tickers).intersection(KOREAN_PROXIES):
        market, symbol, _ = KOREAN_PROXIES[ticker]
        sources[market].add(symbol)
    if sources["us"]:
        sources["us"].add(FX_TICKER)
    return tuple(
        load_price_history(market, tuple(sorted(sources[market])), cutoff, adjusted=False)
        if sources[market] else pd.DataFrame()
        for market in ("us", "kr")
    )


def prior_foreign_close(series, sessions):
    observed = series.dropna().sort_index()
    aligned = observed.reindex(
        sessions - pd.Timedelta(days=1), method="ffill", tolerance=pd.Timedelta(days=7),
    )
    return pd.Series(aligned.to_numpy(), index=sessions)


def extend_korean_prices(actual, sessions, foreign, domestic, tickers):
    """대체 수익률을 첫 실제 종가에 연결하며 상장 이후 공란은 남긴다."""
    result = actual.reindex(sessions).copy()
    fx = prior_foreign_close(foreign[FX_TICKER], sessions) if FX_TICKER in foreign else None
    for ticker in sorted(set(tickers).intersection(KOREAN_PROXIES)):
        if ticker not in result:
            continue
        listing = result[ticker].first_valid_index()
        if listing is None:
            continue
        market, symbol, _ = KOREAN_PROXIES[ticker]
        if market == "us" and symbol in foreign and fx is not None:
            proxy = prior_foreign_close(foreign[symbol], sessions) * fx
        elif market == "kr" and symbol in domestic:
            proxy = domestic[symbol].reindex(sessions)
        else:
            continue
        anchor = proxy.loc[listing]
        if pd.notna(anchor) and anchor > 0:
            earlier = sessions < listing
            result.loc[earlier, ticker] = proxy.loc[earlier] * (result.loc[listing, ticker] / anchor)
    return result
