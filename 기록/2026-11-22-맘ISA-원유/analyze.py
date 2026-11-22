"""Research only. Run against the 767c987 snapshot with collect_prices.py outputs."""
from pathlib import Path
import hashlib
import json
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from utils import snowball as sb
from utils.static_allocation import KR_SUMMER, KR_WINTER, US_SUMMER, US_WINTER
from utils.static_allocation_proxies import prior_foreign_close

CUTOFF = pd.Period("2026-10", freq="M")
COMMON_START = pd.Period("2018-11", freq="M")
COST = .0025
OIL = "261220"
BASE = "WTI_base"
REMOVE = "WTI_remove"
CASH = "WTI_months_cash"
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)


def plain(func):
    return getattr(func, "__wrapped__", func)


def read_daily(market):
    data = pd.read_csv(ROOT / f"research_daily_{market}.csv", index_col="date", parse_dates=True)
    assert data.index.is_monotonic_increasing and data.index.is_unique
    assert (data.stack().dropna() > 0).all()
    return data


def month_ends(daily, sessions):
    on_session = daily.reindex(sessions)
    ends = ~sessions.to_period("M").duplicated(keep="last")
    return on_session.loc[ends].set_axis(sessions[ends].to_period("M"))


def simulate(monthly, signals, first, cost, cash_when_oil=False):
    periods = monthly.index
    records = []
    previous = None
    for signal, holding in zip(periods[:-1], periods[1:]):
        held = signals.at[str(signal), "holds"]
        if holding < first or not isinstance(held, list):
            continue
        ticker = held[0]
        if ticker == OIL and cash_when_oil:
            ticker = CASH
        gross = 0. if ticker == CASH else monthly.at[holding, ticker] / monthly.at[signal, ticker] - 1
        if not np.isfinite(gross):
            continue
        fee = cost if ticker != CASH and previous != ticker else 0.
        records.append((holding, ticker, signals.at[str(signal), "defensive"], gross, fee))
        previous = ticker
    result = pd.DataFrame(records, columns=("month", "ticker", "defensive", "gross", "fee")).set_index("month")
    result["net"] = result.gross - result.fee
    return result


def drawdown(wealth):
    return wealth / wealth.cummax().clip(lower=1.) - 1.


def metrics(returns):
    wealth = (1. + returns).cumprod()
    trough = drawdown(wealth).idxmin()
    peak = wealth.loc[:trough].idxmax()
    downside = np.sqrt(np.mean(np.minimum(returns, 0.) ** 2))
    return {
        "months": len(returns), "cagr": wealth.iloc[-1] ** (12 / len(returns)) - 1,
        "mdd": drawdown(wealth).loc[trough], "trough": str(trough), "peak": str(peak),
        "wealth": wealth.iloc[-1], "worst_month": returns.min(),
        "sortino": returns.mean() * np.sqrt(12) / downside if downside else None,
    }


def daily_path(path, daily, sessions):
    session_series = pd.Series(sessions, index=sessions)
    dates = {m: d.index for m, d in session_series.groupby(sessions.to_period("M"))}
    first_day = dates[path.index[0] - 1][-1]
    rows = [pd.DataFrame({"wealth": [1.], "ticker": [""], "month": [str(path.index[0] - 1)]},
                         index=[first_day])]
    wealth = 1.
    for m, trade in path.iterrows():
        days = dates[m]
        last_day = dates[m - 1][-1]
        ticker = trade.ticker
        if ticker == CASH:
            returns = pd.Series(0., index=days)
        else:
            prices = daily.loc[days, ticker]
            assert prices.notna().all(), (m, ticker, prices[prices.isna()].index)
            returns = prices / daily.at[last_day, ticker] - 1
        assert np.isclose(returns.iloc[-1], trade.gross, atol=1e-12), (m, ticker)
        values = wealth * (1. + returns - trade.fee)
        rows.append(pd.DataFrame({"wealth": values, "ticker": ticker, "month": str(m)}))
        wealth = values.iloc[-1]
    result = pd.concat(rows)
    result["dd"] = drawdown(result.wealth)
    np.testing.assert_allclose(result.wealth.groupby(result.month).last().iloc[1:],
                               (1 + path.net).cumprod(), atol=1e-12)
    return result


def daily_metrics(path):
    trough = path.dd.idxmin()
    peak = path.loc[:trough].wealth.idxmax()
    return {"daily_mdd": path.at[trough, "dd"], "daily_peak": str(peak.date()),
            "daily_trough": str(trough.date()), "daily_trough_ticker": path.at[trough, "ticker"]}


def candidates_from(plans):
    return {asset.ticker: asset.label for plan in plans for asset in plan if asset.ticker}


