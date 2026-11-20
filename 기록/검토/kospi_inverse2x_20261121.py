"""코스피선 위 방어월의 1배·2배 인버스 비교."""

import argparse
from decimal import Decimal, localcontext
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from kospi_inverse_20261121 import month_end, read_daily, score

BASELINE = '현행 금/현금'
COST = .005
WINDOWS = {
    '1997~2026-10': ('1997-01', '2026-10'),
    '1997~2013': ('1997-01', '2013-12'),
    '2014~2026-10': ('2014-01', '2026-10'),
    '2014-02~2026-10': ('2014-02', '2026-10'),
    '2016-10~2026-10 두 ETF 실물': ('2016-10', '2026-10'),
    '2016-10~2019 두 ETF 실물': ('2016-10', '2019-12'),
    '2020~2026-10 두 ETF 실물': ('2020-01', '2026-10'),
}


def leveraged_prices(index, etf2x):
    listing = etf2x.index[0]
    assert listing == pd.Timestamp('2016-09-22') and listing in index.index
    assert index.loc[listing:etf2x.index[-1]].index.equals(etf2x.index)
    factor = 1 - 2 * index.loc[:listing].pct_change().fillna(0)
    assert factor.gt(0).all()
    synthetic = factor.cumprod() * np.exp(-.0064 * np.arange(len(factor)) / 252)
    return pd.concat([synthetic.iloc[:-1], etf2x * (synthetic.iloc[-1] / etf2x.iloc[0])])


def classify(frame):
    reason = frame.reason.fillna('')
    extension = reason.str.startswith('하락장 연장')
    breadth = reason.str.startswith('하락장') & ~extension
    above = ~frame.kospi_below
    assert (above | ~extension).all()
    breadth_only = breadth & above
    return {
        '하락장만': breadth_only,
        '하락장 후 연장': extension,
        '하락장만 또는 연장': breadth_only | extension,
        '코스피선 이탈': frame.kospi_below,
    }


def check_compounding(values, result):
    with localcontext() as ctx:
        ctx.prec = 45
        peak = wealth = Decimal(1)
        mdd = Decimal(0)
        for value in values:
            wealth *= 1 + Decimal(str(value))
            peak = max(peak, wealth)
            mdd = min(mdd, wealth / peak - 1)
        cagr = (wealth ** (Decimal(12) / len(values)) - 1) * 100
        assert abs(float(cagr) - result['cagr']) < 1e-10
        assert abs(float(mdd) * 100 - result['mdd']) < 1e-10


def calculate(book, frame, inverse2, prior):
    nets = {'인버스100': frame.inv_ret - COST, '곱버스100': inverse2 - COST,
            '곱버스50·현금50': (inverse2 - COST) * .5}
    base = frame[BASELINE]
    masks = classify(frame)
    np.testing.assert_array_equal(frame.defense, masks['하락장만 또는 연장'] | masks['코스피선 이탈'])
    returns, metrics, events = {}, [], []
    for tag, regime in masks.items():
        for rule, active in [('무조건', regime), ('금선 아래 현금만', regime & ~frame.current_gold)]:
            assert not (active & ~frame.defense).any()
            for asset, net in nets.items():
                name = f'{tag} / {rule} / {asset}'
                values = base.where(~active, net)
                assert values.loc[~active].equals(base.loc[~active])
                returns[name] = values
                if asset in ('인버스100', '곱버스100'):
                    change = pd.DataFrame({
                        'book': book, 'regime': tag, 'rule': rule, 'asset': asset,
                        'gold_held': frame.current_gold, 'current': base,
                        'replacement': net, 'delta': net - base,
                    }).loc[active].reset_index()
                    events.append(change)
                for window, (start, end) in WINDOWS.items():
                    if start < frame.index[0]:
                        continue
                    sel = active.loc[start:end]
                    r = values.loc[start:end]
                    active_net = net.loc[start:end].loc[sel]
                    net_extra = active_net - base.loc[active_net.index]
                    summary = score(r)
                    check_compounding(r, summary)
                    base_score = score(base.loc[start:end])
                    if asset == '인버스100' and tag in ('하락장만', '하락장 후 연장'):
                        old_tag = '하락장 연장' if tag == '하락장 후 연장' else tag
                        old_rule = '금선 아래만' if rule == '금선 아래 현금만' else rule
                        old_key = (book, window, old_tag, old_rule)
                        if old_key in prior.index:
                            old = prior.loc[old_key]
                            assert int(sel.sum()) == int(old.n)
                            np.testing.assert_allclose([summary['cagr'], summary['mdd']], [old.cagr, old.mdd], atol=1e-10)
                    metrics.append(dict(
                        book=book, window=window, regime=tag, rule=rule, asset=asset, window_months=len(r),
                        active_months=int(sel.sum()), positive_months=int(active_net.gt(0).sum()),
                        active_mean_pct=active_net.mean()*100, active_worst_pct=active_net.min()*100,
                        avg_delta_vs_current_pct=net_extra.mean()*100,
                        baseline_cagr=base_score['cagr'], baseline_mdd=base_score['mdd'], **summary,
                    ))
    return metrics, frame[[BASELINE, 'reason', 'current_gold', 'kospi_below', 'inv_ret']].assign(
        inv2x_ret=inverse2).join(pd.DataFrame(returns)), pd.concat(events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-study', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    study = args.previous_study
    args.output.mkdir(parents=True, exist_ok=True)
    etf2x_path = study / 'etf2x.csv'
    etf2x = read_daily(etf2x_path)
    index = read_daily(study / 'kospi200_daily.csv')
    inverse2 = month_end(leveraged_prices(index, etf2x)).pct_change()
    actual = month_end(etf2x).pct_change().dropna()
    np.testing.assert_allclose(inverse2.loc[actual.index], actual, atol=1e-12)
    synthetic = month_end((1 - 2 * index.pct_change().fillna(0)).cumprod()).pct_change().loc[actual.index]
    print(f'252670 SHA256 {hashlib.sha256(etf2x_path.read_bytes()).hexdigest()}')
    print(f'ETF and synthetic: {len(actual)} months; correlation {actual.corr(synthetic):.4f}; '
          f'mean absolute difference {(actual-synthetic).abs().mean()*100:.3f} percentage points')
    prior = pd.read_csv(study / 'gold-ma/exclusive-regimes.csv').set_index(['book', 'window', 'regime', 'mode'])
    metrics, events = [], []
    for book in ('long', 'archive'):
        frame = pd.read_csv(study / f'results/{book}_monthly.csv', index_col=0)
        rows, monthly, detail = calculate(book, frame, inverse2.reindex(frame.index), prior)
        monthly.to_csv(args.output / f'{book}_monthly.csv', encoding='utf-8-sig')
        metrics.extend(rows)
        events.append(detail)
    pd.DataFrame(metrics).to_csv(args.output / 'results.csv', index=False, encoding='utf-8-sig')
    pd.concat(events).to_csv(args.output / 'events.csv', index=False, encoding='utf-8-sig')
    print(f'Passed {len(metrics)} independent CAGR/MDD checks and the previous 1× benchmark.')


if __name__ == '__main__':
    main()
