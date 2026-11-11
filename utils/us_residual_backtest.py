"""USA500 잔차 백테스트의 종목 선택과 월별 비중 계산."""

import pandas as pd

from utils.us_helpers import get_triple_momentum_us


STRATEGY_NAMES = ("기존 전략", "잔차 전략", "기존 50% + 잔차 50%")


def run_residual_backtest(
    master, scores, invested, *, universe, cutoff, original_ranks, residual_ranks, fee
):
    """세 전략을 같은 달에 운용하며, 비중 차이의 매수·매도액에 편도 비용을 적용한다."""
    months = invested.index
    gross = pd.DataFrame(0.0, index=months, columns=STRATEGY_NAMES)
    net = gross.copy()
    previous_weights = {name: pd.Series(dtype=float) for name in STRATEGY_NAMES}
    cash = pd.Series(dtype=float)
    master_by_month = master.groupby("투자월")
    scores_by_month = scores.groupby("month")

    for month, active in invested.items():
        stocks = master_by_month.get_group(month).sort_values("시가총액", ascending=False).head(universe)
        returns = stocks.set_index("종목코드")["이번달수익률"] / 100
        targets = (cash, cash, cash)
        if active:
            original = get_triple_momentum_us(stocks, cutoff=cutoff, mode="rank")
            a, b = original_ranks
            original_tickers = original.iloc[a - 1:b]["종목코드"]
            ranked = scores_by_month.get_group(month)
            ranked = ranked.loc[ranked.ticker.isin(returns.index)].sort_values(
                ["score", "ticker"], ascending=[False, True]
            )
            a, b = residual_ranks
            residual_tickers = ranked.iloc[a - 1:b].ticker
            original_weights = pd.Series(1 / len(original_tickers), index=original_tickers) if len(original_tickers) else cash
            residual_weights = pd.Series(1 / len(residual_tickers), index=residual_tickers) if len(residual_tickers) else cash
            targets = (original_weights, residual_weights, original_weights.add(residual_weights, fill_value=0) / 2)

        for name, target in zip(STRATEGY_NAMES, targets):
            realized = returns.reindex(target.index)
            growth = 1 + float(target @ realized)
            traded = float(target.subtract(previous_weights[name], fill_value=0).abs().sum())
            gross.loc[month, name] = growth - 1
            net.loc[month, name] = (1 - fee * traded) * growth - 1
            previous_weights[name] = target * (1 + realized) / growth if growth > 0 else cash

    return {"gross": gross, "net": net}
