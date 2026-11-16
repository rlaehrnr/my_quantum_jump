"""Compare the USA500 residual formation window using frozen November 10 inputs."""

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from usa500_filter_review_20261110 import metrics, simulate
from usa500_residual_review_20261110 import parse_factors


CASE = "supplemented_lag1"
PERIODS = (
    ("all", "2000-02", "2026-10"),
    ("2000–2009", "2000-02", "2009-12"),
    ("2010–2019", "2010-01", "2019-12"),
    ("2020–2026", "2020-01", "2026-10"),
)
WINDOWS = {"skip1": slice(None, -1), "include_11m": slice(1, None), "include_12m": slice(None)}


def run(snapshot, source):
    assert (snapshot / "commit.txt").read_text().strip() == "1608859432d90fb7bc5cdf149cfbfa1f5bc24fe1"
    sys.path.insert(0, str(snapshot))
    os.chdir(snapshot)
    from utils.data_loader import load_archive_data
    from utils.us_helpers import preprocess_us_data

    raw = load_archive_data.__wrapped__("archive_usa", None)
    master = preprocess_us_data(raw, is_daily=False)
    history = raw.assign(
        month=pd.to_datetime(raw["종목선정일"]).dt.to_period("M") + 1,
        ticker=raw["종목코드"].astype(str),
        ret=pd.to_numeric(raw["이번달수익률"], errors="coerce") / 100,
    ).pivot(index="month", columns="ticker", values="ret")

    prices = pd.read_csv(source / "downloaded_monthly_prices.csv.gz", dtype={"ticker": str})
    prices["month"] = pd.PeriodIndex(prices.month, freq="M")
    adjusted = prices.pivot(index="month", columns="ticker", values="Adj Close").sort_index()
    yahoo = adjusted.reindex(pd.period_range(adjusted.index.min(), adjusted.index.max(), freq="M"))
    yahoo = yahoo.pct_change(fill_method=None)
    factors = parse_factors(source / "F-F_Research_Data_Factors.csv")

    original = pd.read_csv(source / f"{CASE}__original_triple_monthly.csv").set_index("month")
    months = original.index
    assert list(months) == list(pd.period_range("2000-02", "2026-10", freq="M").astype(str))
    returns = master.pivot(index="투자월", columns="종목코드", values="이번달수익률").reindex(months) / 100
    returns = returns.fillna(0)
    holdings = pd.read_csv(source / "holdings.csv.gz", dtype={"ticker": str})
    base = holdings.loc[holdings.case.eq(CASE) & holdings.variant.eq("original_triple")]
    base = base.pivot(index="month", columns="ticker", values="weight").reindex_like(returns).fillna(0)
    gross, net, _ = simulate(base.to_numpy(), returns.to_numpy())
    np.testing.assert_allclose(np.stack([gross, net]), original[["gross", "net25bp"]].to_numpy().T,
                               atol=1e-12, rtol=0)

    scores = pd.read_csv(source / "signal_scores.csv.gz", dtype={"ticker": str})
    scores = scores.loc[scores.case.eq(CASE)]
    assert not scores.duplicated(["month", "ticker"]).any()
    assert set(scores.month) == set(months)
    assert set(scores.source) == {"archive", "yahoo_full_window"}
    ranked = {}
    max_score_error = 0.0
    for month, frame in scores.groupby("month"):
        frame = frame.set_index("ticker")
        end = pd.Period(month, freq="M") - 1
        window = pd.period_range(end=end, periods=12, freq="M")
        observed = history.reindex(index=window, columns=frame.index)
        use_yahoo = frame.index[frame.source.eq("yahoo_full_window")]
        observed.loc[:, use_yahoo] = yahoo.reindex(index=window, columns=use_yahoo)
        f = factors.reindex(window)
        x = np.column_stack([np.ones(len(window)), f.iloc[:, :3]])
        coefficients = frame[["alpha", "beta_market", "beta_size", "beta_value"]].to_numpy().T
        residual = observed.to_numpy() - f.RF.to_numpy()[:, None] - x @ coefficients
        assert np.isfinite(residual).all()
        for key, formation in WINDOWS.items():
            part = residual[formation]
            z = part.mean(axis=0) / part.std(axis=0, ddof=1)
            assert np.isfinite(z).all()
            if key == "skip1":
                max_score_error = max(max_score_error, float(np.max(np.abs(z - frame.score))))
            ranked[month, key] = frame.assign(score=z).sort_values(
                ["score", "ticker"], ascending=[False, True]
            ).index
    assert max_score_error < 1e-10, max_score_error

    summary = {}
    for count in (4, 5, 6):
        for allocation in (1.0, 0.5):
            monthly = {}
            changes = {}
            for key in WINDOWS:
                weights = pd.DataFrame(0.0, index=months, columns=returns.columns)
                for month in months[original.exposure.gt(0)]:
                    selected = ranked[month, key][:count]
                    weights.loc[month, selected] = original.exposure.loc[month] / count
                weights = (allocation * weights + (1 - allocation) * base).to_numpy()
                np.testing.assert_allclose(weights.sum(axis=1), original.exposure, atol=1e-12, rtol=0)
                gross, net, turnover = simulate(weights, returns.to_numpy())
                monthly[key] = net
                if key == "skip1" and count == 6:
                    variant = "residual_all_top6" if allocation == 1 else "blend50_original_residual"
                    saved = pd.read_csv(source / f"{CASE}__{variant}_monthly.csv").set_index("month")
                    np.testing.assert_allclose(np.stack([gross, net, turnover]),
                                               saved[["gross", "net25bp", "turnover"]].to_numpy().T,
                                               atol=1e-12, rtol=0)
                changes[key] = {
                    period: {"net": metrics(net[(months >= start) & (months <= end)]),
                             "gross": metrics(gross[(months >= start) & (months <= end)])}
                    for period, start, end in PERIODS
                }
            rng = np.random.default_rng(20261116)
            n = len(months)
            blocks = rng.integers(0, n, size=(10000, (n + 5) // 6))
            indices = ((blocks[:, :, None] + np.arange(6)) % n).reshape(len(blocks), -1)[:, :n]
            for key in ("include_11m", "include_12m"):
                delta = np.log1p(monthly[key]) - np.log1p(monthly["skip1"])
                samples = np.expm1(delta[indices].mean(axis=1) * 12)
                changes[key]["relative_cagr_ci"] = np.quantile(samples, [.025, .975]).tolist()
            summary[f"top{count}_residual{allocation:g}"] = changes
    return {"max_score_error": max_score_error, "scores_compared": len(scores), "summary": summary}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot.resolve(), args.source.resolve()), indent=2))
