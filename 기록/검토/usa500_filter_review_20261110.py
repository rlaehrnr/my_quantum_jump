"""연구 전용 USA500 조건 비교. 라이브/실데이터 수정 없음.

python 기록/검토/usa500_filter_review_20261110.py --snapshot .usa500-review-tmp
  --output 기록/2026-11-10-USA500-필터검토 --commit <입력 git SHA>
snapshot: git archive <SHA> utils archive_usa data/snowball/monthly 의 별도 사본.
2026-11 미확정 수익은 반드시 제외한다. 라이브 계산기를 선정에 재사용한다.
"""
import argparse
from dataclasses import dataclass, asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Spec:
    name: str = 'baseline'
    cutoff: int = 100
    first: int = 3
    last: int = 8
    universe: int = 500
    timing: str = 'ma12'
    multi4: bool = True
    vol_target: float = 0
    exposure: float = 1


def specifications():
    b = Spec()
    out = [b]
    out += [replace(b, name=f'cutoff{c}', cutoff=c) for c in [50, 75, 125, 150, 200]]
    out += [replace(b, name=f'rank{a}_{z}', first=a, last=z)
            for a, z in [(1, 6), (1, 10), (1, 20), (1, 30), (3, 12), (3, 22), (5, 10), (5, 14), (9, 14)]]
    out += [replace(b, name=f'ma{m}', timing=f'ma{m}') for m in [6, 8, 10]]
    out += [replace(b, name='absolute12', timing='absolute12'),
            replace(b, name='ma_ensemble', timing='ensemble'),
            replace(b, name='without_multi4', multi4=False),
            replace(b, name='multi4_only', timing='none'),
            replace(b, name='without_timing', timing='none', multi4=False),
            replace(b, name='ma10_without_multi4', timing='ma10', multi4=False)]
    out += [replace(b, name=f'universe{u}', universe=u) for u in [200, 300]]
    out += [replace(b, name=f'vol{v}', vol_target=v / 100) for v in [15, 20, 25]]
    out += [replace(b, name=f'fixed{v}', exposure=v / 100) for v in [50, 75]]
    return out


def metrics(r):
    r = np.asarray(r, dtype=float)
    equity = np.r_[1., np.cumprod(1 + r)]
    dd = equity / np.maximum.accumulate(equity) - 1
    vol = r.std(ddof=0) * np.sqrt(12)
    cagr = equity[-1] ** (12 / len(r)) - 1
    return dict(months=len(r), cagr=float(cagr), mdd=float(dd.min()),
                vol=float(vol), sharpe=float(r.mean() * 12 / vol) if vol else 0.,
                calmar=float(cagr / -dd.min()) if dd.min() < 0 else 0.,
                worst_month=float(r.min()))


def price_series(root, ticker):
    d = pd.read_csv(root / 'data/snowball/monthly' / f'{ticker}_과거_데이터.csv')
    d['날짜'] = pd.to_datetime(d['날짜'])
    s = d.sort_values('날짜').set_index('날짜')['종가'].astype(float)
    s.index = s.index.to_period('M')
    return s[~s.index.duplicated(keep='last')]


def exposure_map(spy, kind):
    if kind == 'none':
        e = pd.Series(1., index=spy.index)
    elif kind == 'absolute12':
        e = (spy / spy.shift(12) >= 1).astype(float)
    elif kind == 'ensemble':
        e = sum((spy >= spy.rolling(m).mean()).astype(float) for m in [6, 10, 12]) / 3
    else:
        m = int(kind.removeprefix('ma'))
        e = (spy >= spy.rolling(m).mean()).astype(float)
    return {(p + 1).strftime('%Y-%m'): float(v) for p, v in e.items()}


