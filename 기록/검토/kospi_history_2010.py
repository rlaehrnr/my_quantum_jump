"""2010년 확장 후보 생성·접합 검사. 라이브 파일은 수정하지 않는다.

실행: python 기록/검토/kospi_history_2010.py --source-dir <marcap폴더> --output <새폴더>
원천: https://github.com/FinanceData/marcap 의 2008~2014 연도별 parquet.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils.kospi_history import with_return_prices, build_monthly_archive, write_monthly_archives


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요. 기존 결과는 덮어쓰지 않습니다.')
    inputs = [args.source_dir / f'marcap-{year}.parquet' for year in range(2008, 2015)]
    source = pd.concat([pd.read_parquet(p) for p in inputs], ignore_index=True)
    source = source[(source.MarketId == 'STK') & source.Code.str.endswith('0')].copy()
    source['month'] = source.Date.dt.to_period('M')
    # 먼저 각 월말의 실제 거래 가능 후보를 정하고, 이들의 전 과거 가격을 유지한다.
    eligible = source[(source.Volume > 0) & (source.Close > 0) & (source.Marcap > 0)]
    last_days = eligible.groupby('month').Date.transform('max')
    snapshots = eligible[eligible.Date == last_days]
    top = snapshots.sort_values('Marcap', ascending=False).groupby('month').head(200)
    codes = top[top.month.between(pd.Period('2009-12'), pd.Period('2014-01'))].Code.unique()
    source = source[source.Code.isin(codes)].drop(columns='month')
    adjusted = with_return_prices(source)
    raw = build_monthly_archive(source, '2010-01', '2014-02')
    candidate = build_monthly_archive(adjusted, '2010-01', '2014-02')
    new = candidate[candidate['투자월'] == '2014-02']
    old = pd.read_csv(ROOT / 'archive_kospi/only_kospi_2014_02.csv', dtype={'종목코드': str})
    comparison = new.merge(old[['종목코드', '이번달수익률']], on='종목코드', suffixes=('_new', '_old'))
    comparison['difference_pp'] = comparison['이번달수익률_new'] - comparison['이번달수익률_old']
    months = candidate[candidate['투자월'] < '2014-02']
    counts = months.groupby('투자월').size()
    assert len(counts) == 49 and counts.eq(200).all()
    assert months['이번달수익률'].notna().all()
    assert (pd.to_datetime(months['종목선정일']).dt.to_period('M') < pd.PeriodIndex(months['투자월'], freq='M')).all()
    changed = raw.merge(candidate, on=['투자월', '종목코드'], suffixes=('_raw', '_adjusted'))
    changed['difference_pp'] = changed['이번달수익률_adjusted'] - changed['이번달수익률_raw']
    changed = changed[changed.difference_pp.abs() > .05]
    args.output.mkdir(parents=True)
    write_monthly_archives(adjusted, '2010-01', '2014-01', args.output / 'candidate_archive')
    comparison.to_csv(args.output / 'overlap_2014_02.csv', index=False, encoding='utf-8-sig')
    changed.to_csv(args.output / 'corporate_action_differences.csv', index=False, encoding='utf-8-sig')
    summary = {
        'status': 'research_only_not_live', 'start': '2010-01', 'end': '2014-01',
        'months': len(counts), 'rows': len(months),
        'overlap_codes': len(comparison),
        'overlap_return_max_difference_pp': float(comparison.difference_pp.abs().max()),
        'overlap_return_mean_difference_pp': float(comparison.difference_pp.abs().mean()),
        'corporate_action_affected_stock_months': len(changed),
        'missing_momentum': months[['1개월(%)','3개월(%)','6개월(%)','12개월(%)']].isna().sum().to_dict(),
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        'limitations': [
            '월말 거래량 0 종목 제외는 과거 2014-02 접합에 맞춘 연구 가정; 현 로봇과는 차이 있음',
            'KRX 기준가격 연결은 배당·인적분할 수령주식·상장폐지 정산을 포함한 총수익이 아님',
            '가격 누락 시 직전 관측값 사용; 거래정지/상장폐지 개별 검산 필요',
            '기존 2014 초반 모멘텀 결측을 고치지 않음; 완전 일치 재현 주장은 불가',
            '2014년 이전 금 프록시 검증·연결 및 전체 전략 성과 검증은 후속',
        ],
    }
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
