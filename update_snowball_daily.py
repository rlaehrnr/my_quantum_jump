"""기존 스노우볼 로봇에서 호출하는 일봉 스냅샷 수집기."""
from zoneinfo import ZoneInfo

import pandas as pd

from utils.snowball_daily import SNAPSHOTS, read_snapshot


def update_daily_snapshot(market, tickers, fetchers):
    try:
        return _write_daily_snapshot(market, tickers, fetchers)
    except (OSError, ValueError) as exc:
        print(f"::warning::{market} 일봉 저장 실패 ({type(exc).__name__})")
        return False


def _write_daily_snapshot(market, tickers, fetchers):
    timezone, close_hour = {"US": ("America/New_York", 17), "KR": ("Asia/Seoul", 16)}[market]
    now = pd.Timestamp.now(tz=ZoneInfo(timezone)).tz_localize(None)
    cutoff = now.normalize() - pd.Timedelta(days=int(now.hour < close_hour))
    start = (now.to_period("M") - 1).start_time
    path = SNAPSHOTS[market]
    previous = read_snapshot(path).loc[start:cutoff]
    updated = {}
    for ticker in tickers:
        for fetch in fetchers:
            try:
                close = fetch(ticker, start.strftime("%Y-%m-%d"))
                if close is None or close.empty:
                    continue
                close = close.loc[start:cutoff].where(close.gt(0)).dropna().sort_index()
                if close.empty:
                    continue
                old = previous[ticker].dropna() if ticker in previous else pd.Series(dtype=float)
                if not old.empty and (close.index[-1] < old.index[-1] or close.index[0] > old.index[0]):
                    continue
                updated[ticker] = close
                break
            except Exception as exc:
                print(f"  일봉 {ticker} 수집 실패 ({type(exc).__name__})")

    if not updated:
        print(f"{market} 일봉 수집 실패. 기존 스냅샷 유지")
        return False
    missing = [ticker for ticker in tickers if ticker not in updated]
    if missing:
        print(f"::warning::{market} 일봉 미갱신: {', '.join(missing)}")
    data = pd.concat([pd.DataFrame(updated), previous.reindex(columns=missing)], axis=1)
    data = data.reindex(columns=tickers).sort_index().dropna(how="all")
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index_label="날짜", date_format="%Y-%m-%d", encoding="utf-8-sig")
    return True
