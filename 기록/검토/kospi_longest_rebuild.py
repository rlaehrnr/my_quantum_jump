"""확보된 1995년 원천부터 당시 시총200·월말 가격을 재구성하고 예외를 사전 점검한다."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from kospi_overlap_audit import ROOT, MOM, c, normalize_stock_code, reconstruct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요.')
    start, end, signal_end = '1996-06', '2026-10', '2026-11'
    data, manifest = reconstruct(args.source_dir, start_month=start, end_month=signal_end, exclude_zero_volume=False)
    data.loc[data['투자월'].gt(end), ['이번달수익률', 'raw_return']] = float('nan')
    months = pd.period_range(start, signal_end, freq='M').astype(str).tolist()
    assert data.groupby('투자월').size().index.tolist() == months
    assert data.groupby('투자월').size().eq(200).all()
    assert not data.duplicated(['투자월', '종목코드']).any()
    previous = ROOT / '기록/2026-11-06-KOSPI-1996-202610-검산'
    index = pd.read_csv(previous / 'kospi_daily.csv', index_col=0, parse_dates=True)
    gold = pd.read_csv(previous / 'gold_monthly.csv', index_col=0)
    market_days = index.index.to_series().groupby(index.index.to_period('M')).max()
    selections = pd.to_datetime(data.groupby('투자월')['종목선정일'].first())
    assert selections.tolist() == market_days.reindex(pd.PeriodIndex(months, freq='M') - 1).tolist()
    assert (index.index.searchsorted(selections, side='right') >= 120).all()
    assert gold['ret'].reindex(months[:-1]).notna().all()
    prior = pd.read_csv(ROOT / '기록/2026-11-10-KOSPI-2014-가격재구성/monthly_price_data.csv', dtype={'종목코드': str})
    overlap = data[data['투자월'].ge('2014-01')]
    merged = overlap.merge(prior, on=['투자월', '종목코드'], suffixes=('_long', '_prior'), validate='one_to_one')
    assert len(merged) == len(prior)
    fields = MOM + ['이번달수익률']
    max_delta = max((merged[f + '_long'] - merged[f + '_prior']).abs().max() for f in fields)
    assert max_delta <= .011
    closed = data[data['투자월'].le(end)].copy()
    engine = closed.copy()
    engine[MOM + ['이번달수익률']] = engine[MOM + ['이번달수익률']].fillna(0)
    engine['시가총액(억)'] = (engine['시가총액'] / 1e8).round(0)
    with patch.object(c, '_load_kospi_index', return_value=index), patch.object(c, 'get_gold_krw_monthly', return_value=gold):
        baseline, _, details = c.run_backtest_k200(engine, 1996, 2026, 6, True, (1, 6), (1, 2), 30, 30,
            trading_cost_pct=.25, gold_returns=gold.ret.to_dict(), use_gold=True, use_gold_ma=True, gold_ma_months=6)
    assert len(baseline) == 365
    modes = details.set_index('투자월')
    selected = []
    for month, frame in engine.groupby('투자월', sort=True):
        if not bool(modes.loc[month, 'invested']):
            continue
        frame = frame.sort_values('시가총액(억)', ascending=False).head(200)
        for policy in ['next', 'cash']:
            p, s = c.select_kospi200_targets(frame, (1, 6), (1, 2), 30, 30, entry_policy=policy)
            for strategy, picks in [('퍼펙트', p), ('달리는말', s)]:
                for row in picks.to_dict('records'):
                    if not row['_cash']:
                        selected.append({'정책': policy, '투자월': month, '전략': strategy,
                                         '종목코드': row['종목코드'], '종목명': row['종목명']})
    selected = pd.DataFrame(selected).merge(closed[['투자월', '종목코드', '이번달수익률']],
                    on=['투자월', '종목코드'], how='left', validate='many_to_one')
    volume_rows = []
    for year in range(1996, 2027):
        d = pd.read_parquet(args.source_dir / f'marcap-{year}.parquet', columns=['Date', 'Code', 'Volume', 'MarketId'])
        d = d[d.MarketId.eq('STK') & d.Date.le('2026-10-31')].copy()
        d['Code'] = d.Code.map({code: normalize_stock_code(code) for code in d.Code.unique()})
        d['month'] = d.Date.dt.to_period('M').astype(str)
        last = d.groupby('month').Date.transform('max')
        volume_rows.append(d[d.Date.eq(last)][['month', 'Code', 'Volume']])
    volumes = pd.concat(volume_rows, ignore_index=True).rename(columns={'month': '투자월', 'Code': '종목코드'})
    selected = selected.merge(volumes, on=['투자월', '종목코드'], how='left', validate='many_to_one')
    freezes = selected[selected.Volume.eq(0)].drop_duplicates(['투자월', '종목코드'])
    missing = selected[selected['이번달수익률'].isna() | selected.Volume.isna()]
    args.output.mkdir(parents=True)
    data.to_csv(args.output / 'monthly_price_data.csv', index=False, encoding='utf-8-sig')
    baseline.to_csv(args.output / 'diagnostic_monthly_returns.csv', index=False, encoding='utf-8-sig')
    details.to_csv(args.output / 'diagnostic_details.csv', index=False, encoding='utf-8-sig')
    freezes.to_csv(args.output / 'selected_halts.csv', index=False, encoding='utf-8-sig')
    missing.to_csv(args.output / 'selected_missing.csv', index=False, encoding='utf-8-sig')
    summary = {'raw_start': '1995-05-02', 'start': start, 'end': end, 'months': 365,
               'signal_end': signal_end, 'rows': len(data), 'overlap_2014_max_delta_pp': float(max_delta),
               'selected_halt_cases': len(freezes), 'selected_missing_rows': len(missing), 'source_manifest': manifest,
               'status': '시총200·가격 재구성 및 사전 점검; 기업행동·거래정지 정산 후 최종 비교'}
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_manifest'}, ensure_ascii=False), flush=True)
    print(freezes.to_string(index=False), flush=True)
    print('MISSING', missing.to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
