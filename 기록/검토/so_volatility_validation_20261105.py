"""연구 전용: 맘·쏘 삼성 변동성 조절과 사전 위험대응 고정 비중 비교.

python 기록/검토/so_volatility_validation_20261105.py --source <원격스냅샷> --output <결과폴더>
라이브/data 무수정. 과거 전부 이미 관찰됨: 시간순 검증은 진짜 미사용 검증이 아님.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd


def stats(r):
    r = pd.Series(r).astype(float)
    assert len(r) and np.isfinite(r).all() and (r > -1).all()
    a = r.to_numpy()
    wealth = np.r_[1., np.cumprod(1 + a)]
    peak = np.maximum.accumulate(wealth)
    dd = wealth / peak - 1
    underwater = 0
    longest = 0
    for v in dd[1:]:
        underwater = underwater + 1 if v < -1e-12 else 0
        longest = max(longest, underwater)
    sd = a.std(ddof=0)
    return dict(n=len(a), cagr=float(wealth[-1] ** (12 / len(a)) - 1),
                cumulative=float(wealth[-1] - 1), mdd=float(dd.min()),
                vol=float(sd * np.sqrt(12)),
                sharpe=float(a.mean() / sd * np.sqrt(12)) if sd else 0.,
                worst_month=float(a.min()),
                worst_3m=float(np.expm1(np.log1p(r).rolling(3).sum()).min()) if len(a) >= 3 else None,
                worst_6m=float(np.expm1(np.log1p(r).rolling(6).sum()).min()) if len(a) >= 6 else None,
                max_underwater_months=longest, current_dd=float(dd[-1]))


def simulate(p, w, start, cost=.0025, drift=False):
    """m월말 비중을 m+1월에 보유. live=매수 증가분, drift=매수·매도 각각 cost/2."""
    prev = np.zeros(p.shape[1])
    rows = []
    for i in range(len(p) - 1):
        m, nm = p.index[i], p.index[i + 1]
        if nm < start:
            continue
        cur = w.loc[m].to_numpy(float)
        assert np.isfinite(cur).all() and cur.min() >= -1e-12 and cur.sum() <= 1 + 1e-12
        held = cur > 0
        r = p.iloc[i + 1].to_numpy(float)[held] / p.iloc[i].to_numpy(float)[held] - 1
        assert np.isfinite(r).all()
        gross = float(cur[held] @ r)
        buy = float(np.maximum(cur - prev, 0).sum())
        sell = float(np.maximum(prev - cur, 0).sum())
        fee = cost * ((buy + sell) / 2 if drift else buy)
        rows.append(dict(month=str(nm), signal_month=str(m), gross=gross, cost=fee,
                         net=gross - fee, exposure=float(cur.sum()), bought=buy))
        if drift:
            prev = np.zeros_like(cur)
            prev[held] = cur[held] * (1 + r) / (1 + gross)
        else:
            prev = cur.copy()
    return pd.DataFrame(rows).set_index(pd.PeriodIndex([x['month'] for x in rows], freq='M'))


def overlay(p, w, window, target):
    r = p.pct_change(fill_method=None)
    scale = pd.Series(np.nan, index=w.index, dtype=float)
    risk = scale.copy()
    for m, row in w.iterrows():
        if row.isna().any():
            continue
        h = row[row > 0]
        if not len(h):
            scale.loc[m] = 1.
            continue
        z = r.loc[:m, h.index].tail(window)
        if len(z) < window or z.isna().any().any():
            scale.loc[m] = 1.  # 자료 부족 기간은 기존 비중 유지, 숨은 현금기간을 만들지 않음
        else:
            v = float(z.dot(h).std(ddof=1) * np.sqrt(12))
            risk.loc[m] = v
            scale.loc[m] = min(1., target / v) if v else 1.
    return w.mul(scale, axis=0), scale, risk


def matched(w, base, dynamic, training='expanding'):
    """연초 전에 실현된 월만으로 위험비율 계산, 해당 연도에는 고정."""
    coef = pd.Series(1., index=w.index)
    folds = []
    for year in range(base.index.min().year + 1, base.index.max().year + 1):
        train_end = pd.Period(f'{year - 1}-12', 'M')
        a = base.loc[:train_end, 'net']
        b = dynamic.loc[:train_end, 'net']
        if len(a) < 60:
            continue
        if training == 'rolling60':
            a, b = a.tail(60), b.tail(60)
        ratio = float(min(1., b.std(ddof=0) / a.std(ddof=0)))
        first_signal, last_signal = pd.Period(f'{year - 1}-12', 'M'), pd.Period(f'{year}-11', 'M')
        coef.loc[first_signal:last_signal] = ratio
        folds.append(dict(year=year, train_end=str(train_end), n_train=len(a),
                          fixed_exposure=ratio, training=training))
    assert folds
    return w.mul(coef, axis=0), coef, folds


def bootstrap(a, b, count=20000, block=6):
    """같은 월의 짝과 시계열 의존 보존. 구간은 다중비교 보정 없는 탐색용."""
    assert a.index.equals(b.index)
    x, y = a.to_numpy(), b.to_numpy()
    rng = np.random.default_rng(20261105)
    n = len(x)
    start = rng.integers(0, n, size=(count, (n + block - 1) // block))
    ix = ((start[:, :, None] + np.arange(block)) % n).reshape(count, -1)[:, :n]
    xx, yy = x[ix], y[ix]
    delta_sharpe = np.sqrt(12) * (yy.mean(1) / yy.std(1) - xx.mean(1) / xx.std(1))
    relative = np.expm1((np.log1p(yy) - np.log1p(xx)).mean(1) * 12)
    return dict(n=n, count=count, block=block,
                sharpe_difference=stats(b)['sharpe'] - stats(a)['sharpe'],
                sharpe_difference_ci95=np.quantile(delta_sharpe, [.025, .975]).tolist(),
                annual_relative_return=float(np.expm1((np.log1p(y) - np.log1p(x)).mean() * 12)),
                annual_relative_ci95=np.quantile(relative, [.025, .975]).tolist())


def selftest():
    assert abs(stats(pd.Series([-.1, .1]))['mdd'] + .1) < 1e-12
    idx = pd.period_range('2000-01', periods=26, freq='M')
    p = pd.DataFrame({'a': 100 * np.cumprod(1 + np.tile([.1, -.04], 13)),
                      'b': 100 * np.cumprod(1 + np.tile([-.02, .03], 13))}, index=idx)
    w = pd.DataFrame(.5, index=idx, columns=p.columns)
    v, scale, risk = overlay(p, w, 12, .1)
    z = p.pct_change(fill_method=None).loc[idx[1]:idx[12]].mean(axis=1)
    expected = float(z.std(ddof=1) * np.sqrt(12))
    assert abs(risk.loc[idx[12]] - expected) < 1e-12
    assert abs(scale.loc[idx[12]] - min(1., .1 / expected)) < 1e-12
    bt = simulate(p, w, idx[1])
    np.testing.assert_allclose(bt.net.iloc[0], ((p.iloc[1] / p.iloc[0] - 1).mean() - .0025))
    np.testing.assert_allclose(simulate(p, w * .5, idx[1]).net, bt.net * .5, atol=1e-12)
    for cut in [idx[15], idx[20]]:
        vc, sc, rc = overlay(p.loc[:cut], w.loc[:cut], 12, .1)
        pd.testing.assert_frame_equal(vc, v.loc[:cut])
        pd.testing.assert_series_equal(sc, scale.loc[:cut])
    future = p.copy()
    future.loc[idx[20]:] *= 4
    vf, _, _ = overlay(future, w, 12, .1)
    pd.testing.assert_frame_equal(vf.loc[:idx[19]], v.loc[:idx[19]])


def independent_check(p, w, bt, scale, risk, window, target, start):
    """공분산 행렬과 종목별 사칙연산으로 조절 비중·비용·월수익 독립 검산."""
    returns = p.pct_change(fill_method=None)
    previous = {}
    max_error = 0.
    for nm, row in bt.iterrows():
        m = nm - 1
        original = w.loc[m]
        h = original[original > 0]
        if pd.notna(risk.loc[m]):
            z = returns.loc[:m, h.index].tail(window).to_numpy()
            center = z - z.mean(axis=0)
            covariance = center.T @ center / (window - 1)
            weights = h.to_numpy()
            sd = float(np.sqrt(weights @ covariance @ weights * 12))
            assert abs(sd - risk.loc[m]) < 1e-12
            expected_scale = min(1., target / sd) if sd else 1.
            assert abs(expected_scale - scale.loc[m]) < 1e-12
        current = {t: float(weight * scale.loc[m]) for t, weight in h.items()}
        gross = sum(weight * (float(p.loc[nm,t]) / float(p.loc[m,t]) - 1) for t,weight in current.items())
        bought = sum(max(current.get(t,0.) - previous.get(t,0.), 0.) for t in set(current) | set(previous))
        error = abs(gross - bought * .0025 - row['net'])
        assert error < 1e-12
        max_error = max(max_error, error)
        previous = current
    return max_error


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    src, out = Path(args.source).resolve(), Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    selftest()
    os.chdir(src)
    sys.path.insert(0, str(src))
    from utils import snowball as sb
    def offline(*a, **kw):
        raise AssertionError('HTTP disabled for reproducible local-data research')
    sb._http_csv = offline
    plain = lambda f: getattr(f, '__wrapped__', f)
    p = plain(sb.load_monthly_prices)()
    cutoff = pd.Period('2026-10', 'M')
    p = p.loc[:cutoff].copy()
    assert p.index.max() == cutoff
    assert p.index.equals(pd.period_range(p.index.min(), cutoff, freq='M'))
    sig = plain(sb.compute_signals_so)(p)
    w = pd.DataFrame(np.nan, index=p.index, columns=p.columns)
    for m, h in sig.holds.items():
        if isinstance(h, list):
            w.loc[m] = 0.
            w.loc[m, h] = 1 / len(h)
    live = plain(sb.run_backtest_samsung)(p, sig, cost=.0025)
    live.index = pd.PeriodIndex(live.hold_month, freq='M')
    start = live.index.min()
    assert live.index.equals(pd.period_range(start, cutoff, freq='M'))
    base = simulate(p, w, start)
    np.testing.assert_allclose(base.net, live.ret_strategy, atol=1e-12, rtol=0)
    for cut in ['2020-12', '2025-12', '2026-06', '2026-09']:
        s2 = plain(sb.compute_signals_so)(p.loc[:cut])
        pd.testing.assert_series_equal(s2.hold, sig.loc[:cut].hold)
    rows, folds_out, reports, series = [], [], {}, {'base': base.net}
    periods = {'full': (str(start), str(cutoff)), 'pre2026': (str(start), '2025-12'),
               'wf_all': ('2017-01', str(cutoff)), 'wf_pre2026': ('2017-01', '2025-12'),
               '2026_observed': ('2026-01', str(cutoff))}
    crises = {'2011_debt': ('2011-08', '2011-12'), '2015_16': ('2015-08', '2016-02'),
              '2018_q4': ('2018-10', '2018-12'), '2020_q1': ('2020-01', '2020-03'),
              '2022': ('2022-01', '2022-12'), '2026_observed': ('2026-01', str(cutoff))}

    def save(name, bt):
        bt.to_csv(out / f'{name}_monthly.csv', encoding='utf-8-sig')
        for label, (a, b) in periods.items():
            z = bt.loc[a:b, 'net']
            if len(z):
                rows.append(dict(variant=name, period=label, **stats(z)))
        return {label: stats(bt.loc[a:b, 'net']) for label, (a, b) in crises.items()}

    save('base', base)
    for fraction in [.5, .75]:
        save(f'fixed_{fraction:.2f}', simulate(p, w * fraction, start))
    for window in [6, 12, 24]:
        for target in [.1, .15, .2]:
            name = f'vol_w{window}_t{int(target*100)}'
            v, scale, risk = overlay(p, w, window, target)
            for cut in ['2020-12', '2025-12', '2026-06', '2026-09']:
                vc, _, _ = overlay(p.loc[:cut], w.loc[:cut], window, target)
                pd.testing.assert_frame_equal(vc, v.loc[:cut])
            dyn = simulate(p, v, start)
            series[name] = dyn.net
            crisis_results = {'dynamic': save(name, dyn), 'base': {k: stats(base.loc[a:b, 'net']) for k,(a,b) in crises.items()}}
            pd.DataFrame(dict(scale=scale, estimated_vol=risk, signal_hold=sig.hold)).to_csv(out / f'{name}_signals.csv', encoding='utf-8-sig')
            report = dict(crises=crisis_results, matched={}, bootstrap={},
                          independent_max_error=independent_check(p,w,dyn,scale,risk,window,target,start))
            for training in ['expanding', 'rolling60']:
                fw, coef, folds = matched(w, base, dyn, training)
                fb = simulate(p, fw, start)
                fixname = name + '_fixed_' + training
                save(fixname, fb)
                series[fixname] = fb.net
                folds_out.extend(dict(variant=name, **row) for row in folds)
                report['matched'][training] = {k: stats(fb.loc[a:b, 'net']) for k,(a,b) in crises.items()}
                for period in ['wf_all', 'wf_pre2026']:
                    a, b = periods[period]
                    report['bootstrap'][training + ':' + period] = bootstrap(fb.loc[a:b,'net'], dyn.loc[a:b,'net'])
                if window == 12 and target in [.15,.2] and training == 'expanding':
                    report['bootstrap_block_sensitivity'] = {
                        str(block): bootstrap(fb.loc['2017-01':'2025-12','net'], dyn.loc['2017-01':'2025-12','net'], block=block)
                        for block in [3,12]}
                if training == 'expanding':
                    # 최초 5년 이상 자료에서 단 한 번만 정해 2017년 이후 계속 고정한 대조군.
                    initial = folds[0]['fixed_exposure']
                    save(name + '_fixed_once', simulate(p, w * initial, start))
                    sensitivity = {}
                    for fee in [0., .0025, .005, .01]:
                        for drift in [False, True]:
                            d2 = simulate(p, v, start, fee, drift)
                            b2 = simulate(p, w, start, fee, drift)
                            f2w, _, _ = matched(w, b2, d2, training)
                            f2 = simulate(p, f2w, start, fee, drift)
                            sensitivity[f'fee{fee}:drift{drift}'] = {
                                'dynamic': stats(d2.loc['2017-01':,'net']),
                                'fixed': stats(f2.loc['2017-01':,'net']),
                                'pre2026_dynamic': stats(d2.loc['2017-01':'2025-12','net']),
                                'pre2026_fixed': stats(f2.loc['2017-01':'2025-12','net'])}
                    report['cost_sensitivity'] = sensitivity
                    # 전체 목표비중 실행을 한 달 늦추는 엄격한 민감도. 기준안도 동일 지연.
                    late_start = start + 1
                    ld = simulate(p, v.shift(1), late_start)
                    lb = simulate(p, w.shift(1), late_start)
                    lfw, _, _ = matched(w.shift(1), lb, ld, training)
                    lf = simulate(p, lfw, late_start)
                    report['one_month_execution_delay'] = {
                        'dynamic': stats(ld.loc['2017-01':,'net']), 'fixed': stats(lf.loc['2017-01':,'net']),
                        'base': stats(lb.loc['2017-01':,'net'])}
            reports[name] = report
    # 연도별 실현 결과. 2026년은 이미 본 10개월이며 연환산보다 누적수익으로 해석.
    yearly = []
    for name, r in series.items():
        for year, z in r.groupby(r.index.year):
            yearly.append(dict(variant=name, year=int(year), **stats(z)))
    pd.DataFrame(rows).to_csv(out / 'summary.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(folds_out).to_csv(out / 'training_folds.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(yearly).to_csv(out / 'yearly.csv', index=False, encoding='utf-8-sig')
    input_hash = hashlib.sha256()
    for path in sorted((src/'data'/'snowball'/'monthly').glob('*.csv')):
        input_hash.update(path.name.encode())
        input_hash.update(path.read_bytes())
    result = dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'], cwd=src, text=True).strip(),
                  input_sha256=input_hash.hexdigest(), cutoff=str(cutoff), start=str(start),
                  checks=dict(live_max_error=float(np.max(abs(base.net-live.ret_strategy))),
                              prefix_invariance=True, selftests=True, missing_months=0),
                  design=dict(primary=['vol_w12_t15','vol_w12_t20'], sensitivity_windows=[6,12,24],
                              sensitivity_targets=[.1,.15,.2], risk_free_return=0., leverage_cap=1.,
                              genuine_unseen_test=False, daily_drawdown_available=False,
                              bootstrap_multiple_comparison_adjusted=False), variants=reports)
    (out/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('VALIDATED: baseline, causal signal/overlay prefixes, formula selftests, 9 settings, 2 training modes; source='+result['source_commit'])
    print(pd.DataFrame(rows).query("variant in ['base','vol_w12_t15','vol_w12_t20','vol_w12_t20_fixed_expanding'] and period in ['full','wf_pre2026','wf_all','2026_observed']").to_string(index=False))


if __name__ == '__main__':
    main()