def asset_breakdown(path):
    weighted = path.net * (1 + path.net).cumprod().shift(fill_value=1.)
    log = np.log1p(path.net)
    rows = []
    for ticker, group in path.groupby("ticker"):
        net = group.net
        rows.append({"ticker": ticker, "months": len(group), "wins": int(net.gt(0).sum()),
                     "losses": int(net.lt(0).sum()), "mean": net.mean(),
                     "held_months_compound": np.expm1(log.loc[group.index].sum()),
                     "sum_log_returns": log.loc[group.index].sum(),
                     "log_wealth_share": log.loc[group.index].sum() / log.sum(),
                     "pnl_per_100_initial": 100 * weighted.loc[group.index].sum(),
                     "pnl_share": weighted.loc[group.index].sum() / weighted.sum()})
    assert np.isclose(sum(row["log_wealth_share"] for row in rows), 1.)
    assert np.isclose(sum(row["pnl_share"] for row in rows), 1.)
    return rows


local = read_daily("kr")
foreign = read_daily("us")
sessions = local["069500"].dropna().index
fx = prior_foreign_close(foreign["KRW=X"], sessions)
foreign_candidates = candidates_from((US_WINTER, US_SUMMER))
foreign_candidates["VTV"] = "US large value proxy"
converted = pd.DataFrame({code: prior_foreign_close(foreign[code], sessions) * fx
                          for code in foreign_candidates})
daily = local.join(converted)
monthly = month_ends(daily, sessions)
live = plain(sb.load_pen_prices)().loc[:CUTOFF]
monthly = monthly.reindex(live.index)
pd.testing.assert_frame_equal(monthly[live.columns].where(live.notna()), live, check_dtype=False, check_names=False)
monthly[live.columns] = live
assert monthly.index.equals(pd.period_range(live.index[0], CUTOFF, freq="M"))

live_signals = plain(sb.compute_signals_pension)(live)
live_result = plain(sb.run_backtest_pension)(live, live_signals, cost=COST)
full = simulate(monthly, live_signals, live.index[0], COST)
assert full.index.astype(str).tolist() == live_result.hold_month.tolist()
np.testing.assert_allclose(full.net, live_result.ret_strategy, rtol=0, atol=1e-12)
np.testing.assert_allclose(full.fee, live_result.cost, rtol=0, atol=1e-12)
missing = pd.period_range(full.index[0], CUTOFF, freq="M").difference(full.index)
continuous = full.loc[missing[-1] + 1:]
assert continuous.index.equals(pd.period_range(continuous.index[0], CUTOFF, freq="M"))

kr = candidates_from((KR_WINTER, KR_SUMMER))
extras = {"144600": "KODEX silver futures (H)", "137610": "TIGER agricultural futures (H)",
          "148070": "KIWOOM Korea Treasury 10Y", "130730": "KIWOOM short-term cash",
          "469830": "SOL ultra short-term bond", "130680": "TIGER WTI crude oil futures Enhanced (H)"}
assert set(kr).intersection(sb.PEN_DEFENSE) == {"411060"}
specs = {BASE: ("control", OIL, "WTI"), REMOVE: ("control", None, "Drop WTI"),
         CASH: ("control", None, "Cash if WTI would win")}
