"""맘·쏘 삼성 원인 분석과 주요 대안의 독립 산술 검산. 연구 전용."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd


def plain(fn):
    return getattr(fn, '__wrapped__', fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[2]
    src, out = Path(args.source).resolve(), Path(args.output).resolve()
    os.chdir(src)
    sys.path.insert(0, str(src))
    from utils import snowball as sb
    sb._http_csv = lambda *a: (_ for _ in ()).throw(AssertionError('HTTP forbidden'))
    p = plain(sb.load_monthly_prices)().loc[:'2026-10']
    sig = plain(sb.compute_signals_so)(p)
    manual = {}
    diagnostic = []
    # pandas의 shift/rolling/신호 헬퍼를 사용하지 않고 원가격 슬라이스에서 계산.
    for i, m in enumerate(p.index):
        if i < 12:
            continue
        off = sb.SO_OFFENSE_ASSETS
        scores, disp = {}, {}
        for t in off:
            vals = p[t].to_numpy()
            if not all(math.isfinite(vals[i-k]) for k in [0, 1, 3, 6, 12]):
                break
            scores[t] = sum(vals[i] / vals[i-k] - 1 for k in [1, 3, 6, 12])
            disp[t] = vals[i] / (sum(vals[i-3:i+1]) / 4) - 1
        if len(scores) != len(off):
            continue
        ret6 = {t: p[t].iloc[i] / p[t].iloc[i-6] - 1 for t in sb.SIGNAL_ASSETS}
        riskoff = all(ret6[t] < 0 for t in ['TIP', 'VWO', 'VEA']) and (ret6['VIXY'] < 0 or ret6['VIXY'] >= .4)
        ranked = sorted(off, key=lambda t: scores[t], reverse=True)
        top = ranked[:2]
        passed = [t for t in top if disp[t] > 0]
        holds = list(sb.SO_DEFENSE_ASSETS) if riskoff or scores['SPY'] <= 0 or not passed else passed
        assert holds == sig.loc[m, 'holds'], (m, holds, sig.loc[m, 'holds'])
        manual[m] = holds
        if m >= pd.Period('2026-01', 'M'):
            diagnostic.append(dict(signal_month=str(m), hold_month=str(m+1),
                                   riskoff=bool(riskoff), spy_score=float(scores['SPY']),
                                   holds=holds, scores=scores, disparity4=disp, ret6=ret6))
    assert len(manual) == 184  # 183개 실현월 + 최신 11월용 신호.

    live = pd.read_csv(out / 'so__live_original.csv')
    # 종목별 기여도와 비용을 직접 누적. 대안별 저장 비중 전월을 동일 검산.
    validated = {}
    for variant in ['base', 'cash25', 'cash50', 'vol10', 'vol15', 'vol20',
                    'top3', 'top4', 'pair50_gldief', 'hold_ma6', 'hold_ma10', 'hold_ma12', 'growth_cap50']:
        w = pd.read_csv(out / f'so__{variant}__weights.csv', index_col=0)
        w.index = pd.PeriodIndex(w.index, freq='M')
        bt = pd.read_csv(out / f'so__{variant}__monthly.csv', index_col=0)
        bt.index = pd.PeriodIndex(bt.index, freq='M')
        previous = {}
        errors = []
        wealth = 1.
        peak = 1.
        minimum_dd = 0.
        for nm, row in bt.iterrows():
            m = nm - 1
            current = {t: float(v) for t, v in w.loc[m].items() if v > 0}
            gross = sum(v * (float(p.loc[nm, t]) / float(p.loc[m, t]) - 1) for t, v in current.items())
            fee = .0025 * sum(max(current.get(t,0.) - previous.get(t,0.),0.) for t in set(current)|set(previous))
            error = abs(gross - fee - row['net'])
            assert error < 1e-12
            errors.append(error)
            if variant.startswith('vol'):
                target = int(variant[3:]) / 100
                h = manual[m]
                j = p.index.get_loc(m)
                vals = []
                for k in range(j-11, j+1):
                    vals.append(sum(float(p[t].iloc[k]) / float(p[t].iloc[k-1]) - 1 for t in h) / len(h))
                avg = sum(vals) / 12
                risk = math.sqrt(sum((x-avg)**2 for x in vals) / 11 * 12)
                scale = min(1., target / risk) if risk else 1.
                for t in h:
                    assert abs(current[t] - scale / len(h)) < 1e-12
            wealth *= 1 + gross - fee
            peak = max(peak, wealth)
            minimum_dd = min(minimum_dd, wealth / peak - 1)
            previous = current
        validated[variant] = dict(months=len(bt), max_error=max(errors),
                                   cagr=wealth ** (12/len(bt))-1, mdd=minimum_dd)

    # 위험을 맞춘 단순 대조군을 별도 검증 러너로 재실행. 타 세션 파일에는 쓰지 않음.
    spec = importlib.util.spec_from_file_location('risk_validator', out / 'risk_control_reference.py')
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    rv.selftest()
    w = pd.read_csv(out / 'so__base__weights.csv', index_col=0).reindex(columns=p.columns)
    w.index = pd.PeriodIndex(w.index, freq='M')
    w = w.reindex(p.index)
    start = pd.Period('2011-08','M')
    base = rv.simulate(p, w, start)
    riskmatched = {}
    rows = []
    allruns = {'base': base}
    for target in [.15, .20]:
        for window in [6, 12, 24]:
            dynw, scale, risk = rv.overlay(p, w, window, target)
            dyn = rv.simulate(p, dynw, start)
            err = rv.independent_check(p, w, dyn, scale, risk, window, target, start)
            label = f'w{window}_t{int(target*100)}'
            if window == 12:
                own = pd.read_csv(out/f'so__vol{int(target*100)}__monthly.csv', index_col=0)
                np.testing.assert_allclose(dyn.net, own.net, atol=1e-12, rtol=0)
            r = {'independent_max_error': err}
            allruns[label] = dyn
            for training in ['expanding', 'rolling60']:
                fw, _, folds = rv.matched(w, base, dyn, training)
                fixed = rv.simulate(p, fw, start)
                allruns[f'{label}_fixed_{training}'] = fixed
                for period,a,b in [('pre2026','2017-01','2025-12'),('with2026','2017-01','2026-10'),('2026','2026-01','2026-10')]:
                    for kind, bt in [('dynamic', dyn),('fixed',fixed)]:
                        rows.append(dict(setting=label, training=training, kind=kind, period=period, **rv.stats(bt.loc[a:b,'net'])))
                if window == 12:
                    r[training] = dict(folds=folds, bootstrap=rv.bootstrap(fixed.loc['2017-01':'2025-12','net'],dyn.loc['2017-01':'2025-12','net']))
            riskmatched[label] = r
    for label,bt in allruns.items():
        bt.to_csv(out/f'so_riskmatched__{label}.csv', encoding='utf-8-sig')
    pd.DataFrame(rows).to_csv(out/'so_riskmatched_summary.csv', encoding='utf-8-sig', index=False)
    r = p.pct_change(fill_method=None)
    correlations = {}
    for end in ['2025-12','2026-06','2026-09','2026-10']:
        correlations[end] = {str(n):float(r.loc[:end,['EWY','SMH']].tail(n).corr().iloc[0,1]) for n in [12,36]}
    (out/'so_independent_audit.json').write_text(json.dumps(dict(
        independent_signals=len(manual), verified=validated, signals2026=diagnostic,
        riskmatched=riskmatched, correlations=correlations), ensure_ascii=False, indent=2), encoding='utf-8')
    print('SO_AUDIT_OK: 184 raw-price signals; 13 x 183 return/cost records; volatility scalar/covariance checks; risk-matched controls')
    print(pd.DataFrame(rows).query("setting == 'w12_t20' and training=='expanding'").to_string(index=False))


if __name__ == '__main__':
    main()
