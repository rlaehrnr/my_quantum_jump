"""연구 전용. 라이브 모듈을 읽되 전략/로봇/data 파일에는 쓰지 않는다.

python 기록/검토/snowball_robustness_20261105.py --source <git-archive 폴더> --output <결과폴더>
확정월 2026-10, 기준안 재현·시간순 분리·비용/규칙 민감도 검증.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd


def plain(fn):
    return getattr(fn, '__wrapped__', fn)


def stats(r):
    r = pd.Series(r).dropna().astype(float)
    if not len(r):
        return {}
    v = np.r_[1., np.cumprod(1. + r.to_numpy())]
    dd = v / np.maximum.accumulate(v) - 1.
    sd = float(r.std(ddof=0))
    down = float(np.sqrt(np.mean(np.minimum(r, 0.) ** 2)))
    return dict(n=len(r), start=str(r.index[0]), end=str(r.index[-1]),
                cumulative=float(v[-1] - 1), cagr=float(v[-1] ** (12 / len(r)) - 1),
                mdd=float(dd.min()), vol=sd * np.sqrt(12),
                sharpe=float(r.mean() / sd * np.sqrt(12)) if sd else 0.,
                sortino=float(r.mean() / down * np.sqrt(12)) if down else 0.,
                worst=float(r.min()), current_dd=float(dd[-1]))


def normalize_signals(sig):
    s = sig.copy(deep=True)
    s.index = pd.PeriodIndex(s.index, freq='M')
    return s


def weights(sig, columns):
    w = pd.DataFrame(np.nan, index=sig.index, columns=columns, dtype=float)
    for m, row in sig.iterrows():
        h = row.get('holds', row.get('hold'))
        if h is None or isinstance(h, float):
            continue
        w.loc[m] = 0.
        d = h if isinstance(h, dict) else ({t: 1 / len(h) for t in h} if isinstance(h, list) else {h: 1.})
        for t, v in d.items():
            if t != 'CASH':
                assert t in columns, (m, t)
                w.loc[m, t] = v
        assert 0 <= w.loc[m].sum() <= 1.0000000001
    return w


def simulate(p, w, start, cost=.0025, mode='live', previous=None):
    """월 m 목표비중에 m+1 수익. 결측수익은 현금으로 덮지 않고 실패시킨다.

    live: 앱과 같은 목표비중 증가분 비용. drift_roundtrip: 월말 표류비중
    대비 매수+매도 각각 cost/2를 부과하는 별도 민감도. 현금은 수익 0.
    """
    cols = list(p.columns)
    prev = pd.Series(0., index=cols) if previous is None else previous.reindex(cols, fill_value=0.).copy()
    records = []
    for m in p.index[:-1]:
        nm = m + 1
        if nm < start:
            continue
        cur = w.loc[m]
        assert cur.notna().all(), ('signal gap', m)
        held = cur[cur > 0]
        returns = p.loc[nm, held.index] / p.loc[m, held.index] - 1
        assert returns.notna().all() and np.isfinite(returns).all(), ('missing prices', m)
        gross = float((held * returns).sum())
        buy = float((cur - prev).clip(lower=0).sum())
        sell = float((prev - cur).clip(lower=0).sum())
        fee = cost * buy if mode == 'live' else cost * .5 * (buy + sell)
        rec = dict(month=str(nm), signal_month=str(m), gross=gross, cost=fee,
                   net=gross - fee, exposure=float(cur.sum()), bought=buy,
                   holds=json.dumps(held.to_dict(), ensure_ascii=False, sort_keys=True),
                   attribution=json.dumps((held * returns).to_dict(), ensure_ascii=False, sort_keys=True))
        records.append(rec)
        if mode == 'live':
            prev = cur.copy()
        else:
            prev = pd.Series(0., index=cols)
            # 비용을 현금/전보유에서 비례 부담했다고 근사. 민감도 계산임.
            prev.loc[held.index] = held * (1 + returns) / (1 + gross)
    out = pd.DataFrame(records).set_index('month')
    out.index = pd.PeriodIndex(out.index, freq='M')
    return out


def bootstrap(base, alt, seed=20261105, count=10000):
    d = np.log1p(alt.to_numpy()) - np.log1p(base.to_numpy())
    rng = np.random.default_rng(seed)
    n = len(d)
    starts = rng.integers(0, n, size=(count, (n + 5) // 6))
    ix = (starts[:, :, None] + np.arange(6)) % n
    sampled = d[ix.reshape(count, -1)[:, :n]]
    annual = np.expm1(sampled.mean(axis=1) * 12)
    return dict(annual_relative=float(np.expm1(d.mean() * 12)),
                ci95=np.quantile(annual, [.025, .975]).tolist(),
                blocks=6, count=count)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    src, out = Path(args.source).resolve(), Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.chdir(src)
    sys.path.insert(0, str(src))
    from utils import snowball as sb

    def offline(*a, **kw):
        raise AssertionError(f'HTTP disabled: {a}')
    sb._http_csv = offline
    cutoff = pd.Period('2026-10', 'M')

    def trim(p):
        p = p.loc[:cutoff].copy()
        assert p.index.max() == cutoff
        assert p.index.equals(pd.period_range(p.index.min(), cutoff, freq='M'))
        assert (p.dropna(how='all') > 0).where(p.notna(), True).all().all()
        return p

    us = trim(plain(sb.load_monthly_prices)())
    div = plain(sb.load_dividend_yield)().loc[:cutoff]
    assert div.index.max() == cutoff
    cfg = [
        ('meritz', '또 메리츠', us, lambda p, u: plain(sb.compute_signals)(p, div.reindex(div.index[div.index <= p.index.max()])), plain(sb.run_backtest)),
        ('so', '맘·쏘 삼성', us, lambda p, u: plain(sb.compute_signals_so)(p), plain(sb.run_backtest_samsung)),
        ('ko', '또 ISA', trim(plain(sb.load_ko_prices)()), lambda p, u: plain(sb.compute_signals_ko)(p), plain(sb.run_backtest_ko)),
        ('pen', '또 연금', trim(plain(sb.load_pen_prices)()), lambda p, u: plain(sb.compute_signals_pension)(p), plain(sb.run_backtest_pension)),
        ('ssopen', '쏘 연금', trim(plain(sb.load_ssopen_prices)()), lambda p, u: plain(sb.compute_signals_ssopen)(p, u), plain(sb.run_backtest_ssopen)),
        ('mamtax', '맘 비과세', trim(plain(sb.load_mamtax_prices)()), lambda p, u: plain(sb.compute_signals_mamtax)(p, u), plain(sb.run_backtest_mamtax)),
    ]
    results, summary_rows, month_rows, latest = {}, [], [], {}
    base_rets, variant_rets = {}, {}
    input_hash = hashlib.sha256()
    for path in sorted((src / 'data' / 'snowball').rglob('*.csv')) + sorted((src / 'data' / 'snowball_kr').rglob('*.csv')):
        input_hash.update(str(path.relative_to(src)).encode('utf-8'))
        input_hash.update(path.read_bytes())

    for key, name, p, signal, livefn in cfg:
        s_raw = signal(p, us)
        s = normalize_signals(s_raw)
        live = livefn(p, s_raw, cost=.0025)
        live.index = pd.PeriodIndex(live.hold_month, freq='M')
        w = weights(s, p.columns)
        # 초기의 누락월을 압축해 CAGR을 부풀리지 않는다: 마지막 누락 뒤로 정렬.
        allmonths = pd.period_range(live.index.min(), cutoff, freq='M')
        missing = allmonths.difference(live.index)
        start = missing.max() + 1 if len(missing) else allmonths.min()
        firstm = live.index.min() - 1
        previous = pd.Series(0., index=p.columns)
        # 원출력의 거래비용까지 독립 재현. 초기 공백은 명시적으로 기록.
        errors = []
        for nm, row in live.iterrows():
            m = nm - 1
            cur = w.loc[m]
            held = cur[cur > 0]
            gross = float((held * (p.loc[nm, held.index] / p.loc[m, held.index] - 1)).sum())
            fee = float((cur - previous).clip(lower=0).sum()) * .0025
            errors.append(abs(gross - fee - row.ret_strategy))
            assert abs(gross - row.ret_gross) < 1e-12 and abs(fee - row.cost) < 1e-12
            previous = cur.copy()
        assert max(errors) < 1e-12

        # 모든 비교가 동일한 연속 구간에서 현금 출발. 최초매수비용도 동일.
        baseline = simulate(p, w, start)
        checklive = live.loc[start:, 'ret_strategy']
        # start 앞에 보유가 있으면 최초비용만 다를 수 있으므로 그 뒤는 모두 같아야 함.
        np.testing.assert_allclose(baseline.net.iloc[1:], checklive.iloc[1:], rtol=0, atol=1e-12)
        checks = dict(live_months=len(live), max_error=max(errors), missing_months=list(map(str, missing)),
                      comparison_start=str(start), live_first_month=str(live.index.min()))
        # 잘라 계산해도 과거의 신호/비중이 바뀌지 않는지 검사.
        for cut in ['2025-12', '2026-06', '2026-09']:
            c = pd.Period(cut, 'M')
            sw = weights(normalize_signals(signal(p.loc[:c], us.loc[:c])), p.columns)
            pd.testing.assert_frame_equal(sw, w.loc[:c])
        checks['prefix_invariant'] = True

        variants = {'base': w.copy(), 'cash25': w * .75, 'cash50': w * .5}
        for win in [6, 10, 12]:
            ma = p.rolling(win, min_periods=win).mean()
            # 보유 슬롯이 실패하면 현금 유지, 살아남은 종목에 재집중하지 않음.
            variants[f'hold_ma{win}'] = w.where(p >= ma, 0.).where(w.notna())
        for target in [.10, .15, .20]:
            v = w.copy()
            r = p.pct_change(fill_method=None)
            for m in w.index:
                cur = w.loc[m]
                held = cur[cur > 0]
                if cur.isna().any() or not len(held):
                    continue
                window = r.loc[:m, held.index].tail(12)
                if len(window) == 12 and window.notna().all().all():
                    risk = float(window.dot(held).std(ddof=1) * np.sqrt(12))
                    v.loc[m] *= min(1., target / risk) if risk > 0 else 1.
            variants[f'vol{int(target * 100)}'] = v
        if key == 'so':
            oldk = sb.SO_TOPK
            for k in [3, 4]:
                sb.SO_TOPK = k
                variants[f'top{k}'] = weights(normalize_signals(signal(p, us)), p.columns)
            sb.SO_TOPK = oldk
            # 과거 검토안도 같은 자료에서 재검증. 2026 손실을 보고 만든 가설이다.
            pair = w.copy()
            for m in w.index:
                if w.loc[m, 'EWY'] > 0 and w.loc[m, 'SMH'] > 0:
                    pair.loc[m] *= .5
                    pair.loc[m, ['GLD', 'IEF']] += .25
            variants['pair50_gldief'] = pair
            broad = w.copy()
            growth = ['EWY', 'SMH', 'QQQ', 'FDN', 'LIT']
            for m in w.index:
                total = w.loc[m, growth].sum()
                if total > .5:
                    broad.loc[m, growth] *= .5 / total
            variants['growth_cap50'] = broad
        if key == 'meritz':
            v = w.copy()
            for a, b in [('TQQQ', 'QQQ'), ('USD', 'SOXX')]:
                v[b] += v[a]
                v[a] = 0.
            variants['unlevered_offense'] = v

        byvariant = {}
        for variant, vw in variants.items():
            bt = simulate(p, vw, start)
            bt['defensive'] = s['defensive'].shift(1).reindex(bt.index).astype(bool)
            bt.to_csv(out / f'{key}__{variant}__monthly.csv', encoding='utf-8-sig')
            vw.loc[start - 1:].to_csv(out / f'{key}__{variant}__weights.csv', encoding='utf-8-sig')
            intervals = dict(full=bt.net, pre2026=bt.loc[:'2025-12', 'net'],
                             y2026=bt.loc['2026-01':, 'net'], crisis2022=bt.loc['2022-01':'2022-12', 'net'],
                             post_june=bt.loc['2026-07':, 'net'])
            sm = {k: stats(v) for k, v in intervals.items()}
            sm['mean_exposure'] = float(bt.exposure.mean())
            sm['changed_months'] = int(((vw - w).abs().sum(axis=1).loc[start - 1:cutoff - 1] > 1e-10).sum())
            sm['cost_sensitivity'] = {str(c): stats(simulate(p, vw, start, cost=c).net) for c in [0., .001, .005, .01]}
            drift = simulate(p, vw, start, cost=.005, mode='drift_roundtrip')
            sm['drift_roundtrip_cost_50bp'] = {'full': stats(drift.net), 'y2026': stats(drift.loc['2026-01':, 'net'])}
            sm['pre2026_relative_ci'] = None
            byvariant[variant] = sm
            for period, st in sm.items():
                if period in intervals:
                    summary_rows.append(dict(strategy=key, name=name, variant=variant, period=period, **st))
            variant_rets[(key, variant)] = bt.net
            if variant == 'base':
                base_rets[key] = bt.net
                # 원출력의 실제 표시 MDD와 새 비교시점의 차이를 둘 다 보존.
                original = live.copy()
                original.to_csv(out / f'{key}__live_original.csv', encoding='utf-8-sig', index=False)
                for nm, row in bt.loc['2026-01':].iterrows():
                    month_rows.append(dict(strategy=key, name=name, **row.to_dict(), month=str(nm)))
        for variant in variants:
            byvariant[variant]['pre2026_relative_ci'] = bootstrap(
                variant_rets[(key, 'base')].loc[:'2025-12'], variant_rets[(key, variant)].loc[:'2025-12'])
        # 연도별 과거정보만으로 선택: 5년 이상 훈련 뒤 매년 Sharpe 최고 규칙.
        candidates = ['base', 'cash25', 'cash50', 'hold_ma6', 'hold_ma10', 'hold_ma12', 'vol10', 'vol15', 'vol20']
        annual_choices, wf = [], []
        for year in range(max(start.year + 5, 2017), 2027):
            train_end = pd.Period(f'{year - 1}-12', 'M')
            opts = [(stats(variant_rets[(key, v)].loc[:train_end])['sharpe'], v) for v in candidates]
            chosen = max(opts, key=lambda item: item[0])[1]
            test = variant_rets[(key, chosen)].loc[f'{year}-01':f'{year}-12']
            if len(test):
                wf.append(test)
                annual_choices.append(dict(year=year, variant=chosen, train_end=str(train_end)))
        wfret = pd.concat(wf) if wf else pd.Series(dtype=float)
        wfbase = base_rets[key].reindex(wfret.index)
        # 후보별 연속 운용 곡선을 접합한 선택 진단에는 추가 전환비용이 없다.
        # 운용 가능한 메타 전략의 성과로 해석하지 않고 선택 안정성만 진단한다.
        selected = max(candidates, key=lambda v: byvariant[v]['pre2026']['sharpe'])
        latest[key] = dict(name=name, signal_month=str(cutoff), holds=w.loc[cutoff][w.loc[cutoff] > 0].to_dict(),
                           candidates={v: vv.loc[cutoff][vv.loc[cutoff] > 0].to_dict() for v, vv in variants.items()},
                           reason=s.loc[cutoff, 'reason'])
        # 역사적 최고점·최대낙폭·올해 공격/방어 개월 수를 보존.
        lv = live.ret_strategy
        curve = (1 + lv).cumprod()
        dd = curve / curve.cummax().clip(lower=1.) - 1
        trough = dd.idxmin()
        peak = curve.loc[:trough].idxmax()
        diag = dict(live_full=stats(lv), live_pre2026=stats(lv.loc[:'2025-12']),
                    peak=str(peak), trough=str(trough), peak_to_trough=float(dd.min()),
                    y2026_offense_months=int((~live.loc['2026-01':, 'defensive'].astype(bool)).sum()),
                    y2026_defense_months=int(live.loc['2026-01':, 'defensive'].astype(bool).sum()))
        results[key] = dict(name=name, checks=checks, variants=byvariant, diagnostics=diag,
                            selected_pre2026=selected, annual_selection=annual_choices,
                            wf_selection_diagnostic=stats(wfret), wf_base=stats(wfbase))
        print(json.dumps(dict(strategy=name, live=diag['live_full'], pre2026=diag['live_pre2026'],
                              y2026=byvariant['base']['y2026'], selected=selected), ensure_ascii=False), flush=True)

    R = pd.DataFrame(base_rets).dropna()
    R.to_csv(out / 'six_strategies_common_monthly.csv', encoding='utf-8-sig')
    R.corr().to_csv(out / 'strategy_correlations.csv', encoding='utf-8-sig')
    R.loc['2026-01':].corr().to_csv(out / 'strategy_correlations_2026.csv', encoding='utf-8-sig')
    portfolio = {}
    # 미국 2개(USD)·한국 4개(KRW)를 합친 값은 통화 미통일 진단치다.
    for label, rr in [('six_mixed_currency_diagnostic', R), ('us_two_usd', R[['meritz', 'so']]),
                      ('kr_four_krw', R[['ko', 'pen', 'ssopen', 'mamtax']])]:
        b = rr.mean(axis=1)
        portfolio[label] = {'base': {q: stats(z) for q, z in [('full', b), ('pre2026', b.loc[:'2025-12']), ('y2026', b.loc['2026-01':])]}}
    # 단순 비교기준: 국내는 나스닥/코스피 반반, 미국은 SPY/GLD 반반.
    benchmarks = {}
    for key, name, p, signal, livefn in cfg:
        start = pd.Period(results[key]['checks']['comparison_start'], 'M')
        q = us if key in ['meritz', 'so'] else cfg[3][2]
        for label, assets in ([('spy_gld_50_50', ['SPY', 'GLD']), ('qqq_hold', ['QQQ'])] if key in ['meritz', 'so'] else [('nasdaq_kospi_50_50', ['133690', '102110']), ('nasdaq_hold', ['133690'])]):
            vw = pd.DataFrame(0., index=q.index, columns=q.columns)
            vw.loc[:, assets] = 1 / len(assets)
            bt = simulate(q, vw, start)
            benchmarks[f'{key}:{label}'] = {'full': stats(bt.net), 'pre2026': stats(bt.loc[:'2025-12', 'net']), 'y2026': stats(bt.loc['2026-01':, 'net'])}
    pd.DataFrame(summary_rows).to_csv(out / 'summary.csv', encoding='utf-8-sig', index=False)
    pd.DataFrame(month_rows).to_csv(out / 'baseline_2026_attribution.csv', encoding='utf-8-sig', index=False)
    marker = src / 'SOURCE_COMMIT.txt'
    source_commit = marker.read_text(encoding='utf-8-sig').strip() if marker.exists() else 'not recorded'
    (out / 'results.json').write_text(json.dumps(dict(source_commit=source_commit, cutoff=str(cutoff), input_sha256=input_hash.hexdigest(),
          strategies=results, portfolios=portfolio, benchmarks=benchmarks, latest=latest), ensure_ascii=False, indent=2), encoding='utf-8')
    print('AUDIT_OK: live return reconciliation, causal signal prefixes, aligned continuous periods', flush=True)


if __name__ == '__main__':
    main()
