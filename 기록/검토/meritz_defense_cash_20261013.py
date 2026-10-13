"""또메리츠 방어 최고 이격도 <0 현금 비교. 제품 코드/실데이터 수정 없음.

실행: python 기록/검토/meritz_defense_cash_20261013.py --output <결과폴더>
확정월 2026-09까지, 라이브 엔진/기본 교체비용을 사용한다.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils import snowball as sb


def metrics(rets):
    rets = np.asarray(rets, dtype=float)
    curve = np.r_[1., np.cumprod(1 + rets)]
    dd = curve / np.maximum.accumulate(curve) - 1
    std = rets.std(ddof=0)
    down = np.sqrt(np.mean(np.minimum(rets, 0) ** 2))
    return dict(months=len(rets), cagr=float(curve[-1] ** (12 / len(rets)) - 1),
                cumulative=float(curve[-1] - 1), mdd=float(dd.min()),
                vol=float(std * np.sqrt(12)),
                sharpe=float(rets.mean() / std * np.sqrt(12)) if std else 0.,
                sortino=float(rets.mean() / down * np.sqrt(12)) if down else 0.,
                worst_month=float(rets.min()))


def independent_check(prices, div, sig, bt, threshold_cash, cost):
    """원가격에서 신호/다음월 수익/비용을 독립 검산한다."""
    previous = None
    max_error = 0.
    for row in bt.itertuples():
        m, nm = pd.Period(row.signal_month, 'M'), pd.Period(row.hold_month, 'M')
        i = prices.index.get_loc(m)
        ret6 = {t: prices[t].iloc[i] / prices[t].iloc[i - 6] - 1
                for t in sb.SIGNAL_ASSETS}
        c1 = all(ret6[t] < 0 for t in sb.C1_RISK_ASSETS) and (
            ret6['VIXY'] < 0 or ret6['VIXY'] >= sb.VIXY_SPIKE)
        window = div.reindex(pd.period_range(m - 59, m, freq='M')).dropna()
        current = div.get(m, np.nan)
        rank = int((window <= current).sum())
        c2 = (len(window) >= 48 and pd.notna(current)
              and rank / len(window) * 100 <= 10 and rank != 1)
        assert bool(sig.loc[m, 'cond1']) == bool(c1)
        assert bool(sig.loc[m, 'cond2']) == bool(c2)
        if c1 or c2:
            ds = {t: prices[t].iloc[i] / prices[t].iloc[i - 11:i + 1].mean() - 1
                  for t in sb.DEFENSE_ASSETS}
            chosen = max(ds, key=ds.get)
            if threshold_cash and ds[chosen] < 0:
                chosen = sb.CASH
        else:
            rs = {t: prices[t].iloc[i] / prices[t].iloc[i - 12] - 1
                  for t in sb.OFFENSE_ASSETS}
            chosen = max(rs, key=rs.get)
        assert chosen == row.hold, (m, chosen, row.hold)
        gross = 0. if chosen == sb.CASH else prices.loc[nm, chosen] / prices.loc[m, chosen] - 1
        tc = cost if previous is None or chosen != previous else 0.
        error = abs(gross - tc - row.ret_strategy)
        max_error = max(max_error, float(error))
        previous = chosen
    assert max_error < 1e-12
    return dict(months=len(bt), max_return_error=max_error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    # 로컬 CSV만 읽으며 HTTP 폴백을 금지한다.
    sb._http_csv = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('local CSV required'))
    prices = sb.load_monthly_prices.__wrapped__().loc[:'2026-09']
    div = sb.load_dividend_yield.__wrapped__().loc[:'2026-09']
    required = list(dict.fromkeys(sb.SIGNAL_ASSETS + sb.OFFENSE_ASSETS + sb.DEFENSE_ASSETS))
    assert set(required).issubset(prices.columns)
    assert all(prices[t].last_valid_index() == pd.Period('2026-09', 'M') for t in required)
    assert prices.index.equals(pd.period_range(prices.index.min(), prices.index.max(), freq='M'))
    sig = sb.compute_signals.__wrapped__(prices, div)
    variant = sig.copy(deep=True)
    best_disp = sig[[f'disp12_{t}' for t in sb.DEFENSE_ASSETS]].max(axis=1)
    stop = sig['hold'].notna() & sig['defensive'] & (best_disp < 0)
    variant.loc[stop, 'hold'] = sb.CASH
    variant.loc[stop, 'reason'] = '방어 최고 12M MA 이격도 <0 → 현금'
    # 현 엔진은 CASH 열이 없으면 그 달을 누락한다. 1.0 가격 열로 현금 0% 수익을 구현.
    px_cash = prices.assign(CASH=1.)
    original = sb.run_backtest.__wrapped__(prices, sig)
    baseline = sb.run_backtest.__wrapped__(px_cash, sig)
    trial = sb.run_backtest.__wrapped__(px_cash, variant)
    pd.testing.assert_frame_equal(original, baseline)
    assert baseline['hold_month'].equals(trial['hold_month'])
    months = pd.PeriodIndex(baseline['hold_month'], freq='M')
    assert months.equals(pd.period_range(months.min(), months.max(), freq='M'))
    checks = {
        'baseline': independent_check(prices, div, sig, baseline, False, .0025),
        'cash': independent_check(prices, div, sig, trial, True, .0025),
        'baseline_live_equal': True,
    }
    detail = pd.DataFrame(dict(signal_month=baseline.signal_month, hold_month=baseline.hold_month,
                              defensive=baseline.defensive, base_hold=baseline.hold,
                              cash_hold=trial.hold, best_disp=best_disp.reindex(
                                  pd.PeriodIndex(baseline.signal_month, freq='M')).to_numpy(),
                              base_gross=baseline.ret_gross, cash_gross=trial.ret_gross,
                              base_cost=baseline.cost, cash_cost=trial.cost,
                              base_net=baseline.ret_strategy, cash_net=trial.ret_strategy))
    detail['delta'] = detail.cash_net - detail.base_net
    detail.to_csv(out / 'monthly.csv', index=False, encoding='utf-8-sig')
    changed = detail.base_hold != detail.cash_hold
    intervals = [('full', months.min(), months.max()),
                 ('2012-2016', pd.Period('2012-01'), pd.Period('2016-12')),
                 ('2017-2021', pd.Period('2017-01'), pd.Period('2021-12')),
                 ('2022-2026', pd.Period('2022-01'), pd.Period('2026-09')),
                 ('through_2025', months.min(), pd.Period('2025-12'))]
    periods = {}
    for label, start, end in intervals:
        mask = (months >= start) & (months <= end)
        if mask.any():
            periods[label] = dict(start=str(months[mask].min()), end=str(months[mask].max()),
                                 baseline=metrics(detail.base_net[mask]), cash=metrics(detail.cash_net[mask]),
                                 cash_months=int((trial.hold[mask] == sb.CASH).sum()))
    annual = {str(y): dict(baseline=float(np.prod(1 + detail.base_net[months.year == y]) - 1),
                          cash=float(np.prod(1 + detail.cash_net[months.year == y]) - 1),
                          months=int((months.year == y).sum())) for y in np.unique(months.year)}
    costs = {}
    for c in [0, .001, .0025, .005, .01]:
        costs[str(c)] = {name: metrics(sb.run_backtest.__wrapped__(px_cash, signals, cost=c).ret_strategy)
                        for name, signals in [('baseline', sig), ('cash', variant)]}
    # 0.25%가 매수+매도 교체 합계라는 해석: 현금 진입/이탈에 각 0.125%.
    half = trial.ret_strategy.copy()
    prior = trial.hold.shift(1)
    one_leg = trial.switched & ((trial.hold == sb.CASH) | (prior == sb.CASH))
    half += np.where(one_leg, trial.cost / 2, 0)
    relative_logs = np.log1p(detail.cash_net.to_numpy()) - np.log1p(detail.base_net.to_numpy())
    rng = np.random.default_rng(20261013)
    n = len(relative_logs)
    starts = rng.integers(0, n, size=(20000, (n + 5) // 6))
    indices = ((starts[:, :, None] + np.arange(6)) % n).reshape(20000, -1)[:, :n]
    boot = np.expm1(relative_logs[indices].mean(axis=1) * 12)
    diffs = detail.delta.to_numpy()
    t = diffs.mean() / (diffs.std(ddof=1) / np.sqrt(n)) if diffs.std(ddof=1) else 0.
    latest = sig[sig.hold.notna()].iloc[-1]
    latest_m = sig[sig.hold.notna()].index[-1]
    summary = dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                   price_sha256=hashlib.sha256(prices.to_csv().encode()).hexdigest(),
                   dividend_sha256=hashlib.sha256(div.to_csv().encode()).hexdigest(),
                   periods=periods, annual=annual, costs=costs, checks=checks,
                   half_cash_transition_cost=metrics(half),
                   changed_hold_months=int(changed.sum()),
                   defensive_months=int(baseline.defensive.sum()),
                   cash_win_months=int((detail.delta[changed] > 0).sum()),
                   cash_loss_months=int((detail.delta[changed] < 0).sum()),
                   base_switches=int(baseline.switched.sum()), cash_switches=int(trial.switched.sum()),
                   paired_t=float(t), relative_log_bootstrap95=np.quantile(boot, [.025, .975]).tolist(),
                   latest=dict(signal_month=str(latest_m), defensive=bool(latest.defensive),
                               baseline_hold=latest.hold, cash_hold=variant.loc[latest_m, 'hold'],
                               best_defense_disparity=float(best_disp.loc[latest_m])))
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print('CHANGED MONTHS')
    print(detail[changed].to_string(index=False))


if __name__ == '__main__':
    main()
