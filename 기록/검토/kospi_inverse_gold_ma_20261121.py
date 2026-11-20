"""코스피200 인버스 조건 분해와 금 MA 1~12개월 비교."""

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import kospi_inverse_20261121 as previous

COST_PCT = .25
ROUND_TRIP = .005
DAILY_GOLD = previous.ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정/gold_daily_combined.csv'
WINDOWS = {**previous.WINDOWS, '2010~2026-10 실물': ('2010-01', previous.END)}
PORTFOLIOS = (previous.INTEGRATED, previous.ENSEMBLE)
EXPECTED_PRIOR = {
    '기존 금·현금': '현행 금/현금',
    '코스피선 아래면 무조건 인버스': '코스피 120일선 아래만 인버스100',
    '금선 아래면 인버스': '금 유지·현금만 인버스100',
    '금·코스피 두 선 아래면 인버스': '금 유지·현금만 인버스100(코스피 120일선 아래)',
    '금·코스피 두 선 아래면 인버스50': '금 유지·현금만 인버스50(코스피 120일선 아래)',
}


def regimes(stocks, detail, weak_index):
    cap = '시가총액(억)' if '시가총액(억)' in stocks else '시가총액'
    breadth = {}
    for month, frame in stocks.groupby('투자월'):
        top = frame.sort_values(cap, ascending=False).head(200)
        breadth[month] = (top['1개월(%)'].lt(0).sum() >= 100 and top['3개월(%)'].lt(0).sum() >= 100)
    broad = pd.Series(breadth, dtype=bool).reindex(detail.index)
    raw_defense = broad | weak_index
    extension = ~raw_defense & broad.shift(1, fill_value=False)
    defense = raw_defense | extension
    np.testing.assert_array_equal(defense.to_numpy(), (~detail.invested).to_numpy())
    labels = pd.Series(np.select(
        [broad & weak_index, weak_index, broad, extension],
        ['두 조건', '코스피선만', '하락장만', '하락장 연장'], default='공격',
    ), index=detail.index, name='regime')
    return defense, labels


def gold_signals(stocks, gold, dates, method, months):
    if method == '월말':
        p = gold.price
        ma = p.rolling(months).mean().shift(1).reindex(dates)
        close = p.shift(1).reindex(dates)
    else:
        p = DAILY_GOLD
        daily = pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0].sort_index()
        selection = pd.to_datetime(stocks.groupby('투자월')['종목선정일'].first()).reindex(dates)
        ma = daily.rolling(months * 20).mean().round(2).asof(selection).set_axis(dates)
        close = daily.asof(selection).set_axis(dates)
    assert ma.notna().all() and close.notna().all()
    return close.lt(ma)


def policies(defense, index_weak, gold_weak):
    g = defense & ~gold_weak
    inv = defense & gold_weak
    no_inv = pd.Series(False, index=defense.index)
    return {
        '기존 금·현금': (defense, g, no_inv),
        '코스피선 아래면 무조건 인버스': (defense, g & ~index_weak, index_weak),
        '금선 아래면 인버스': (defense, g, inv),
        '금·코스피 두 선 아래면 인버스': (defense, g, inv & index_weak),
        '금·코스피 두 선 아래면 인버스50': (defense, g, (inv & index_weak) * .5),
        '하락장 필터 제외, 코스피선 아래면 인버스': (index_weak, no_inv, index_weak),
        '하락장 필터 제외, 코스피선 아래 금·현금': (index_weak, g & index_weak, no_inv),
        '하락장 필터 제외, 코스피선 아래 금·인버스': (index_weak, g & index_weak, inv & index_weak),
    }


