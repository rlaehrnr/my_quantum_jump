"""공통 기간·지수·금·기존 엔진으로 원본 아카이브와 월말 재구성 자료를 대조한다."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from kospi_overlap_audit import ROOT, MOM, load_frames, run
from kospi_top4_comparison import stats

START, END = '2014-02', '2026-10'


def endpoint_audit(old, source):
    months = pd.period_range(START, END, freq='M').astype(str).tolist()
    raw = []
    for year in range(2013, 2027):
        path = source / f'marcap-{year}.parquet'
        d = pd.read_parquet(path, columns=['Date', 'Code', 'Close'])
        raw.append(d[d.Code.isin(old['종목코드'].unique())])
    prices = pd.concat(raw, ignore_index=True).sort_values(['Code', 'Date'])
    lookups = {code: (d.Date.to_numpy(), d.Close.to_numpy()) for code, d in prices.groupby('Code')}
    records = []
    for month in months:
        group = old[old['투자월'].eq(month)]
        checks = []
        for row in group.to_dict('records'):
            if row['종목코드'] not in lookups:
                continue
            dates, values = lookups[row['종목코드']]
            base = pd.Timestamp(row['종목선정일'])
            targets = [base, base - pd.DateOffset(months=1),
                       (base.to_period('M') - 1).to_timestamp('M'),
                       base + pd.DateOffset(months=1), pd.Period(month).to_timestamp('M')]
            idx = np.searchsorted(dates, pd.DatetimeIndex(targets).to_numpy(), side='right') - 1
            if (idx < 0).any():
                continue
            observed = pd.DatetimeIndex(dates[idx])
            if observed[0] != base or observed[3].to_period('M') != pd.Period(month) or observed[4].to_period('M') != pd.Period(month):
                continue
            b, prev_day, prev_end, next_day, next_end = values[idx]
            if min(b, prev_day, prev_end, next_day, next_end) <= 0:
                continue
            returns = [(b / prev_day - 1) * 100, (b / prev_end - 1) * 100,
                       (next_day / b - 1) * 100, (next_end / b - 1) * 100]
            actual = [row['1개월(%)'], row['1개월(%)'], row['이번달수익률'], row['이번달수익률']]
            matched = [pd.notna(a) and abs(a - r) < .011 for a, r in zip(actual, returns)]
            checks.append([observed[1] != observed[2], observed[3] != observed[4], *matched])
        table = np.array(checks, dtype=bool).reshape(-1, 6)
        momentum = table[table[:, 0]]
        forward = table[table[:, 1]]
        records.append({'투자월': month, '종목수': len(group), '비교가능종목수': len(table),
                        '1M_비교일다름': len(momentum), '1M_동월일일치': int(momentum[:, 2].sum()),
                        '1M_월말일치': int(momentum[:, 3].sum()), '보유_종료일다름': len(forward),
                        '보유_동월일일치': int(forward[:, 4].sum()), '보유_월말일치': int(forward[:, 5].sum())})
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요.')
    input_dir = ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정'
    old = load_frames(str(ROOT / 'archive_kospi'))
    old['종목코드'] = old['종목코드'].astype(str).str.zfill(6)
    old = old[old['종목코드'].str.endswith('0') & old['투자월'].between(START, END)].copy()
    new = pd.read_csv(input_dir / 'reconstructed_stocks.csv', dtype={'종목코드': str})
    new = new[new['투자월'].between(START, END)].copy()
    expected = pd.period_range(START, END, freq='M').astype(str).tolist()
    assert len(expected) == 153
    assert old.groupby('투자월').size().index.tolist() == new.groupby('투자월').size().index.tolist() == expected
    assert not old.duplicated(['투자월', '종목코드']).any()
    assert not new.duplicated(['투자월', '종목코드']).any()
    index = pd.read_csv(input_dir / 'source_kospi_complete.csv', index_col=0, parse_dates=True)
    gold = pd.read_csv(input_dir / 'gold_monthly.csv', index_col=0)
    assert all(index.index.searchsorted(pd.to_datetime(old['종목선정일']), side='right') >= 120)
    variants = {'old': old, 'reconstructed': new}
    for label, fields in [('old_new_momentum', MOM), ('old_new_forward', ['이번달수익률']),
                          ('old_new_both', MOM + ['이번달수익률'])]:
        d = old.merge(new[['투자월', '종목코드', *fields]], how='left', on=['투자월', '종목코드'],
                      suffixes=('', '_new'), indicator=True, validate='one_to_one')
        for field in fields:
            d.loc[d['_merge'].eq('both'), field] = d.loc[d['_merge'].eq('both'), field + '_new']
        variants[label] = d.drop(columns=['_merge'] + [f + '_new' for f in fields])
    audit = endpoint_audit(old, args.source_dir)
    args.output.mkdir(parents=True)
    audit.to_csv(args.output / 'monthly_endpoint_audit.csv', index=False, encoding='utf-8-sig')
    output_stats = {}
    for name, d in variants.items():
        r, t, detail = run(d, index, gold)
        assert r['투자월'].tolist() == expected
        fields = [col for col in r if col not in ['투자월', 'invested', '중지 사유']]
        assert r[fields].notna().all().all()
        output_stats[name] = {col: stats(r[col]) for col in fields}
        r.to_csv(args.output / f'{name}_monthly.csv', index=False, encoding='utf-8-sig')
        print(name, json.dumps(output_stats[name], ensure_ascii=False), flush=True)
    report = {'start': START, 'end': END, 'months': len(expected), 'stats': output_stats,
              'endpoint_counts': audit.drop(columns='투자월').sum().to_dict(),
              'momentum_anchor_months': audit.loc[audit['1M_동월일일치'] > audit['1M_월말일치'], '투자월'].tolist(),
              'holding_anchor_months': audit.loc[audit['보유_동월일일치'] > audit['보유_월말일치'], '투자월'].tolist(),
              'controls': ['공통 153개월과 시작 상태', '공통 120거래일 KOSPI 지수 이력 및 금 자료',
                           '퍼펙트 1~6위·달리는 말 1~2위·기존 필터·금6M·금1개월연장', '편도비용0.25%, 엔진 월왕복0.50%'],
              'limitations': ['원본 대 재구성은 날짜 정의 외 기업행동 가격·워밍업·일부 종목군 차이를 포함한다.',
                              '교체 후보는 연구 자료이며 기업행동·상폐정산 검증이 남아 있다.',
                              'raw 종가비율과 날짜가 구분되는 관측만 endpoint 표에 비교했다.'],
              'input_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                               [input_dir / 'reconstructed_stocks.csv', input_dir / 'source_kospi_complete.csv', input_dir / 'gold_monthly.csv']}}
    (args.output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ['stats', 'input_sha256']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
