"""기존 USA500 잔차 점수에서 매수 순위 범위만 바꿔 비교한다."""

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from usa500_filter_review_20261110 import metrics, simulate
from usa500_residual_review_20261110 import parse_factors


CASE = "supplemented_lag2"
RANK_RANGES = ((1, 4), (1, 5), (1, 6), (3, 8), (3, 4), (3, 5))


def run(snapshot, source, output):
    sys.path.insert(0, str(snapshot))
    os.chdir(snapshot)
    from utils.data_loader import load_archive_data
    from utils.us_helpers import preprocess_us_data

    raw = load_archive_data.__wrapped__("archive_usa", None)
    master = preprocess_us_data(raw, is_daily=False)
    original = pd.read_csv(source / f"{CASE}__original_triple_monthly.csv").set_index("month")
    scores = pd.read_csv(source / "signal_scores.csv.gz")
    scores = scores.loc[scores.case.eq(CASE)].sort_values(
        ["month", "score", "ticker"], ascending=[True, False, True]
    )
    assert not scores.duplicated(["month", "ticker"]).any()
    months = original.index
    assert list(months) == list(pd.period_range("2000-02", "2026-10", freq="M").astype(str))
    picks = scores.groupby("month")
    coverage = picks.size().reindex(months)
    assert coverage.min() >= 8
    holdings = pd.read_csv(source / "holdings.csv.gz")
    holdings = holdings.loc[holdings.case.eq(CASE) & holdings.variant.eq("original_triple")]
    returns = master.loc[master["투자월"].isin(months)].pivot(
        index="투자월", columns="종목코드", values="이번달수익률"
    ).reindex(months) / 100
    base = holdings.pivot(index="month", columns="ticker", values="weight").reindex(
        index=months, columns=returns.columns
    ).fillna(0)
    ret = returns.fillna(0).to_numpy()
    gross, net, _ = simulate(base.to_numpy(), ret)
    assert np.allclose(gross, original.gross, atol=1e-12, rtol=0)
    assert np.allclose(net, original.net25bp, atol=1e-12, rtol=0)

    score = picks.get_group("2026-10").iloc[0]
    fit_months = pd.period_range("2023-09", "2026-08", freq="M")
    if score.source == "archive":
        rows = raw.loc[raw["종목코드"].astype(str).eq(score.ticker)].copy()
        rows.index = pd.to_datetime(rows["종목선정일"]).dt.to_period("M") + 1
        price_return = pd.to_numeric(rows["이번달수익률"]).reindex(fit_months) / 100
    else:
        prices = pd.read_csv(source / "downloaded_monthly_prices.csv.gz")
        prices = prices.loc[prices.ticker.eq(score.ticker)].set_index("month")
        prices.index = pd.PeriodIndex(prices.index, freq="M")
        price_return = prices["Adj Close"].reindex(
            pd.period_range(fit_months[0] - 1, fit_months[-1], freq="M")
        ).pct_change(fill_method=None).reindex(fit_months)
    factors = parse_factors(source / "F-F_Research_Data_Factors.csv").reindex(fit_months)
    x = np.column_stack([np.ones(36), factors.iloc[:, :3]])
    coefficients = np.linalg.lstsq(x, price_return - factors.RF, rcond=None)[0]
    fitted = x @ coefficients + factors.RF.to_numpy()
    residuals = (price_return.to_numpy() - fitted)[-11:]
    reproduced = residuals.mean() / residuals.std(ddof=1)
    assert abs(reproduced - score.score) < 1e-10
    diagnostics = {
        "input_snapshot": (snapshot / "commit.txt").read_text().strip(),
        "scores_source": source.name,
        "mean_eligible": float(coverage.mean()),
        "eligible_2026_10": int(coverage.loc["2026-10"]),
        "example_ticker": score.ticker,
        "example_return_2026_08": float(price_return.iloc[-1]),
        "example_fitted_2026_08": float(fitted[-1]),
        "example_residual_2026_08": float(residuals[-1]),
        "example_11m_residual_mean": float(residuals.mean()),
        "example_11m_residual_std": float(residuals.std(ddof=1)),
        "example_score": float(reproduced),
    }

    output.mkdir(parents=True, exist_ok=True)
    summary = []
    monthly = []
    periods = {
        "all": ("2000-02", "2026-10"),
        "2000–2009": ("2000-02", "2009-12"),
        "2010–2019": ("2010-01", "2019-12"),
        "2020–2026": ("2020-01", "2026-10"),
        "through2025": ("2000-02", "2025-12"),
    }
    active = original.exposure.gt(0)
    for start, end in RANK_RANGES:
        residual = pd.DataFrame(0., index=months, columns=returns.columns)
        for month in months[active]:
            selected = list(picks.get_group(month).iloc[start - 1:end].ticker)
            assert returns.loc[month, selected].notna().all()
            residual.loc[month, selected] = 1 / len(selected)
        label = f"{start}-{end}"
        for name, weights in [("잔차 단독", residual), ("기존·잔차 반반", (base + residual) / 2)]:
            assert np.allclose(weights.sum(axis=1), original.exposure, atol=1e-12, rtol=0)
            gross, net, turnover = simulate(weights.to_numpy(), ret)
            if label == "1-6":
                file = "residual_all_top6" if name == "잔차 단독" else "blend50_original_residual"
                expected = pd.read_csv(source / f"{CASE}__{file}_monthly.csv").set_index("month")
                assert np.allclose(gross, expected.gross, atol=1e-12, rtol=0)
                assert np.allclose(net, expected.net25bp, atol=1e-12, rtol=0)
            monthly.append(pd.DataFrame({"ranks": label, "strategy": name, "month": months,
                                         "gross": gross, "net25bp": net, "turnover": turnover}))
            for period, (first, last) in periods.items():
                mask = (months >= first) & (months <= last)
                for cost, series in [("gross", gross), ("net25bp", net)]:
                    summary.append({"ranks": label, "strategy": name, "period": period,
                                    "cost": cost, **metrics(series[mask])})
    table = pd.DataFrame(summary)
    table.to_csv(output / "comparison.csv", index=False)
    pd.concat(monthly).to_csv(output / "monthly.csv", index=False)
    (output / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    print(json.dumps(diagnostics, indent=2))
    print(table.loc[table.period.eq("all"), ["ranks", "strategy", "cost", "cagr", "mdd"]].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.snapshot.resolve(), args.source.resolve(), args.output.resolve())
