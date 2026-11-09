"""연구 전용: 원격 Git 월봉으로 공격 유니버스와 자산군 한도를 비교한다."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils import snowball as sb


def plain(fn):
    return getattr(fn, '__wrapped__', fn)


def stats(ret):
    r = np.asarray(ret, dtype=float)
    if not len(r):
        return {}
    eq = np.r_[1., np.cumprod(1 + r)]
    sd = r.std()
    return dict(n=len(r), cagr=float(eq[-1] ** (12 / len(r)) - 1),
                mdd=float((eq / np.maximum.accumulate(eq) - 1).min()),
                vol=float(sd * np.sqrt(12)),
                sharpe=float(r.mean() / sd * np.sqrt(12)) if sd else 0.)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--revision', default='origin/main')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    rev = subprocess.check_output(['git', 'rev-parse', args.revision], cwd=ROOT).decode().strip()
    names = subprocess.check_output(['git', 'ls-tree', '-r', '-z', '--name-only', rev], cwd=ROOT).decode().split('\0')
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()

    def load(prefix, code):
        path = next(x for x in names if x.startswith(prefix + code + '_') and x.endswith('.csv'))
        raw = subprocess.check_output(['git', 'show', rev + ':' + path], cwd=ROOT)
        digest.update(path.encode()); digest.update(raw)
        return sb._series_from_csv(pd.read_csv(io.BytesIO(raw), encoding='utf-8-sig')).rename(code)

    original = list(sb.MAMTAX_OFFENSE)
    additions = ['261220', '137610', '148070', '305080']
    codes = list(dict.fromkeys(sb.MAMTAX_ALL + additions))
    p = pd.concat([load('data/snowball_kr/monthly/', c) for c in codes], axis=1).sort_index().loc[:'2026-10']
    us = pd.concat([load('data/snowball/monthly/', c) for c in sb.SIGNAL_ASSETS], axis=1).sort_index().loc[:'2026-10']
    equity = set(original) - {'411060'}
    expanded = original + additions
    replaced = [c for c in original if c not in ['360750', '229200', '371160', '466940']] + additions
    configs = {'base': (original, False), 'expand14': (expanded, False),
               'replace10': (replaced, False), 'expand14_equity3': (expanded, True),
               'replace10_equity3': (replaced, True)}

    def signals(off, cap, prices=p, signals_us=us):
        # 연구 프로세스에서만 변경하고 제품 파일에는 쓰지 않는다.
        saved = sb.MAMTAX_OFFENSE
        sb.MAMTAX_OFFENSE = off
        try:
            s = plain(sb.compute_signals_mamtax)(prices, signals_us)
        finally:
            sb.MAMTAX_OFFENSE = saved
        if cap:
            scores = plain(sb.compute_returns)(prices[off], 12)
            for m, row in s.iterrows():
                if row['defensive'] is None or bool(row['defensive']) or not isinstance(row['holds'], dict):
                    continue
                valid = scores.loc[pd.Period(m)].dropna().sort_values(ascending=False, kind='stable')
                picks, count = [], 0
                for code, score in valid.items():
                    if score < 0 or (code in equity and count == 3):
                        continue
                    picks.append(code)
                    count += int(code in equity)
                    if len(picks) == 5:
                        break
                # 각 슬롯20%. 자산이 부족하면 현금; 양수 종목으로 재집중하지 않음.
                s.at[m, 'holds'] = {c: .2 for c in picks}
        return s

    results, monthly, sigs = {}, {}, {}
    for key, (off, cap) in configs.items():
        sigs[key] = signals(off, cap)
        bt = plain(sb.run_backtest_mamtax)(p, sigs[key]).set_index('hold_month', drop=False)
        monthly[key] = bt
    common = sorted(set.intersection(*(set(b.index) for b in monthly.values())))
    # 누락월을 압축하지 않고 전안이 일치하는 마지막 연속 구간으로 비교한다.
    period = pd.PeriodIndex(common, freq='M')
    gaps = np.flatnonzero(np.diff(period.asi8) != 1)
    common = common[gaps[-1] + 1:] if len(gaps) else common
    for key, (off, cap) in configs.items():
        sig = sigs[key]
        bt = monthly[key].loc[common].copy()
        # 공통 시작월 현금 출발로 비용을 다시 계산하고 월별 사칙연산을 검산한다.
        prev = {}
        rets, contributions, weights = [], [], []
        for nm, row in bt.iterrows():
            m = row.signal_month; h = sig.loc[m, 'holds']
            gross = sum(w * (p.loc[pd.Period(nm), t] / p.loc[pd.Period(m), t] - 1) for t, w in h.items())
            fee = .0025 * sum(max(h.get(t, 0) - prev.get(t, 0), 0) for t in set(h) | set(prev))
            if nm != common[0]:
                assert abs(gross - fee - row.ret_strategy) < 1e-12
            rets.append(gross - fee)
            contributions.append(sum(w for t, w in h.items() if t in equity))
            weights.append(dict(month=nm, **h))
            prev = h
        bt['ret_strategy'] = rets
        bt['equity_weight'] = contributions
        bt.to_csv(out / (key + '_monthly.csv'), index=False, encoding='utf-8-sig')
        pd.DataFrame(weights).fillna(0).to_csv(out / (key + '_weights.csv'), index=False, encoding='utf-8-sig')
        r = bt.set_index('hold_month').ret_strategy
        results[key] = {label: stats(r.loc[lo:hi]) for label, lo, hi in [
            ('full', common[0], common[-1]), ('pre2026', common[0], '2025-12'),
            ('y2026', '2026-01', '2026-10'), ('complete_universe', '2024-11', '2026-10')]}
        results[key]['equity_mean'] = float(np.mean(contributions))
        results[key]['equity100_months'] = int(np.sum(np.array(contributions) > .999))
        results[key]['universe'] = off
        # 미래 가격을 절단해도 과거 선정이 바뀌지 않는지 확인한다.
        cut = pd.Period('2025-12')
        short = signals(off, cap, p.loc[:cut], us.loc[:cut])
        assert short.holds.tolist() == sig.loc[:str(cut)].holds.tolist()
        print(key, json.dumps(results[key], ensure_ascii=False), flush=True)
    asset_returns = p.pct_change(fill_method=None).loc['2024-11':'2026-10']
    asset_returns.corr().to_csv(out / 'correlation_24months.csv', encoding='utf-8-sig')
    base_r = pd.read_csv(out / 'base_monthly.csv', index_col='hold_month').ret_strategy
    comparisons = {}
    for key in configs:
        r = pd.read_csv(out / (key + '_monthly.csv'), index_col='hold_month').ret_strategy
        # 2026 이전 실현위험으로 단순 현금혼합 비중을 한 번 고정한 사후 대조군.
        ratio = min(1., r.loc[:'2025-12'].std() / base_r.loc[:'2025-12'].std())
        comparisons[key] = dict(fixed_weight=float(ratio),
            fixed_full=stats(base_r * ratio), fixed_pre2026=stats(base_r.loc[:'2025-12'] * ratio),
            early=stats(r.loc[:'2020-12']), middle=stats(r.loc['2021-01':'2025-12']),
            latest_holds=sigs[key].iloc[-1]['holds'])
    meta = dict(revision=rev, cutoff='2026-10', input_sha256=digest.hexdigest(),
                start=common[0], end=common[-1], checks='all-month return reconciliation and prefix invariance passed',
                comparisons=comparisons, results=results)
    (out / 'results.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
