"""월별 원자료에서 코스피 방어 현금의 인버스 전환을 재구성한다."""

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from kospi_inverse_20261121 import END, HISTORY, INTEGRATED, LONG, read_daily, score
from kospi_inverse2x_20261121 import check_compounding

FIRST = '1997-01'
LISTING = pd.Timestamp('2009-09-16')
WINDOWS = {
    '전체': (FIRST, END),
    '1997~2013': (FIRST, '2013-12'),
    '상장 전 합성': (FIRST, '2009-08'),
    '상장 후 실제 ETF': ('2009-10', END),
    '초기 실제 ETF': ('2009-10', '2013-12'),
    '2014년 이후': ('2014-01', END),
    '2014~2019': ('2014-01', '2019-12'),
    '2020년 이후': ('2020-01', END),
}


def generate_signals(stocks, kospi, gold):
    rows = []
    previous_breadth = False
    for month, basket in stocks.groupby('투자월'):
        assert len(basket) == 200 and basket['종목코드'].is_unique and basket['종목선정일'].nunique() == 1
        selection = pd.Timestamp(basket['종목선정일'].iat[0])
        previous_month = pd.Period(month, freq='M') - 1
        assert selection.to_period('M') == previous_month
        recent = kospi.loc[:selection].tail(120)
        assert len(recent) == 120 and recent.index[-1] == selection
        below_kospi = bool(recent.iat[-1] < recent.mean())
        neg1 = int(basket['1개월(%)'].lt(0).sum())
        neg3 = int(basket['3개월(%)'].lt(0).sum())
        breadth = neg1 >= 100 and neg3 >= 100
        direct = breadth or below_kospi
        extension = previous_breadth and not direct
        gold_window = gold.reindex(pd.period_range(end=previous_month, periods=6, freq='M').astype(str))
        assert gold_window.notna().all()
        below_gold = bool(gold_window.iat[-1] < gold_window.mean())
        rows.append(dict(
            투자월=month, selection=str(selection.date()), kospi_price=recent.iat[-1], kospi_ma120=recent.mean(),
            neg1=neg1, neg3=neg3, kospi_below=below_kospi, breadth=breadth, direct=direct,
            extension=extension, gold_previous=gold_window.iat[-1], gold_ma6=gold_window.mean(),
            gold_below=below_gold,
        ))
        previous_breadth = breadth
    return pd.DataFrame(rows).set_index('투자월')


def monthly_inverse(index, etf):
    assert etf.index[0] == LISTING and etf.index[-1] == pd.Timestamp('2026-10-30')
    assert index.loc[LISTING:etf.index[-1]].index.equals(etf.index)
    pre_factors = (1 - index.pct_change().dropna().loc[:LISTING]) * np.exp(-.0064 / 252)
    actual_factors = etf.div(etf.shift()).dropna()
    factors = pd.concat([pre_factors, actual_factors])
    assert factors.index.is_unique and factors.gt(0).all()
    inverse = factors.groupby(factors.index.to_period('M').astype(str)).prod().sub(1)
    actual = etf.groupby(etf.index.to_period('M').astype(str)).last().pct_change().dropna()
    pd.testing.assert_series_equal(inverse.reindex(actual.index), actual, atol=1e-12, rtol=1e-12)
    return inverse


