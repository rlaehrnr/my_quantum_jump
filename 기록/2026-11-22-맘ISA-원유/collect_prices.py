from datetime import date
from pathlib import Path
import sys

import pandas as pd

from utils import snowball as sb
from utils.static_allocation import KR_SUMMER, KR_WINTER, US_SUMMER, US_WINTER
from utils.static_allocation_history import load_price_history
from utils.static_allocation_quotes import FX_TICKER

market = sys.argv[1]
plans = (KR_SUMMER, KR_WINTER) if market == "kr" else (US_SUMMER, US_WINTER)
codes = {asset.ticker for plan in plans for asset in plan if asset.ticker}
if market == "kr":
    codes.update(sb.PEN_ALL)
    codes.update(("144600", "137610", "148070", "130730", "469830", "130680"))
else:
    codes.update((FX_TICKER, "VTV"))
prices = load_price_history(market, tuple(codes), date(2026, 11, 20) if market == "kr" else date(2026, 10, 31), adjusted=market == "us")
print(prices.count().to_string())
if prices.empty:
    raise RuntimeError(f"No {market} prices")
prices.to_csv(Path(f"research_daily_{market}.csv"), index_label="date")
print(pd.DataFrame({"start": prices.apply(pd.Series.first_valid_index),
                    "end": prices.apply(pd.Series.last_valid_index)}).to_string())
