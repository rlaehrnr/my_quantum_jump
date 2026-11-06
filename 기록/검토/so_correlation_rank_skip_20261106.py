"""연구용 상관 기반 차순위 교체. 제품 코드와 원본 가격은 읽기만 한다.

실행: python 기록/검토/so_correlation_rank_skip_20261106.py --output <폴더>
저장소 루트에서 실행하며, 2026-10 확정월까지 사용한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from so_volatility_validation_20261105 import bootstrap, stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import snowball as sb

CUTOFF = '2026-10'
PRIMARY = 'w24_r70'
WINDOWS = (12, 24, 36)
THRESHOLDS = (.60, .70, .80)
PERIODS = {
    'full': ('2011-08', CUTOFF),
    'pre2026': ('2011-08', '2025-12'),
    '2011_2016': ('2011-08', '2016-12'),
    '2017_2021': ('2017-01', '2021-12'),
    '2022_2025': ('2022-01', '2025-12'),
    '2026_observed': ('2026-01', CUTOFF),
}


def choose(signals, correlations, threshold):
    """상위 2종이 모두 통과한 공격월에서만 2위 교체를 검토한다."""
    altered = signals.copy(deep=True)
    events = []
    for month, row in signals.iterrows():
        holds = row['holds']
        if row['defensive'] or not isinstance(holds, list) or len(holds) != 2:
            continue
        first, second = holds
        pair = correlations.loc[(month, first)]
        initial_corr = float(pair[second])
        if not np.isfinite(initial_corr) or initial_corr <= threshold:
            continue
        ranked = row[[f'score_{t}' for t in sb.SO_OFFENSE_ASSETS]].astype(float).sort_values(ascending=False)
        ranking = [key.removeprefix('score_') for key in ranked.index]
        assert ranking[:2] == holds
        replacement = None
        for rank, asset in enumerate(ranking[2:], start=3):
            if row[f'abs_{asset}'] > 0 and pd.notna(pair[asset]) and pair[asset] <= threshold:
                replacement = asset
                altered.at[month, 'holds'] = [first, asset]
                altered.at[month, 'hold'] = f'{first}·{asset}'
                altered.at[month, 'reason'] = '연구용 상관 차순위 교체'
                break
        events.append(dict(signal_month=str(month), hold_month=str(month + 1),
                           first=first, second=second, initial_corr=initial_corr,
                           replacement=replacement, replacement_rank=rank if replacement else None,
                           replacement_corr=float(pair[replacement]) if replacement else None))
    return altered, events


def independent_check(prices, original, chosen, backtest, window, threshold):
    """원가격 슬라이스에서 상관·선택·수익·비용을 독립 재계산한다."""
    previous = {}
    max_error = 0.
    for month, row in original.iterrows():
        holds = row['holds']
        if holds is None:
            continue
        expected = holds
        if not row['defensive'] and len(holds) == 2:
            first, second = holds
            history = prices.loc[:month].tail(window + 1)

            def corr(asset):
                raw = history[[first, asset]].to_numpy()
                if len(raw) != window + 1 or not np.isfinite(raw).all():
                    return np.nan
                changes = raw[1:] / raw[:-1] - 1
                return np.corrcoef(changes.T)[0, 1]

            if corr(second) > threshold:
                eligible = [asset for asset in sb.SO_OFFENSE_ASSETS
                            if asset not in holds and row[f'abs_{asset}'] > 0 and corr(asset) <= threshold]
                if eligible:
                    expected = [first, max(eligible, key=lambda asset: row[f'score_{asset}'])]
        assert expected == chosen.at[month, 'holds'], (window, threshold, month)
        if month == prices.index[-1]:
            continue
        current = {asset: 1 / len(expected) for asset in expected}
        gross = sum(weight * (prices.loc[month + 1, asset] / prices.loc[month, asset] - 1)
                    for asset, weight in current.items())
        cost = .0025 * sum(max(weight - previous.get(asset, 0.), 0.) for asset, weight in current.items())
        live_row = backtest.loc[month + 1]
        error = abs(gross - cost - live_row['ret_strategy'])
        assert error < 1e-12 and abs(cost - live_row['cost']) < 1e-12
        max_error = max(max_error, error)
        previous = current
    return max_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=True)

    def offline(*args, **kwargs):
        raise AssertionError('로컬 스냅샷 파일이 필요합니다.')

    sb._http_csv = offline
    prices = sb.load_monthly_prices.__wrapped__().loc[:CUTOFF]
    assert str(prices.index.max()) == CUTOFF
    assert prices.index.equals(pd.period_range(prices.index.min(), prices.index.max(), freq='M'))
    signals = sb.compute_signals_so.__wrapped__(prices)
    returns = prices[sb.SO_OFFENSE_ASSETS].pct_change(fill_method=None)

    def run(chosen, cost=.0025):
        bt = sb.run_backtest_samsung.__wrapped__(prices, chosen, cost=cost)
        bt.index = pd.PeriodIndex(bt['hold_month'], freq='M')
        assert bt.index.equals(pd.period_range('2011-08', CUTOFF, freq='M'))
        return bt

    baseline = {cost: run(signals, cost) for cost in (0., .0025, .005, .01)}
    base = baseline[.0025]
    baseline_error = independent_check(prices, signals, signals, base, 24, 1.)
    results, summaries, events_out, months = {}, [], [], []
    for window in WINDOWS:
        matrix = returns.rolling(window).corr()
        for threshold in THRESHOLDS:
            name = f'w{window}_r{round(threshold * 100)}'
            chosen, events = choose(signals, matrix, threshold)
            alt = run(chosen)
            max_error = independent_check(prices, signals, chosen, alt, window, threshold)
            for cutoff in ['2019-12', '2025-12', '2026-06', '2026-09']:
                truncated = sb.compute_signals_so.__wrapped__(prices.loc[:cutoff])
                prior, _ = choose(truncated, returns.loc[:cutoff].rolling(window).corr(), threshold)
                pd.testing.assert_series_equal(prior['hold'], chosen.loc[:cutoff, 'hold'])
            event_counts, intervals = {}, {}
            for period, (start, end) in PERIODS.items():
                a = base.loc[start:end, 'ret_strategy']
                b = alt.loc[start:end, 'ret_strategy']
                changed = base.loc[start:end, 'hold'].ne(alt.loc[start:end, 'hold'])
                difference = b - a
                intervals[period] = {'base': stats(a), 'alternative': stats(b),
                                     'changed_months': int(changed.sum()),
                                     'changed_wins': int((difference[changed] > 0).sum()),
                                     'changed_losses': int((difference[changed] < 0).sum()),
                                     'changed_average_delta': float(difference[changed].mean()) if changed.any() else None}
                summaries.append(dict(variant=name, period=period, changed_months=int(changed.sum()),
                                      **{f'base_{k}': v for k, v in stats(a).items()},
                                      **{f'alt_{k}': v for k, v in stats(b).items()}))
            for event in events:
                hold_month = pd.Period(event['hold_month'], 'M')
                if hold_month in base.index:
                    event.update(base_return=float(base.at[hold_month, 'ret_strategy']),
                                 alt_return=float(alt.at[hold_month, 'ret_strategy']))
                events_out.append(dict(variant=name, **event))
            event_counts['high_corr_months'] = sum(event['hold_month'] <= CUTOFF for event in events)
            event_counts['no_replacement_months'] = sum(event['hold_month'] <= CUTOFF and event['replacement'] is None for event in events)
            costs = {}
            for fee, ref in baseline.items():
                compared = alt if fee == .0025 else run(chosen, fee)
                costs[str(fee)] = {period: dict(base=stats(ref.loc[start:end, 'ret_strategy']),
                                                alternative=stats(compared.loc[start:end, 'ret_strategy']))
                                   for period, (start, end) in PERIODS.items() if period in ('full', 'pre2026')}
            results[name] = dict(intervals=intervals, event_counts=event_counts, cost_sensitivity=costs,
                                 independent_max_error=max_error,
                                 bootstrap={period: bootstrap(base.loc[:end, 'ret_strategy'], alt.loc[:end, 'ret_strategy'])
                                            for period, end in [('full', CUTOFF), ('pre2026', '2025-12')]},
                                 latest_hold=chosen.iloc[-1]['hold'])
            for month in base.index:
                months.append(dict(variant=name, hold_month=str(month), signal_month=str(month - 1),
                                   base_hold=base.at[month, 'hold'], alt_hold=alt.at[month, 'hold'],
                                   base_return=base.at[month, 'ret_strategy'], alt_return=alt.at[month, 'ret_strategy'],
                                   base_cost=base.at[month, 'cost'], alt_cost=alt.at[month, 'cost']))
    digest = hashlib.sha256(prices.to_csv().encode()).hexdigest()
    report = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  prices_sha256=digest, cutoff=CUTOFF, primary=PRIMARY, candidates=sb.SO_OFFENSE_ASSETS,
                  baseline_independent_max_error=baseline_error, prefix_checks=True,
                  baseline_latest_hold=signals.iloc[-1]['hold'], variants=results)
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    pd.DataFrame(summaries).to_csv(out / 'summary.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(events_out).to_csv(out / 'events.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(months).to_csv(out / 'monthly.csv', index=False, encoding='utf-8-sig')
    print('CHECK_OK', len(base), 'live months;', len(months), 'independently verified variant months; 4 prefix cuts per variant')
    print(pd.DataFrame(summaries).query("period in ['full','pre2026']")[[
        'variant', 'period', 'changed_months', 'base_cagr', 'alt_cagr', 'base_mdd', 'alt_mdd', 'base_sharpe', 'alt_sharpe']].to_string(index=False))


if __name__ == '__main__':
    main()