def simulate(weights, stock_returns, cost=0.0025):
    """월초 목표비중과 전월말 표류비중의 매수+매도액 각각에 편도비용 부과.

    비용을 월초 자산에서 비례 차감한 뒤 목표비중 수익 실현. 현금0%.
    """
    prev = np.zeros(weights.shape[1])
    gross, net, turnover = [], [], []
    for w, ret in zip(weights, stock_returns):
        traded = np.abs(w - prev).sum()
        r = float(w @ ret)
        gross.append(r)
        net.append((1 - cost * traded) * (1 + r) - 1)
        turnover.append(float(traded))
        prev = w * (1 + ret) / (1 + r)
    return np.array(gross), np.array(net), np.array(turnover)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--commit', required=True)
    a = p.parse_args()
    root, out = Path(a.snapshot).resolve(), Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root))
    os.chdir(root)
    from utils import us_helpers as uh
    from utils.data_loader import load_archive_data
    raw = load_archive_data.__wrapped__('archive_usa', None)
    master = uh.preprocess_us_data(raw, is_daily=False)
    all_master = master.copy()
    master = master[master['투자월'] <= '2026-10'].copy()
    months = sorted(master['투자월'].unique())
    assert months == list(pd.period_range(months[0], months[-1], freq='M').astype(str))
    assert not master.duplicated(['투자월', '종목코드']).any()
    tickers = sorted(master['종목코드'].unique())
    lookup = {t: i for i, t in enumerate(tickers)}
    groups = {m: d.copy() for m, d in master.groupby('투자월', sort=True)}
    returns = master.pivot(index='투자월', columns='종목코드', values='이번달수익률').reindex(index=months, columns=tickers).fillna(0).to_numpy() / 100
    spy = price_series(root, 'SPY')
    px = pd.DataFrame({t: price_series(root, t) for t in ['TIP', 'VWO', 'VEA', 'VIXY']})
    r6 = px / px.shift(6) - 1
    valid = r6.notna().all(axis=1)
    cond = (r6[['TIP', 'VWO', 'VEA']] < 0).all(axis=1) & ((r6.VIXY < 0) | (r6.VIXY >= .4))
    m4 = {(p + 1).strftime('%Y-%m'): bool(cond.loc[p]) for p in px.index if valid.loc[p]}
    uh.get_multi4_cond1_map = lambda: m4
    uh.get_spy_timing_map = lambda n: {m: v == 0 for m, v in exposure_map(spy, f'ma{n}').items()}
    pools = {}
    specs = specifications()
    weights, series, summary, holding_records = {}, {}, [], []
    for s in specs:
        key = (s.cutoff, s.universe)
        if key not in pools:
            pools[key] = {m: uh.get_triple_momentum_us(d.sort_values('시가총액', ascending=False).head(s.universe), s.cutoff, 'rank') for m, d in groups.items()}
        signal = exposure_map(spy, s.timing)
        w = np.zeros_like(returns)
        for i, m in enumerate(months):
            picks = pools[key][m].iloc[s.first-1:s.last]
            e = signal.get(m, 1.)
            if s.multi4 and m4.get(m, False): e = 0.
            if not picks.empty:
                for t in picks['종목코드']: w[i, lookup[t]] = e / len(picks)
        if s.vol_target:
            # 전월까지 실현된 기준 전략 월수익만 사용한다. 당월 수익은 참조하지 않는다.
            history = series['baseline']['gross']
            vol = pd.Series(history).rolling(6).std(ddof=1).shift(1).to_numpy() * np.sqrt(12)
            scale = np.minimum(1., np.divide(s.vol_target, vol, out=np.ones(len(vol)), where=vol > 0))
            scale[~np.isfinite(scale)] = 1.
            w *= scale[:, None]
        w *= s.exposure
        assert np.all(w >= 0) and np.all(w.sum(axis=1) <= 1 + 1e-12)
        gross, net, turnover = simulate(w, returns)
        assert np.max(np.abs(gross - np.sum(w * returns, axis=1))) < 1e-12
        frame = pd.DataFrame({'month': months, 'gross': gross, 'net_25bp': net,
                              'turnover': turnover, 'exposure': w.sum(axis=1),
                              'holdings': (w > 0).sum(axis=1)})
        frame.to_csv(out / f'{s.name}_monthly.csv', index=False, encoding='utf-8-sig')
        weights[s.name], series[s.name] = w, frame
        for i, j in np.argwhere(w > 0):
            holding_records.append({'variant': s.name, 'month': months[i], 'ticker': tickers[j], 'weight': w[i, j], 'return': returns[i, j]})
        for label, lo, hi in [('all', '1999-01', '2026-10'), ('train_1999_2009', '1999-01', '2009-12'),
                              ('2010_2019', '2010-01', '2019-12'), ('2020_2026', '2020-01', '2026-10'),
                              ('through_2025', '1999-01', '2025-12'), ('2026', '2026-01', '2026-10')]:
            part = frame[(frame.month >= lo) & (frame.month <= hi)]
            for col in ['gross', 'net_25bp']:
                summary.append({'variant': s.name, 'period': label, 'cost': col, **metrics(part[col]),
                                'mean_exposure': float(part.exposure.mean()),
                                'mean_holdings_invested': float(part.loc[part.exposure > 0, 'holdings'].mean()),
                                'turnover_per_year': float(part.turnover.mean() * 12)})
    # 네트워크와 무관한 같은 입력으로 현행 엔진의 전월 출력을 대조한다.
    actual, _ = uh.run_backtest_triple_us_m4.__wrapped__(master, 1999, 2026, 12, True, True, 100, 3, 8, pd.DataFrame(), universe_n=500)
    col = '🛡️ 3·6·12 교집합 + 멀티4'
    error = float(np.max(np.abs(actual[col].to_numpy() / 100 - series['baseline'].gross.to_numpy())))
    assert error < 1e-12, error
    # 모든 월의 교집합을 별도 수식으로 재현한다.
    pick_checks = 0
    for m, d in groups.items():
        d = d.sort_values('시가총액', ascending=False).head(500).copy()
        for n in [3, 6, 12]: d[f'r{n}'] = (1 + d[f'{n}개월(%)'] / 100) / (1 + d['1개월(%)'] / 100) - 1
        common = set.intersection(*[set(d.sort_values(f'r{n}', ascending=False).head(100)['종목코드']) for n in [3, 6, 12]])
        expected = list(d[d['종목코드'].isin(common)].sort_values('r12', ascending=False)['종목코드'])
        assert expected == list(pools[(100, 500)][m]['종목코드'])
        pick_checks += 1
    # Future truncation: timing and risk scaling before a cut must remain unchanged.
    cuts = ['2009-12', '2019-12', '2025-12']
    for cut in cuts:
        for kind in ['ma6', 'ma8', 'ma10', 'ma12', 'absolute12', 'ensemble']:
            short = exposure_map(spy[spy.index <= pd.Period(cut)], kind)
            full = exposure_map(spy, kind)
            assert all(full[k] == v for k, v in short.items())
    table = pd.DataFrame(summary)
    table.to_csv(out / 'comparison.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(holding_records).to_csv(out / 'holdings.csv', index=False, encoding='utf-8-sig')
    sensitivity = []
    for name, w in weights.items():
        for bp in [10, 25, 50]:
            _, net, _ = simulate(w, returns, bp / 10000)
            sensitivity.append({'variant': name, 'one_way_bp': bp, **metrics(net)})
    pd.DataFrame(sensitivity).to_csv(out / 'cost_sensitivity.csv', index=False, encoding='utf-8-sig')
    # 목표변동성안과 사전 위험 규모를 맞춘 연초 고정비중 대조군.
    # 매년 1월 직전60개월의 동적안/기준 실현변동성 비율을 그 해 유지한다.
    # 첫60개월은 비교에서 제외. 사후 전체기간 위험비율로 맞추지 않는다.
    matched = []
    for target in ['vol15', 'vol20']:
        w = weights['baseline'].copy()
        scale = 1.
        for i, m in enumerate(months):
            if i >= 60 and m.endswith('-01'):
                base_vol = series['baseline'].gross.iloc[i-60:i].std(ddof=1)
                managed_vol = series[target].gross.iloc[i-60:i].std(ddof=1)
                scale = min(1., managed_vol / base_vol) if base_vol > 0 else 1.
            w[i] *= scale
        _, net, _ = simulate(w, returns)
        for begin in ['2004-01', '2010-01']:
            mask = np.array(months) >= begin
            matched += [{'target': target, 'begin': begin, 'method': 'annual_fixed', **metrics(net[mask])},
                        {'target': target, 'begin': begin, 'method': 'monthly_dynamic', **metrics(series[target].net_25bp.to_numpy()[mask])}]
    pd.DataFrame(matched).to_csv(out / 'risk_matched.csv', index=False, encoding='utf-8-sig')
    partial, _ = uh.run_backtest_triple_us_m4.__wrapped__(all_master, 1999, 2026, 12, True, True, 100, 3, 8, pd.DataFrame(), universe_n=500)
    partial_metrics = metrics(partial[col].to_numpy() / 100)
    partial_last = partial.iloc[-1][['투자월', col]].to_dict()
    # Pseudo out-of-sample: all candidates were specified before this run, but not before historic data.
    train = table[(table.period == 'train_1999_2009') & (table.cost == 'net_25bp')].sort_values('calmar', ascending=False)
    chosen = str(train.iloc[0].variant)
    wf = {name: metrics(series[name].loc[series[name].month >= '2010-01', 'net_25bp']) for name in ['baseline', chosen]}
    rng = np.random.default_rng(20261110)
    ci = {}
    n = sum(np.array(months) <= '2025-12')
    indices = ((rng.integers(0, n, size=(10000, (n + 5) // 6))[:, :, None] + np.arange(6)) % n).reshape(10000, -1)[:, :n]
    base_log = np.log1p(series['baseline'].net_25bp.to_numpy()[:n])
    for s in specs[1:]:
        delta = np.log1p(series[s.name].net_25bp.to_numpy()[:n]) - base_log
        stats = np.expm1(delta[indices].mean(axis=1) * 12)
        ci[s.name] = dict(relative_annual_return=float(np.expm1(delta.mean()*12)),
                          interval95=list(np.quantile(stats, [.025, .975])))
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(root.rglob('*.csv'))}
    (out / 'input_sha256.json').write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')
    result = {'input_commit': a.commit, 'first': months[0], 'last': months[-1], 'months': len(months),
              'variants': [asdict(s) for s in specs], 'live_max_monthly_error': error,
              'independent_selection_months': pick_checks, 'timing_truncation_checks': cuts,
              'multi4_first_month': min(m4), 'pseudo_oos_selected': chosen, 'pseudo_oos': wf,
              'including_unfinished_month_metrics': partial_metrics,
              'including_unfinished_last_row': partial_last,
              'bootstrap_through_2025_net_25bp': ci,
              'excluded_months': sorted(set(all_master['투자월']) - set(months))}
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['variants','bootstrap_through_2025_net_25bp']}, ensure_ascii=False, indent=2))
    print(table[(table.period == 'all') & (table.cost == 'gross')][['variant', 'cagr', 'mdd', 'sharpe']].to_string(index=False))


if __name__ == '__main__':
    main()
