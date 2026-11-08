"""2017-05 기존 아카이브의 동월일 기준과 재구성 월말 기준을 일별 원천으로 대조한다.

실행 예시
python 기록/검토/kospi_month_anchor_audit.py --source-dir <marcap폴더> --output <새폴더>
"""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MONTH = '2017-05'
BASE = pd.Timestamp('2017-04-28')
MOM = ['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)']


def select(frame):
    d = frame.copy()
    d[MOM] = d[MOM].fillna(0)
    d['시가총액(억)'] = (d['시가총액'] / 1e8).round(0)
    d = d.sort_values('시가총액(억)', ascending=False).head(200)
    threshold = d[MOM].quantile(.7)
    perfect = d[d[MOM].ge(threshold).all(axis=1) & d[MOM].gt(0).all(axis=1)]
    horse = d[d['12개월(%)'].ge(threshold['12개월(%)']) &
              d['1개월(%)'].ge(d['1개월(%)'].quantile(.9))]
    return {'퍼펙트': perfect.sort_values('3개월(%)', ascending=False).head(6),
            '달리는말': horse.sort_values('1개월(%)', ascending=False).head(2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요.')
    old_path = ROOT / 'archive_kospi/only_kospi_2017_05.csv'
    new_path = ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정/reconstructed_stocks.csv'
    old = pd.read_csv(old_path, dtype={'종목코드': str})
    new = pd.read_csv(new_path, dtype={'종목코드': str})
    new = new[new['투자월'].eq(MONTH)].copy()
    assert len(old) == len(new) == 200
    assert set(old['종목코드']) == set(new['종목코드'])
    assert old['종목선정일'].eq(str(BASE.date())).all()
    assert new['종목선정일'].eq(str(BASE.date())).all()
    raw_paths = [args.source_dir / f'marcap-{y}.parquet' for y in [2016, 2017]]
    raw = pd.concat([pd.read_parquet(p) for p in raw_paths], ignore_index=True)
    raw = raw[raw.Code.isin(old['종목코드'])].sort_values(['Code', 'Date'])
    comparisons = []
    for code, rows in raw.groupby('Code'):
        rows = rows.set_index('Date')
        base_close = rows.loc[BASE, 'Close']
        for n, field in zip([1, 3, 6, 12, -1], MOM + ['이번달수익률']):
            old_target = BASE - pd.DateOffset(months=n)
            target_month = BASE.to_period('M') - n
            new_target = target_month.to_timestamp('M')
            old_history = rows.loc[rows.index <= old_target]
            new_history = rows.loc[rows.index <= new_target]
            if old_history.empty or new_history.empty:
                comparisons.append({'종목코드': code, '종목명': rows.loc[BASE, 'Name'], '항목': field,
                                    '이력부족': True, '기존_동월일_일치': None,
                                    '재구성_월말_종가비율_일치': None})
                continue
            old_row = old_history.iloc[-1]
            new_row = new_history.iloc[-1]
            old_ratio, new_ratio = base_close / old_row.Close, base_close / new_row.Close
            if n == -1:
                old_ratio, new_ratio = 1 / old_ratio, 1 / new_ratio
            old_return, new_return = round((old_ratio - 1) * 100, 2), round((new_ratio - 1) * 100, 2)
            actual_old = float(old.loc[old['종목코드'].eq(code), field].iloc[0])
            actual_new = float(new.loc[new['종목코드'].eq(code), field].iloc[0])
            comparisons.append({'종목코드': code, '종목명': rows.loc[BASE, 'Name'],
                                '항목': field, '선정일종가': float(base_close),
                                '기존_비교일': str(old_row.name.date()), '기존_비교일종가': float(old_row.Close),
                                '재구성_비교일': str(new_row.name.date()), '재구성_비교일종가': float(new_row.Close),
                                '기존_저장값': actual_old, '기존_동월일_재계산': old_return,
                                '재구성_저장값': actual_new, '재구성_월말_종가비율': new_return,
                                '기존_동월일_일치': abs(actual_old - old_return) < .011,
                                '재구성_월말_종가비율_일치': abs(actual_new - new_return) < .011})
    check = pd.DataFrame(comparisons)
    selections = []
    for label, d in [('기존', old), ('재구성', new)]:
        for strategy, picks in select(d).items():
            for rank, row in enumerate(picks.to_dict('records'), 1):
                selections.append({'자료': label, '투자월': MONTH, '전략': strategy, '순위': rank,
                                   **{key: row[key] for key in ['종목코드', '종목명', *MOM, '이번달수익률']}})
    picks = pd.DataFrame(selections)
    saved = pd.read_csv(ROOT / '기록/2026-11-06-KOSPI-1996-202610-검산/trades.csv')
    saved = saved[saved['투자월'].eq(MONTH)]
    assert picks[picks['자료'].eq('재구성')]['종목명'].tolist() == saved['종목명'].tolist()
    detail = check[check['종목코드'].eq('009150')]
    assert detail['기존_동월일_일치'].all()
    assert detail['재구성_월말_종가비율_일치'].all()
    inputs = [old_path, new_path, *raw_paths]
    summary = {'month': MONTH, 'selection_day': str(BASE.date()), 'universe_equal': True,
               'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
               'endpoint_matches': check[['기존_동월일_일치', '재구성_월말_종가비율_일치']].apply(
                   lambda s: s.fillna(False).astype(int)).groupby(check['항목']).sum().to_dict(),
               'endpoint_evaluated': check.groupby('항목')[['기존_동월일_일치', '재구성_월말_종가비율_일치']].count().to_dict(),
               'rows_per_field': 200,
               'samsung_electromechanics': json.loads(detail.to_json(orient='records', force_ascii=False)),
               'limitations': ['종가비율 대조. 기업행위에 따른 기준가격 조정 차이는 별도 검증 대상.',
                               '2017-05 사례로 전체 기간의 정확성을 확정하지 않음.',
                               '기존 첨부 KOSPI_조합_백테스트.xlsx가 없어 기존 아카이브와 재구성 입력을 비교.']}
    args.output.mkdir(parents=True)
    check.to_csv(args.output / 'endpoint_comparison.csv', index=False, encoding='utf-8-sig')
    picks.to_csv(args.output / 'selected_stocks.csv', index=False, encoding='utf-8-sig')
    text = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    (args.output / 'summary.json').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
