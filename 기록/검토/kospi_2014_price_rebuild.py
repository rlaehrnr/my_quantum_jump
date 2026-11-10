"""당시 시총200·월말 가격 기준의 2014년 이후 연구 자료와 보유 예외를 생성한다."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from kospi_overlap_audit import ROOT, MOM, c, normalize_stock_code, reconstruct
from kospi_top4_comparison import stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요.')
    closed_end = '2026-10'
    signal_end = '2026-11'
    data, manifest = reconstruct(args.source_dir, start_month='2014-01', end_month=signal_end,
                                 exclude_zero_volume=False)
    data.loc[data['투자월'].gt(closed_end), ['이번달수익률', 'raw_return']] = float('nan')
    expected = pd.period_range('2014-01', signal_end, freq='M').astype(str).tolist()
    assert data.groupby('투자월').size().index.tolist() == expected
    assert data.groupby('투자월').size().eq(200).all()
    assert not data.duplicated(['투자월', '종목코드']).any()
    roster_path = ROOT / '기록/2026-11-09-KOSPI-2014재구성-기업행동점검/strict_top200.csv'
    roster = pd.read_csv(roster_path, dtype={'Code': str})
    left = data[['투자월', '종목코드', '종목선정일', '순위']].rename(columns={'종목코드': 'Code', '종목선정일': 'Date'})
    right = roster[['투자월', 'Code', 'Date', '순위']]
    pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True), check_dtype=False)
    input_dir = ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정'
    index = pd.read_csv(input_dir / 'source_kospi_complete.csv', index_col=0, parse_dates=True)
    gold = pd.read_csv(input_dir / 'gold_monthly.csv', index_col=0)
    market_months = index.index.to_series().groupby(index.index.to_period('M')).max()
    selected_days = pd.to_datetime(data.groupby('투자월')['종목선정일'].first())
    assert selected_days.tolist() == market_months.reindex(pd.PeriodIndex(expected, freq='M') - 1).tolist()
    assert (index.index.searchsorted(selected_days, side='right') >= 120).all()
    closed = data[data['투자월'].le(closed_end)].copy()
    closed['시가총액(억)'] = (closed['시가총액'] / 1e8).round(0)
    # 기존 엔진의 결측0 입력과 동일하게 신호를 진단하되, 실제 선택된 결측은 아래서 차단한다.
    engine_input = closed.copy()
    engine_input[MOM + ['이번달수익률']] = engine_input[MOM + ['이번달수익률']].fillna(0)
    with patch.object(c, '_load_kospi_index', return_value=index), patch.object(c, 'get_gold_krw_monthly', return_value=gold):
        returns, trades, detail = c.run_backtest_k200(
            engine_input, 2014, 2026, 6, True, (1, 6), (1, 2), 30, 30,
            trading_cost_pct=.25, gold_returns=gold.ret.to_dict(), use_gold=True,
            use_gold_ma=True, gold_ma_months=6)
    assert len(returns) == 154
    selections = trades[trades['전략'].isin(['퍼펙트', '달리는말'])].merge(
        closed, on=['투자월', '종목명'], how='left', validate='many_to_one')
    assert selections['종목코드'].notna().all()
    end_volumes = []
    for year in range(2014, 2027):
        raw = pd.read_parquet(args.source_dir / f'marcap-{year}.parquet', columns=['Date', 'Code', 'Volume', 'MarketId'])
        raw = raw[raw.MarketId.eq('STK') & raw.Date.le(pd.Timestamp('2026-10-31'))].copy()
        raw['Code'] = raw.Code.map({code: normalize_stock_code(code) for code in raw.Code.unique()})
        raw['month'] = raw.Date.dt.to_period('M')
        last_day = raw.groupby('month').Date.transform('max')
        raw = raw[raw.Date.eq(last_day)].copy()
        raw['투자월'] = raw['month'].astype(str)
        end_volumes.append(raw[['투자월', 'Code', 'Volume']])
    monthly_volumes = pd.concat(end_volumes, ignore_index=True).rename(columns={'Code': '종목코드', 'Volume': '보유월말거래량'})
    selections = selections.merge(monthly_volumes, on=['투자월', '종목코드'], how='left', validate='many_to_one')
    selections['매수시거래량0'] = selections['거래량'].eq(0)
    selections['보유월말거래량0'] = selections['보유월말거래량'].eq(0)
    selections['보유월말원천누락'] = selections['보유월말거래량'].isna()
    selections['보유수익결측'] = selections['이번달수익률'].isna()
    unsafe_fields = ['매수시거래량0', '보유월말거래량0', '보유월말원천누락', '보유수익결측']
    unsafe = selections[selections[unsafe_fields].any(axis=1)]
    events = pd.read_csv(ROOT / '기록/2026-11-09-KOSPI-2014재구성-기업행동점검/price_reference_event_candidates.csv', dtype={'Code': str})
    selected_events = events.merge(selections[['투자월', '종목코드', '전략']], left_on=['투자월', 'Code'],
                                  right_on=['투자월', '종목코드'], how='inner', validate='many_to_many')
    dividends = selections[['투자월', '종목코드', '종목명', '전략']].drop_duplicates().copy()
    dividends['현금배당금_주당'] = pd.NA
    dividends['확인상태'] = '미조회'
    dividends['가격수익률합산여부'] = False
    args.output.mkdir(parents=True)
    data['거래량0_체결확인필요'] = data['거래량'].eq(0)
    data['보유월확정'] = data['투자월'].le(closed_end)
    data.to_csv(args.output / 'monthly_price_data.csv', index=False, encoding='utf-8-sig')
    selections.to_csv(args.output / 'selected_positions.csv', index=False, encoding='utf-8-sig')
    unsafe.to_csv(args.output / 'unresolved_selected_positions.csv', index=False, encoding='utf-8-sig')
    selected_events.to_csv(args.output / 'selected_price_events.csv', index=False, encoding='utf-8-sig')
    dividends.to_csv(args.output / 'dividend_collection_queue.csv', index=False, encoding='utf-8-sig')
    missing = closed[closed[MOM + ['이번달수익률']].isna().any(axis=1)]
    missing.to_csv(args.output / 'missing_price_inputs.csv', index=False, encoding='utf-8-sig')
    returns.to_csv(args.output / 'diagnostic_monthly_returns.csv', index=False, encoding='utf-8-sig')
    summary = {'start': '2014-01', 'closed_end': closed_end, 'signal_end': signal_end,
               'rows': len(data), 'closed_months': len(returns), 'dividend_policy': '별도 표시·가격수익률에서 제외',
               'dividend_collection_status': '미조회는 0원 배당을 뜻하지 않음',
               'selected_rows': len(selections), 'unresolved_selected_rows': len(unsafe),
               'selected_event_rows': len(selected_events),
               'selected_event_cases': len(selected_events[['Date', 'Code']].drop_duplicates()),
               'missing_price_input_rows': len(missing), 'source_manifest': manifest,
               'engine_missing_policy': '기존 엔진 비교를 위해 입력만 결측0; 원본 결측 보존·실제 보유 결측은 검토 대상으로 차단',
               'status': '기업행동·체결 예외 및 배당내역 검증 전 연구 초안',
               'stats': {col: stats(returns[col]) for col in returns if col not in ['투자월', 'invested', '중지 사유']} if unsafe.empty else {}}
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_manifest'}, ensure_ascii=False, indent=2))
    print(unsafe[['투자월', '종목코드', '종목명', '전략', *unsafe_fields]].to_string(index=False))
    print(selected_events[['Date', 'Code', 'Name', '전략']].to_string(index=False))


if __name__ == '__main__':
    main()
