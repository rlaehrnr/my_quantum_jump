"""2014년 이후 당시 시총200 후보군과 거래량0·기업행동 점검 대상을 추출한다.

기업행동 확정 자료나 최종 백테스트를 만들지 않는다. 일별 원천과 기존 연구 자료를
읽어 당시 후보군, 제외 차이, 수익률 결측 및 기준가격 단절 후보를 보존한다.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils.data_loader import normalize_stock_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--end-month', default='2026-10')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요.')
    snapshots, events, manifest = [], [], {}
    complete_end = pd.Period(args.end_month, freq='M')
    raw_last_day = None
    final_observations = {}
    previous_year_close = {}
    columns = ['Date', 'Code', 'Name', 'Close', 'Changes', 'Volume', 'Marcap', 'MarketId']
    for year in range(2013, 2027):
        path = args.source_dir / f'marcap-{year}.parquet'
        d = pd.read_parquet(path, columns=columns)
        source_last = d.Date.max()
        raw_last_day = max(raw_last_day, source_last) if raw_last_day is not None else source_last
        d = d[d.Date.le(complete_end.end_time)].copy()
        d = d[d.MarketId.eq('STK')].copy()
        code_map = {code: normalize_stock_code(code) for code in d.Code.unique()}
        d['Code'] = d.Code.map(code_map)
        d = d[d.Code.str.endswith('0')].sort_values(['Code', 'Date'])
        previous_close = d.groupby('Code').Close.shift(1)
        first = ~d.Code.duplicated()
        previous_close.loc[first] = d.loc[first, 'Code'].map(previous_year_close)
        reference = d.Close - d.Changes
        ratio = reference / previous_close
        # 1% 이상 단절은 검토 후보일 뿐, 기업행동 확정이나 손익 보정값이 아니다.
        event = d[(ratio - 1).abs().gt(.01) & reference.gt(0) & previous_close.gt(0)].copy()
        event['PreviousClose'] = previous_close.loc[event.index]
        event['Reference'] = reference.loc[event.index]
        event['ReferenceRatio'] = ratio.loc[event.index]
        events.append(event)
        previous_year_close = d.groupby('Code').Close.last().to_dict()
        final_observations.update(d.groupby('Code').Date.max().to_dict())
        d['month'] = d.Date.dt.to_period('M')
        last_day = d.groupby('month').Date.transform('max')
        snapshots.append(d[d.Date.eq(last_day)].copy())
        manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot = pd.concat(snapshots, ignore_index=True)
    latest_day = snapshot.Date.max()
    latest_selection_month = latest_day.to_period('M')
    earliest = pd.Period('2013-12', freq='M')
    assert latest_selection_month == complete_end
    index_path = ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정/source_kospi_complete.csv'
    market = pd.read_csv(index_path, index_col=0, parse_dates=True)
    market_days = market.index.to_series().groupby(market.index.to_period('M')).max()
    actual_days = snapshot.groupby('month').Date.max()
    common = pd.period_range(earliest, complete_end, freq='M')
    assert actual_days.reindex(common).tolist() == market_days.reindex(common).tolist()
    rosters, omitted, audit = [], [], []
    for month, d in snapshot.groupby('month'):
        if not earliest <= month <= latest_selection_month:
            continue
        d = d[d.Marcap.gt(0)].sort_values(['Marcap', 'Code'], ascending=[False, True])
        strict = d.head(200).copy()
        tradable = d[d.Volume.gt(0)].head(200)
        assert len(strict) == 200 and strict.Code.nunique() == 200 and strict.Date.nunique() == 1
        strict['투자월'] = str(month + 1)
        strict['순위'] = range(1, 201)
        strict['월말거래량0'] = strict.Volume.eq(0)
        strict['원천최종관측일'] = strict.Code.map(final_observations)
        strict['최근원천에서코드미존재'] = strict['원천최종관측일'].lt(latest_day)
        strict['투자월확정'] = month + 1 <= complete_end
        rosters.append(strict)
        missing = strict[~strict.Code.isin(tradable.Code)]
        omitted.append(missing)
        audit.append({'투자월': str(month + 1), '선정일': str(d.Date.iloc[0].date()),
                      '원시시총200': len(strict), '월말거래량0': int(strict.Volume.eq(0).sum()),
                      '거래량조건에따른교체수': len(missing), '투자월확정': month + 1 <= complete_end})
    roster = pd.concat(rosters, ignore_index=True)
    omitted = pd.concat(omitted, ignore_index=True)
    events = pd.concat(events, ignore_index=True)
    events['투자월'] = events.Date.dt.to_period('M').astype(str)
    events = events.merge(roster[['투자월', 'Code', '순위']], on=['투자월', 'Code'], how='inner', validate='many_to_one')
    old_path = ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정/reconstructed_stocks.csv'
    existing = pd.read_csv(old_path, dtype={'종목코드': str})
    existing = existing[existing['투자월'].between('2014-01', str(complete_end))].copy()
    missing_returns = existing[existing['이번달수익률'].isna()].copy()
    disappeared = roster[roster['최근원천에서코드미존재']].groupby('Code').agg(
        Name=('Name', 'last'), FirstMonth=('투자월', 'min'), LastMonth=('투자월', 'max'),
        RosterMonths=('투자월', 'count'), LastObservation=('원천최종관측일', 'max')).reset_index()
    args.output.mkdir(parents=True)
    for name, frame in [('strict_top200', roster), ('monthly_universe_audit', pd.DataFrame(audit)),
                        ('omitted_by_volume', omitted), ('price_reference_event_candidates', events),
                        ('missing_existing_returns', missing_returns), ('disappeared_code_candidates', disappeared)]:
        frame.to_csv(args.output / f'{name}.csv', index=False, encoding='utf-8-sig')
    summary = {'start': '2014-01', 'last_raw_day': str(raw_last_day.date()),
               'last_confirmed_day': str(latest_day.date()),
               'completed_through': str(complete_end), 'completed_months': int(pd.DataFrame(audit)['투자월확정'].sum()),
               'latest_signal_month': str(latest_selection_month + 1),
               'roster_months': len(audit), 'roster_rows': len(roster),
               'months_changed_by_volume_filter': int(pd.DataFrame(audit)['거래량조건에따른교체수'].gt(0).sum()),
               'rows_excluded_by_volume_filter': len(omitted),
               'disappeared_codes_for_review': len(disappeared), 'price_event_candidates': len(events),
               'missing_existing_forward_rows': len(missing_returns),
               'universe_definition': '당시 KOSPI 보통주 시총200; 거래량0도 포함; 동일 시총은 종목코드 오름차순.',
               'limitations': ['거래량0은 거래정지 확정 정보가 아니며 미체결·매도불가 처리는 별도 검토.',
                               '코드가 사라진 것은 상폐 확정 정보가 아니며 합병·코드교체·시장변경을 조사.',
                               '기업행동·배당·상폐 정산과 미확정 11월의 수익률을 최종 계산하지 않음.',
                               '원천 최종관측일은 사후 점검용이며 과거 종목 선택 조건으로 사용하지 않음.'],
               'source_sha256': manifest}
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_sha256'}, ensure_ascii=False, indent=2))
    examples = roster[roster.Code.isin(['117930', '000030', '004940', '002550', '008560'])]
    print(examples.groupby(['Code', 'Name']).agg(first=('투자월', 'min'), last=('투자월', 'max'), months=('투자월', 'count')).to_string())
    print(missing_returns[['투자월', '종목코드', '종목명']].to_string(index=False))


if __name__ == '__main__':
    main()