def run(study, output):
    sys.path.insert(0, str((study / 'main-study').resolve()))
    from unittest.mock import patch
    from utils import calculator as live

    stocks = pd.read_csv(LONG / 'monthly_price_data.csv', dtype={'종목코드': str})
    stocks = stocks[stocks['투자월'].le(END)].copy()
    stocks['시가총액(억)'] = (stocks['시가총액'] / 1e8).round()
    fill = [f'{n}개월(%)' for n in (1, 3, 6, 12)] + ['이번달수익률']
    stocks[fill] = stocks[fill].fillna(0)
    kospi = read_daily(HISTORY / 'kospi_daily.csv')
    gold = pd.read_csv(HISTORY / 'gold_monthly.csv', index_col=0)
    inv = monthly_inverse(read_daily(study / 'kospi200_daily.csv'), read_daily(study / 'etf.csv'))
    signal = generate_signals(stocks, kospi, gold.price)
    with patch.object(live, '_load_kospi_index', return_value=kospi.to_frame()), \
            patch.object(live, 'get_gold_krw_monthly', return_value=gold), \
            patch.object(live, 'get_gold_timing_for_backtest', live.get_gold_timing_for_backtest.__wrapped__):
        _, _, engine = live.run_backtest_k200(stocks, 1996, 2026, 6, True, (1, 6), (1, 2), 30, 30,
            trading_cost_pct=.25, gold_returns=gold.ret.to_dict(), use_gold=True, use_gold_ma=True, gold_ma_months=6)
    engine = engine.set_index('투자월')
    signal = signal.loc[FIRST:].copy()
    engine = engine.reindex(signal.index)
    assert signal.index.tolist() == pd.period_range(FIRST, END, freq='M').astype(str).tolist()
    defense = signal.direct | signal.extension
    buy_gold = defense & ~signal.gold_below
    buy_inverse = signal.direct & signal.gold_below
    assert not (buy_inverse & signal.extension).any()
    np.testing.assert_array_equal(defense, ~engine.invested)
    np.testing.assert_array_equal(buy_gold, engine['방어자산'].eq('금'))

    prior = pd.read_csv(study / 'results/long_monthly.csv', index_col=0)
    np.testing.assert_array_equal(signal.kospi_below, prior.kospi_below)
    np.testing.assert_array_equal(signal.extension, prior.reason.fillna('').str.startswith('하락장 연장'))
    np.testing.assert_allclose(inv.reindex(signal.index), prior.inv_ret, atol=1e-12, rtol=1e-12)
    gold_ret = gold.price.pct_change().reindex(signal.index)
    np.testing.assert_allclose(gold_ret, prior.gold_ret, atol=1e-12, rtol=1e-12)
    attack_gross = engine[f'{INTEGRATED} · 공격시_수익률(%)'].div(100).add(.005)
    inv = inv.reindex(signal.index)
    signal['현행 자산'] = np.select([~defense, buy_gold], ['주식', '금'], default='현금')
    signal['후보 자산'] = np.select([~defense, buy_gold, buy_inverse], ['주식', '금', '인버스'], default='현금')
    signal['인버스 총수익률'] = inv
    summaries = []
    for one_way in (.10, .25, .50):
        cost = one_way * .02
        baseline = (buy_gold * (gold_ret - cost)).where(defense, attack_gross - cost)
        candidate = baseline.where(~buy_inverse, inv - cost)
        if one_way == .25:
            prior_candidate = prior['현행 금/현금'].where(
                ~prior.defense | prior.current_gold | prior.reason.fillna('').str.startswith('하락장 연장'),
                prior.inv_ret - .005,
            )
            np.testing.assert_allclose(baseline, engine[INTEGRATED].div(100), atol=1e-12, rtol=1e-12)
            np.testing.assert_allclose(candidate, prior_candidate, atol=1e-12, rtol=1e-12)
            signal['현행 순수익률'] = baseline
            signal['후보 순수익률'] = candidate
        for period, (lo, hi) in WINDOWS.items():
            invested = buy_inverse.loc[lo:hi]
            for name, series in [('현행', baseline), ('후보', candidate)]:
                r = series.loc[lo:hi]
                result = score(r)
                check_compounding(r, result)
                summaries.append(dict(period=period, cost_pct=one_way, policy=name, months=len(r),
                    inverse_months=int(invested.sum()) if name == '후보' else 0,
                    inverse_wins=int((invested & (inv.loc[lo:hi] > cost)).sum()) if name == '후보' else 0, **result))
    signal.to_csv(output / 'monthly-audit.csv', encoding='utf-8-sig')
    pd.DataFrame(summaries).to_csv(output / 'results.csv', index=False, encoding='utf-8-sig')
    print(f'Reproduced {len(signal)} monthly signals and returns and checked {len(summaries)} statistics.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-study', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args.previous_study, args.output)


if __name__ == '__main__':
    main()
