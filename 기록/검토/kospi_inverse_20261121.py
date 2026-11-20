"""코스피200 월간 전략의 방어 자산 비교. 입력 가격과 운영 사본은 명시적으로 전달한다."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LONG = ROOT / '기록/2026-11-10-KOSPI-최장기간-재구성입력'
HISTORY = ROOT / '기록/2026-11-06-KOSPI-1996-202610-검산'
INTEGRATED = '통합 전략 (중복 제외 1/N)'
ENSEMBLE = '앙상블 (50:50 전략)'
END = '2026-10'
WINDOWS = {
    '1997~2026-10': ('1997-01', END),
    '1997~2013': ('1997-01', '2013-12'),
    '1997~2009-08 합성': ('1997-01', '2009-08'),
    '2010~2013 실물': ('2010-01', '2013-12'),
    '2014~2026-10': ('2014-01', END),
    '2014-02~2026-10': ('2014-02', END),
    '2014~2019': ('2014-01', '2019-12'),
    '2020~2026-10': ('2020-01', END),
    '2014~2024': ('2014-01', '2024-12'),
}


def read_daily(path):
    close = pd.read_csv(path, index_col='Date', parse_dates=True)['Close'].sort_index()
    assert close.index.is_unique and close.gt(0).all(), path
    return close


def month_end(close):
    result = close.groupby(close.index.to_period('M').astype(str)).last()
    assert result.index.tolist() == pd.period_range(result.index[0], result.index[-1], freq='M').astype(str).tolist()
    return result


def inverse_prices(index, etf, fee):
    join = etf.index[0]
    assert join == pd.Timestamp('2009-09-16') and join in index.index
    synthetic = (1 - index.loc[:join].pct_change().fillna(0)).cumprod()
    synthetic *= np.exp(-fee * np.arange(len(synthetic)) / 252)
    return pd.concat([synthetic.iloc[:-1], etf * (synthetic.iloc[-1] / etf.iloc[0])])


def load_baseline(c, stocks, index, gold, cost_pct):
    with patch.object(c, '_load_kospi_index', return_value=index.to_frame()), \
            patch.object(c, 'get_gold_krw_monthly', return_value=gold):
        below = c.get_kospi_timing_for_backtest(6, stocks)
        gold_signal = c.get_gold_timing_for_backtest.__wrapped__(6)
        with patch.object(c, 'get_kospi_timing_for_backtest', return_value=below), \
                patch.object(c, 'get_gold_timing_for_backtest', return_value=gold_signal):
            _, _, detail = c.run_backtest_k200(
                stocks, 1996, 2026, 6, True, (1, 6), (1, 2), 30, 30,
                trading_cost_pct=cost_pct, gold_returns=gold.ret.to_dict(),
                use_gold=True, use_gold_ma=True, gold_ma_months=6,
            )
    detail = detail.set_index('투자월')
    assert detail.index.tolist() == pd.period_range(detail.index[0], END, freq='M').astype(str).tolist()
    assert set(detail.index) == set(below)
    return detail, pd.Series(below, dtype=bool).reindex(detail.index)


def allocations(frame):
    gold = frame.current_gold.astype(float)
    weak = frame.kospi_below.astype(float)
    cash = 1 - gold
    zero = gold * 0
    one = zero + 1
    only = frame.inv_mom6.gt(0).astype(float)
    candidates = {
        '현행 금/현금': (gold, zero),
        '현금만': (zero, zero),
        '인버스만': (zero, one),
        '금50+인버스50 고정': (one * .5, one * .5),
        '금75+인버스25 고정': (one * .75, one * .25),
        '금 보유월만 금50+인버스50': (gold * .5, gold * .5),
        '금 유지·현금만 인버스100': (gold, cash),
        '금 유지·현금만 인버스50': (gold, cash * .5),
        '금 유지·현금만 인버스100(코스피 120일선 아래)': (gold, cash * weak),
        '금 유지·현금만 인버스50(코스피 120일선 아래)': (gold, cash * weak * .5),
        '금 유지·현금만 인버스100(인버스 6M 양수)': (gold, cash * only),
        '코스피 120일선 아래만 인버스100': (gold * (1 - weak), weak),
        '코스피 120일선 아래만 금/현금50+인버스50': (gold * (1 - weak * .5), weak * .5),
        '인버스 6M 양수면 인버스, 그 외 현행': (gold * (1 - only), only),
        '코스피 6M 수익 음수일 때만 인버스100': (
            gold * frame.kospi_mom6.ge(0), frame.kospi_mom6.lt(0).astype(float)),
    }
    for m in (3, 6, 12):
        g = frame[f'gold_mom{m}']
        i = frame[f'inv_mom{m}']
        gold_won = g.ge(i)
        candidates[f'{m}M 우위, 양수만'] = ((gold_won & g.gt(0)).astype(float), (~gold_won & i.gt(0)).astype(float))
    g, i = frame.gold_mom6, frame.inv_mom6
    candidates['6M 우위(음수 허용)'] = (g.ge(i).astype(float), i.gt(g).astype(float))
    candidates['6M 우위, 양수만(인버스는 코스피 120일선 아래)'] = (
        (g.gt(0) & (g.ge(i) | weak.eq(0))).astype(float),
        (i.gt(0) & i.gt(g) & weak.eq(1)).astype(float),
    )
    return {name: (gw.where(frame.defense, 0), iw.where(frame.defense, 0)) for name, (gw, iw) in candidates.items()}


def score(returns):
    assert (returns > -1).all() and returns.notna().all()
    multiples = np.r_[1, (1 + returns).cumprod().to_numpy()]
    drawdown = multiples / np.maximum.accumulate(multiples) - 1
    trough = int(drawdown.argmin())
    peak = int(multiples[:trough + 1].argmax())
    log_growth = sum(np.log1p(returns))
    assert abs(np.exp(log_growth) / multiples[-1] - 1) < 1e-12
    return dict(cagr=np.expm1(log_growth * 12 / len(returns)) * 100, mdd=drawdown.min() * 100,
                worst_month=returns.min() * 100, peak=returns.index[peak - 1] if peak else 'start',
                trough=returns.index[trough - 1] if trough else 'start')


def evaluate(detail, below, index, gold, inverse, cost_pct, field, book):
    frame = pd.DataFrame(index=detail.index).loc['1997-01':].copy()
    frame['defense'] = ~detail.invested
    frame['current_gold'] = detail['방어자산'].eq('금')
    frame['kospi_below'] = below
    frame['reason'] = detail['중지 사유'].fillna('')
    frame['kospi_mom6'] = month_end(index).pct_change(6).shift(1)
    for name, prices in [('gold', gold.price), ('inv', month_end(inverse))]:
        frame[f'{name}_ret'] = prices.pct_change()
        for m in (3, 6, 12):
            frame[f'{name}_mom{m}'] = prices.pct_change(m).shift(1)
    assert frame.drop(columns='reason').notna().all().all()
    attack = detail[field].div(100).reindex(frame.index)
    cost = 2 * cost_pct / 100
    out, weights, stats = {}, {}, []
    for name, (gw, iw) in allocations(frame).items():
        assert ((gw >= 0) & (iw >= 0) & (gw + iw <= 1)).all()
        net = gw * (frame.gold_ret - cost) + iw * (frame.inv_ret - cost)
        returns = net.where(frame.defense, attack)
        if name == '현행 금/현금':
            pd.testing.assert_series_equal(returns, attack, check_names=False, atol=1e-12, rtol=1e-12)
        else:
            assert returns.loc[~frame.defense].equals(attack.loc[~frame.defense])
        out[name] = returns
        weights[name] = iw
        for period, (start, end) in WINDOWS.items():
            if start < frame.index[0]:
                continue
            r = returns.loc[start:end]
            month = frame.loc[start:end]
            iw_r = iw.loc[start:end]
            active = iw_r.gt(0)
            stats.append(dict(book=book, strategy=field, cost_pct=cost_pct, window=period, variant=name,
                              n=len(r), n_def=int(month.defense.sum()), n_inv=int(active.sum()),
                              n_inv_positive=int((active & month.inv_ret.gt(cost)).sum()),
                              avg_weight_inv=iw_r.mean() * 100,
                              avg_inv_month=month.inv_ret.loc[active].mean() * 100 - cost * 100,
                              **score(r)))
    return stats, frame.join(pd.DataFrame(out)), pd.DataFrame(weights)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--market', type=Path, required=True, help='etf.csv와 kospi200_daily.csv가 있는 폴더')
    parser.add_argument('--live-root', type=Path, required=True, help='운영 utils/와 archive_kospi/ 사본')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.live_root.resolve()))
    from utils import calculator as c
    from utils.data_loader import load_archive_data

    index = read_daily(HISTORY / 'kospi_daily.csv')
    gold = pd.read_csv(HISTORY / 'gold_monthly.csv', index_col=0)
    etf = read_daily(args.market / 'etf.csv').loc[:'2026-10-31']
    k200 = read_daily(args.market / 'kospi200_daily.csv')
    assert etf.index[-1] == index.index[-1] == pd.Timestamp('2026-10-30')
    assert month_end(etf).index[1] == '2009-10'
    long = pd.read_csv(LONG / 'monthly_price_data.csv', dtype={'종목코드': str})
    long = long[long['투자월'].le(END)].copy()
    long['시가총액(억)'] = (long['시가총액'] / 1e8).round()
    columns = [f'{m}개월(%)' for m in (1, 3, 6, 12)] + ['이번달수익률']
    long[columns] = long[columns].fillna(0)
    archive = load_archive_data.__wrapped__(str(args.live_root.resolve() / 'archive_kospi'))
    archive = archive[archive['투자월'].le(END)].copy()
    all_stats = []
    for book, stocks, fields, costs in [('long', long, (INTEGRATED, ENSEMBLE), (.10, .25, .50)),
                                        ('archive', archive, (INTEGRATED, ENSEMBLE), (.25,))]:
        for cost in costs:
            detail, below = load_baseline(c, stocks, index, gold, cost)
            if book == 'long' and cost == .25:
                previous = pd.read_csv(LONG / 'diagnostic_monthly_returns.csv', index_col='투자월')
                for f in ('invested', INTEGRATED, ENSEMBLE):
                    pd.testing.assert_series_equal(previous[f], detail[f], atol=1e-12, rtol=1e-12)
            sources = [(book, k200, .0064)]
            if book == 'long' and cost == .25:
                sources.extend([('kospi_proxy', index, .0064), ('no_synthetic_fee', k200, 0.),
                                ('higher_synthetic_fee', k200, .015)])
            for source, proxy, fee in sources:
                inverse = inverse_prices(proxy, etf, fee)
                for field in fields:
                    rows, months, weights = evaluate(detail, below, index, gold, inverse, cost, field, source)
                    all_stats.extend(rows)
                    if cost == .25 and field == INTEGRATED and source == book:
                        months.to_csv(args.output / f'{book}_monthly.csv', encoding='utf-8-sig')
                        weights.to_csv(args.output / f'{book}_inverse_weights.csv', encoding='utf-8-sig')
    pd.DataFrame(all_stats).to_csv(args.output / 'results.csv', index=False, encoding='utf-8-sig')
    comparable = pd.concat([month_end(etf).pct_change().rename('etf'), month_end(k200).pct_change().rename('kospi200')], axis=1)
    comparable = comparable.loc['2009-10':].dropna()
    proxy = (1 - k200.pct_change().fillna(0)).cumprod()
    tracking = pd.concat([comparable.etf, month_end(proxy).pct_change().rename('synthetic')], axis=1).loc[comparable.index]
    tracking.to_csv(args.output / 'tracking.csv')
    files = [HISTORY / 'kospi_daily.csv', HISTORY / 'gold_monthly.csv', LONG / 'monthly_price_data.csv',
             args.market / 'etf.csv', args.market / 'kospi200_daily.csv']
    (args.output / 'input_sha256.json').write_text(
        json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2), encoding='utf-8')
    print(f'{len(all_stats)} summary rows. ETF {len(etf)} days, 200 index {len(k200)} days.')


if __name__ == '__main__':
    main()
