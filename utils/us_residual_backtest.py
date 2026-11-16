"""USA500 잔차 백테스트의 종목 선택과 월별 비중 계산."""

import numpy as np
import pandas as pd

from utils.us_helpers import get_triple_momentum_us


STRATEGY_NAMES = ("기존 전략", "잔차 전략", "기존 50% + 잔차 50%", "종목 균등 배분")
RESIDUAL_DEFAULT_RANKS = (1, 9)


def calculate_residual_scores(month, archive, supplemental, factors):
    """투자월 두 달 전까지 36개월 회귀, 마지막 11개월 잔차 평균/표준편차."""
    window = pd.period_range(end=month - 2, periods=36, freq="M")
    ff3 = factors.reindex(window).to_numpy()
    if not np.isfinite(ff3).all():
        return pd.Series(dtype=float)

    returns = archive.reindex(window).to_numpy(copy=True)
    alternate = supplemental.reindex(index=window, columns=archive.columns).to_numpy()
    complete = np.isfinite(returns).all(axis=0)
    for col in np.flatnonzero(~complete & np.isfinite(alternate).all(axis=0)):
        overlap = np.isfinite(returns[:, col])
        if overlap.sum() >= 12:
            difference = np.abs(returns[overlap, col] - alternate[overlap, col])
            if np.median(difference) <= 0.001 and np.quantile(difference, 0.95) <= 0.01:
                returns[:, col] = alternate[:, col]
                complete[col] = True

    x = np.column_stack([np.ones(36), ff3[:, :3]])
    excess = returns[:, complete] - ff3[:, 3, None]
    residual = (excess - x @ (np.linalg.pinv(x) @ excess))[-11:]
    deviation = residual.std(axis=0, ddof=1)
    valid = deviation > 1e-10
    values = residual[:, valid].mean(axis=0) / deviation[valid]
    return pd.Series(values, index=archive.columns[complete][valid], dtype=float)


def run_residual_backtest(
    master, scores, invested, *, universe, cutoff, original_ranks, residual_ranks, fee
):
    """같은 달에 전략을 비교하고 목표비중까지의 매수·매도액에 편도 비용을 적용한다."""
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
        targets = (cash,) * len(STRATEGY_NAMES)
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
            combined = original_weights.add(residual_weights, fill_value=0)
            unique_tickers = combined.index
            equal_weights = pd.Series(1 / len(unique_tickers), index=unique_tickers) if len(unique_tickers) else cash
            targets = (original_weights, residual_weights, combined / 2, equal_weights)

        for name, target in zip(STRATEGY_NAMES, targets):
            realized = returns.reindex(target.index)
            growth = 1 + float(target @ realized)
            traded = float(target.subtract(previous_weights[name], fill_value=0).abs().sum())
            gross.loc[month, name] = growth - 1
            net.loc[month, name] = (1 - fee * traded) * growth - 1
            previous_weights[name] = target * (1 + realized) / growth if growth > 0 else cash

    return {"gross": gross, "net": net}