def evaluate(stocks, detail, index_weak, gold, inverse, reference, book, scratch):
    defense, labels = regimes(stocks, detail, index_weak)
    gold_ret = gold.ret.div(100).sub(ROUND_TRIP)
    inv_ret = inverse.pct_change().sub(ROUND_TRIP)
    metrics, events = [], []
    for method, start in [('월말', '1997-01'), ('일봉', '2010-01')]:
        dates = detail.loc[start:].index
        frames = []
        d, k, g_ret, i_ret = (s.reindex(dates) for s in (defense, index_weak, gold_ret, inv_ret))
        assert g_ret.notna().all() and i_ret.notna().all()
        for ma in range(1, 13):
            gold_weak = gold_signals(stocks, gold, dates, method, ma)
            if method == '월말' and ma == 6:
                pd.testing.assert_series_equal(
                    d & ~gold_weak, detail['방어자산'].reindex(dates).eq('금'), check_names=False,
                )
            for name, (d_mode, g, i) in policies(d, k, gold_weak).items():
                assert ((g.astype(float) + i.astype(float)) <= d_mode.astype(float)).all()
                defense_return = g.astype(float) * g_ret + i.astype(float) * i_ret
                for field in PORTFOLIOS:
                    attack = detail[f'{field} · 공격시_수익률(%)'].reindex(dates).div(100)
                    ret = defense_return.where(d_mode, attack)
                    if method == '월말' and ma == 6:
                        if name == '기존 금·현금':
                            np.testing.assert_allclose(ret, detail[field].reindex(dates).div(100), atol=1e-12)
                        if name in EXPECTED_PRIOR and field == previous.INTEGRATED:
                            np.testing.assert_allclose(ret, reference[EXPECTED_PRIOR[name]].reindex(dates), atol=1e-12)
                    if field == previous.INTEGRATED:
                        frames.append(pd.DataFrame({
                            'method': method, 'gold_ma': ma, 'policy': name, 'return': ret,
                            'inv_weight': i.astype(float), 'gold_weight': g.astype(float),
                            'gold_weak': gold_weak, 'defense': d_mode,
                        }))
                    for window, (first, last) in WINDOWS.items():
                        if first < dates[0]:
                            continue
                        active = i.loc[first:last].gt(0)
                        values = ret.loc[first:last]
                        metrics.append(dict(
                            book=book, strategy=field, method=method, gold_ma=ma, policy=name, window=window,
                            months=len(values), gold_months=int(g.loc[first:last].sum()),
                            inverse_months=int(active.sum()), inverse_positive=int((active & i_ret.loc[first:last].gt(0)).sum()),
                            **previous.score(values),
                        ))
            if ma == 6:
                frames6 = pd.DataFrame({
                    'regime': labels.reindex(dates), 'gold_weak': gold_weak,
                    'gold_net': g_ret, 'inv_net': i_ret,
                })
                for window, (first, last) in WINDOWS.items():
                    if first < dates[0]:
                        continue
                    sample = frames6.loc[first:last].query('regime != "공격"')
                    for (regime, weak), group in sample.groupby(['regime', 'gold_weak']):
                        events.append(dict(book=book, method=method, window=window, regime=regime, gold_weak=weak,
                                           n=len(group), inverse_win=int(group.inv_net.gt(0).sum()),
                                           inverse_avg=group.inv_net.mean()*100, gold_avg=group.gold_net.mean()*100,
                                           avg_vs_current=(group.inv_net - group.gold_net * (not weak)).mean()*100))
        pd.concat(frames).to_csv(scratch / f'{book}_{method}_월별.csv', encoding='utf-8-sig')
    return metrics, events


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--previous-study', type=Path, required=True)
    args.add_argument('--output', type=Path, required=True)
    args = args.parse_args()
    study = args.previous_study
    args.output.mkdir(parents=True, exist_ok=True)
    live = study / 'main-study'
    sys.path.insert(0, str(live.resolve()))
    from utils import calculator as c
    from utils.data_loader import load_archive_data

    index = previous.read_daily(previous.HISTORY / 'kospi_daily.csv')
    gold = pd.read_csv(previous.HISTORY / 'gold_monthly.csv', index_col=0)
    etf = previous.read_daily(study / 'etf.csv').loc[:'2026-10-31']
    k200 = previous.read_daily(study / 'kospi200_daily.csv')
    inverse = previous.month_end(previous.inverse_prices(k200, etf, .0064))
    daily = pd.read_csv(DAILY_GOLD, index_col=0, parse_dates=True).iloc[:, 0].sort_index()
    np.testing.assert_allclose(
        previous.month_end(daily).pct_change().loc['2010-01':previous.END],
        gold.ret.div(100).loc['2010-01':previous.END], atol=1e-12,
    )

    long = pd.read_csv(previous.LONG / 'monthly_price_data.csv', dtype={'종목코드': str})
    long['시가총액(억)'] = (long['시가총액'] / 1e8).round()
    cols = [f'{m}개월(%)' for m in (1, 3, 6, 12)] + ['이번달수익률']
    long[cols] = long[cols].fillna(0)
    archive = load_archive_data.__wrapped__(str(live.resolve() / 'archive_kospi'))
    metrics, regimes_summary = [], []
    for name, source in [('long', long), ('archive', archive)]:
        source = source[source['투자월'].le(previous.END)].copy()
        detail, index_weak = previous.load_baseline(c, source, index, gold, COST_PCT)
        reference = pd.read_csv(study / 'results' / f'{name}_monthly.csv', index_col=0)
        m, r = evaluate(source, detail, index_weak, gold, inverse, reference, name, args.output)
        metrics.extend(m)
        regimes_summary.extend(r)
    pd.DataFrame(metrics).to_csv(args.output / 'results.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(regimes_summary).to_csv(args.output / 'regimes.csv', index=False, encoding='utf-8-sig')
    print(f'Reproduced the previous six-month baseline and four inverse variants on both datasets. {len(metrics)} result rows.')


if __name__ == '__main__':
    main()