specs.update({code: ("KR static", code, name) for code, name in kr.items() if code not in sb.PEN_DEFENSE})
specs.update({code: ("KR extra", code, name) for code, name in extras.items()})
specs.update({code: ("US reference", code, name) for code, name in foreign_candidates.items()})
common = pd.period_range(COMMON_START, CUTOFF, freq="M")
pairs, rows, signals_by_model = {}, [], {}
for key, (group, candidate, name) in specs.items():
    if key in (BASE, CASH):
        sig = live_signals
    else:
        new_defense = [t for t in sb.PEN_DEFENSE if t != OIL]
        if candidate:
            new_defense.insert(sb.PEN_DEFENSE.index(OIL), candidate)
        with patch.object(sb, "PEN_DEFENSE", new_defense), patch.dict(sb.PEN_TICKER_NAMES, {key: name}):
            sig = plain(sb.compute_signals_pension)(monthly)
        for signal in sig.index:
            original = live_signals.at[signal, "holds"]
            if isinstance(original, list) and not live_signals.at[signal, "defensive"]:
                assert original == sig.at[signal, "holds"]
    signals_by_model[key] = sig
    result = simulate(monthly, sig, COMMON_START, COST, cash_when_oil=key == CASH)
    assert result.index.equals(common), key
    pairs[key] = result
    eligible = common
    first_valid = None
    if candidate:
        valid_scores = monthly[candidate].rolling(sb.PEN_DEF_WIN).count().eq(sb.PEN_DEF_WIN)
        first_valid = valid_scores[valid_scores].index[0] + 1
        eligible = common[common >= first_valid]
        assert len(eligible) and monthly[candidate].loc[first_valid - 1:CUTOFF].notna().all()
    source = pairs[BASE]
    oil_free = pairs[REMOVE] if key != BASE else source
    result_stats = metrics(result.net)
    ready = metrics(result.loc[eligible, "net"])
    ready_base = metrics(source.loc[eligible, "net"])
    ready_drop = metrics(oil_free.loc[eligible, "net"])
    result_daily = daily_path(result, daily, sessions)
    path_daily_stats = daily_metrics(result_daily)
    result_daily.to_csv(OUT / f"daily_{key}.csv", index_label="date")
    diff = np.log1p(result.net) - np.log1p(source.net)
    diff_eligible = diff.loc[eligible].to_numpy()
    rng = np.random.default_rng(20261122)
    starts = rng.integers(0, len(eligible), size=(10000, (len(eligible) + 5) // 6))
    indices = ((starts[:, :, None] + np.arange(6)) % len(eligible)).reshape(len(starts), -1)[:, :len(eligible)]
    paired_ci = np.expm1(12 * diff_eligible[indices].mean(axis=1))
    row = {"key": key, "group": group, "name": name, **result_stats, **path_daily_stats,
           "first_candidate_holding": str(first_valid) if first_valid else "",
           "eligible_start": str(eligible[0]), "eligible_n": len(eligible),
           "candidate_picks": int(result.ticker.eq(candidate if candidate else CASH).sum()),
           "changed_picks_vs_base": int(result.ticker.ne(source.ticker).sum()),
           "eligible_cagr": ready["cagr"], "eligible_base_cagr": ready_base["cagr"],
           "eligible_drop_cagr": ready_drop["cagr"], "eligible_mdd": ready["mdd"],
           "eligible_base_mdd": ready_base["mdd"], "eligible_drop_mdd": ready_drop["mdd"],
           "eligible_cagr_relative_low": float(np.quantile(paired_ci, .025)),
           "eligible_cagr_relative_high": float(np.quantile(paired_ci, .975)),
           "wealth_ratio_no_2026": float(np.exp(diff.loc[:'2025-12'].sum())),
           "wealth_ratio_no_2022_2026": float(np.exp(diff.loc[~diff.index.year.isin([2022, 2026])].sum())),
           "ytd_return": float((1 + result.net.loc['2026']).prod() - 1)}
    for bps in (0, 50):
        alt = simulate(monthly, sig, COMMON_START, bps / 10000, cash_when_oil=key == CASH)
        row[f"cagr_{bps}bps"] = metrics(alt.net)["cagr"]
    rows.append(row)

summary = pd.DataFrame(rows)
summary.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
pd.concat(pairs, axis=1).to_csv(OUT / "monthly_all.csv", encoding="utf-8-sig")
full.to_csv(OUT / "live_full.csv", encoding="utf-8-sig")
daily_continuous = daily_path(continuous, daily, sessions)
oil = full.loc[full.ticker == OIL].copy()
oil["drop_ticker"] = pairs[REMOVE].ticker.reindex(oil.index)
oil["drop_net"] = pairs[REMOVE].net.reindex(oil.index)
oil.to_csv(OUT / "oil_holdings.csv", encoding="utf-8-sig")
events = pd.concat({label: p.loc["2026-03":"2026-10", ["ticker", "net"]]
                    for label, p in pairs.items()}, axis=1)
events.to_csv(OUT / "recent.csv", encoding="utf-8-sig")
annual = pd.DataFrame({key: frame.net.groupby(frame.index.year).apply(lambda r: (1 + r).prod() - 1)
                       for key, frame in pairs.items()})
annual.to_csv(OUT / "annual.csv", encoding="utf-8-sig")
monthly.to_csv(OUT / "monthly_inputs.csv")
details = {
    "baseline_app": metrics(full.net),
    "baseline_continuous": metrics(continuous.net),
    "missing_live_months": missing.astype(str).tolist(),
    "daily_continuous": daily_metrics(daily_continuous),
    "losses_worst_baseline_daily": daily_continuous.nsmallest(5, "dd").to_string(),
    "baseline_attribution": asset_breakdown(full),
    "common_attribution": asset_breakdown(pairs[BASE]),
    "oil_by_year_log": np.log1p(oil.net).groupby(oil.index.year).sum().to_dict(),
    "oil_months_recent": oil.loc["2026"].reset_index().astype({"month": str}).to_dict(orient="records"),
    "inputs": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
               for f in ("snapshot.tar", "research_daily_kr.csv", "research_daily_us.csv")},
    "spec_count": len(specs),
}
(OUT / "details.json").write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
cols = ["key", "group", "cagr", "mdd", "daily_mdd", "eligible_start", "candidate_picks",
        "eligible_cagr", "eligible_base_cagr", "eligible_drop_cagr", "wealth_ratio_no_2026",
        "ytd_return"]
print(summary[cols].round(4).to_string(index=False))
print(json.dumps(details, ensure_ascii=False, indent=2))
