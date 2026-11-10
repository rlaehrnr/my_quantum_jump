"""2014년 이후 거래 불가 신규매수의 차순위 대체·해당 비중 현금 비교."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from kospi_overlap_audit import ROOT, MOM, c, normalize_stock_code
from kospi_top4_comparison import stats

PERF = '🔥 퍼펙트 상승 (1~6위)'
HORSE = '🐎 달리는 말 (1~2위)'
ENS = '앙상블 (50:50 전략)'
PRIORITY = '앙상블 (달리는말 우선 50:50)'
UNIQUE = '통합 전략 (중복 제외 1/N)'
DUPLICATE = '통합 전략 (중복 인정 1/N)'


def slot_weights(slots):
    if not slots:
        return {'cash:empty': 1.}
    return {code: count / len(slots) for code, count in Counter(slots).items()}


def combination_weights(perfect, horse):
    def blend(left, right):
        result = Counter()
        for weights in [slot_weights(left), slot_weights(right)]:
            for code, weight in weights.items():
                result[code] += weight / 2
        return dict(result)

    unique_perfect = [code for code in perfect if code not in set(horse)]
    combined = perfect + horse
    return {PERF: slot_weights(perfect), HORSE: slot_weights(horse),
            ENS: blend(perfect, horse), PRIORITY: blend(unique_perfect, horse),
            UNIQUE: slot_weights(list(dict.fromkeys(combined))), DUPLICATE: slot_weights(combined)}


def advance_book(wealth, locked, weights, price_returns, blocked_end, release_returns, cost=.005):
    """매도 대기 자금은 월초 새 목표에 투입하지 않고, 재개일 매도 후 현금으로 둔다."""
    assert abs(sum(weights.values()) - 1) < 1e-12
    free = wealth - sum(locked.values())
    assert free >= -1e-10
    free = max(free, 0.)
    remaining, released = {}, 0.
    for code, value in locked.items():
        if code in release_returns:
            released += value * (1 + release_returns[code])
        else:
            remaining[code] = value
    invested_end = 0.
    for code, weight in weights.items():
        allocation = free * weight
        if code.startswith('cash:'):
            invested_end += allocation
            continue
        value = allocation * (1 + price_returns[code] - cost)
        assert value >= 0
        invested_end += value
        if blocked_end.get(code, False):
            remaining[code] = remaining.get(code, 0.) + value
    # remaining에는 이전 달부터 계속 잠긴 자금과 이달 새로 잠긴 자금이 함께 있다.
    old_still_locked = sum(value for code, value in locked.items() if code not in release_returns)
    total = invested_end + released + old_still_locked
    assert total >= sum(remaining.values()) - 1e-10
    return total, remaining, {'free_start': free, 'released_end': released,
                              'locked_start': sum(locked.values()), 'locked_end': sum(remaining.values())}


def load_market(source):
    snapshots, daily = [], []
    codes = ['005300', '042670', '012450', '034020', '489790']
    for year in range(2014, 2027):
        d = pd.read_parquet(source / f'marcap-{year}.parquet',
                            columns=['Date', 'Code', 'Close', 'Changes', 'Volume', 'MarketId'])
        d = d[d.MarketId.eq('STK') & d.Date.le('2026-10-31')].copy()
        d['Code'] = d.Code.map({code: normalize_stock_code(code) for code in d.Code.unique()})
        d['month'] = d.Date.dt.to_period('M').astype(str)
        last_day = d.groupby('month').Date.transform('max')
        snapshots.append(d[d.Date.eq(last_day)][['month', 'Code', 'Volume']])
        daily.append(d[d.Code.isin(codes)])
    snapshots = pd.concat(snapshots, ignore_index=True).set_index(['month', 'Code'])
    assert snapshots.index.is_unique
    return snapshots.Volume.to_dict(), pd.concat(daily, ignore_index=True).sort_values(['Code', 'Date'])


def release_return(code, month, daily):
    previous_month = str(pd.Period(month, freq='M') - 1)
    prices = daily[daily.Code.eq(code)]
    previous = prices[prices['month'].eq(previous_month)].iloc[-1]
    resumed = prices[prices['month'].eq(month) & prices.Volume.gt(0)]
    if resumed.empty:
        return None
    first = resumed.iloc[0]
    if code == '005300' and month == '2019-05':
        value = 10 * first.Close
        components = '롯데칠성 1주→10주'
    elif code == '042670' and month == '2021-07':
        other = daily[daily.Code.eq('034020') & daily.Date.eq(first.Date)].iloc[0]
        value = .3104974 * first.Close + .4719929 * other.Close
        components = '두산인프라코어0.3104974주+두산중공업0.4719929주'
    elif code == '012450' and month == '2024-09':
        other = daily[daily.Code.eq('489790') & daily.Date.eq(first.Date)].iloc[0]
        value = .9002797 * first.Close + .997203 * other.Close
        components = '한화에어로스페이스0.9002797주+한화인더스트리얼솔루션즈0.997203주'
    else:
        raise ValueError(f'배정비율 확인이 필요한 매도 대기 사례 {month} {code}')
    return value / previous.Close - 1, str(first.Date.date()), components, float(previous.Close), float(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('새 출력 폴더를 지정하세요.')
    data_path = ROOT / '기록/2026-11-10-KOSPI-2014-가격재구성/monthly_price_data.csv'
    data = pd.read_csv(data_path, dtype={'종목코드': str})
    data = data[data['투자월'].le('2026-10')].copy()
    expected = pd.period_range('2014-01', '2026-10', freq='M').astype(str).tolist()
    data['시가총액(억)'] = (data['시가총액'] / 1e8).round(0)
    engine_data = data.copy()
    engine_data[MOM + ['이번달수익률']] = engine_data[MOM + ['이번달수익률']].fillna(0)
    sources = ROOT / '기록/2026-11-05-KOSPI-2010-202610-확정'
    index = pd.read_csv(sources / 'source_kospi_complete.csv', index_col=0, parse_dates=True)
    gold = pd.read_csv(sources / 'gold_monthly.csv', index_col=0)
    with patch.object(c, '_load_kospi_index', return_value=index), patch.object(c, 'get_gold_krw_monthly', return_value=gold):
        baseline, _, detail = c.run_backtest_k200(engine_data, 2014, 2026, 6, True, (1, 6), (1, 2), 30, 30,
            trading_cost_pct=.25, gold_returns=gold.ret.to_dict(), use_gold=True, use_gold_ma=True, gold_ma_months=6)
    prior = pd.read_csv(data_path.parent / 'diagnostic_monthly_returns.csv')
    prior['중지 사유'] = prior['중지 사유'].fillna('')
    baseline['중지 사유'] = baseline['중지 사유'].fillna('')
    pd.testing.assert_frame_equal(baseline, prior, check_dtype=False, rtol=1e-12, atol=1e-12)
    assert baseline['투자월'].tolist() == expected
    modes = detail.set_index('투자월')
    volumes, daily = load_market(args.source_dir)
    results, positions, decisions, ledger, releases = {}, [], [], [], []
    strategy_names = [PERF, HORSE, ENS, PRIORITY, UNIQUE, DUPLICATE]
    for policy in ['next', 'cash']:
        wealth = {name: 1. for name in strategy_names}
        locked = {name: {} for name in strategy_names}
        records = []
        for month, source_frame in engine_data.groupby('투자월', sort=True):
            frame = source_frame.sort_values('시가총액(억)', ascending=False).head(200)
            p, s = c.select_kospi200_targets(frame, (1, 6), (1, 2), 30, 30, entry_policy=policy)
            slots = []
            for label, selected in [('퍼펙트', p), ('달리는말', s)]:
                slots.append([('cash:' if row['_cash'] else '') + row['종목코드'] for row in selected.to_dict('records')])
                if bool(modes.loc[month, 'invested']):
                    for rank, row in enumerate(selected.to_dict('records'), 1):
                        decisions.append({'정책': policy, '투자월': month, '전략': label, '포지션': rank,
                                          '종목코드': row['종목코드'], '종목명': row['종목명'],
                                          '현금대기': bool(row['_cash'])})
            weights_by_strategy = combination_weights(*slots)
            price_returns = (source_frame.set_index('종목코드')['이번달수익률'] / 100).to_dict()
            true_returns = data[data['투자월'].eq(month)].set_index('종목코드')['이번달수익률']
            blocked = {code: volume == 0 for (ym, code), volume in volumes.items() if ym == month}
            release_values = {}
            for code in set().union(*(set(items) for items in locked.values())):
                release = release_return(code, month, daily)
                if release is not None:
                    value, day, parts, previous_price, proceeds = release
                    release_values[code] = value
                    releases.append({'정책': policy, '투자월': month, '종목코드': code, '매도일': day,
                                     '권리승계': parts, '직전월말주당평가': previous_price,
                                     '구주1주당매도대가': proceeds, '매도대기수익률': value * 100})
            record = {'투자월': month, 'invested': bool(modes.loc[month, 'invested'])}
            for name, weights in weights_by_strategy.items():
                if not bool(modes.loc[month, 'invested']):
                    if modes.loc[month, '방어자산'] == '금':
                        weights = {'gold': 1.}
                        price_returns['gold'] = float(gold.loc[month, 'ret']) / 100
                    else:
                        weights = {'cash:defense': 1.}
                for code, weight in weights.items():
                    if not code.startswith('cash:') and code != 'gold':
                        assert pd.notna(true_returns.loc[code]), (policy, month, code, '선택 종목 수익 결측')
                        assert frame.set_index('종목코드').loc[code, '거래량'] > 0, (policy, month, code, '신규 매수 불가')
                        assert (month, code) in volumes, (policy, month, code, '보유월말 원천 누락')
                    positions.append({'정책': policy, '투자월': month, '전략': name, '대상': code, '가용자금내비중': weight})
                previous_wealth = wealth[name]
                wealth[name], locked[name], amounts = advance_book(previous_wealth, locked[name], weights,
                    price_returns, blocked, release_values)
                record[name] = (wealth[name] / previous_wealth - 1) * 100
                ledger.append({'정책': policy, '투자월': month, '전략': name, '월초자산': previous_wealth,
                               '월말자산': wealth[name], **amounts})
            records.append(record)
        results[policy] = pd.DataFrame(records)
    args.output.mkdir(parents=True)
    report = {'period': ['2014-01', '2026-10'], 'months': 154, 'stats': {},
              'data_sha256': hashlib.sha256(data_path.read_bytes()).hexdigest(),
              'assumptions': ['당시코스피보통주시총200·퍼펙트1~6·달리는말1~2·동일필터·동일금방어',
                              '동일한 모멘텀 자격조건 안에서 차순위 충원; 후보 부족분은 현금',
                              '미매수 현금은0%·비용0; 체결 비중만 기존 모형의 월왕복0.50% 차감',
                              '매도정지 자금은 새 월초 매수에 재사용하지 않음; 재개 첫날 종가로 권리승계 주식 동시 매도 후 해당월 현금',
                              '매도정지분 외 가용자금에 목표비중 적용; 소수주 허용·단주 정산 차이 미반영',
                              '현금배당은 가격수익률 제외·별도집계 미완료',
                              '가격 모멘텀 결측은 기존 엔진의0처리 유지; 기업행동 전체 공시 및 완전한 체결 검증 전 연구 비교']}
    for policy, result in results.items():
        assert result['투자월'].tolist() == expected
        result.to_csv(args.output / f'{policy}_monthly.csv', index=False, encoding='utf-8-sig')
        annual = ((1 + result[strategy_names] / 100).groupby(result['투자월'].str[:4]).prod() - 1) * 100
        annual.to_csv(args.output / f'{policy}_annual.csv', encoding='utf-8-sig')
        report['stats'][policy] = {name: stats(result[name]) for name in strategy_names}
    delta = results['next'][strategy_names] - results['cash'][strategy_names]
    report['changed_months'] = results['next'].loc[delta.abs().max(axis=1).gt(1e-9), '투자월'].tolist()
    delta.insert(0, '투자월', expected)
    delta.to_csv(args.output / 'monthly_difference_pp.csv', index=False, encoding='utf-8-sig')
    for name, rows in [('target_positions', positions), ('selection_decisions', decisions), ('cash_and_locked_ledger', ledger),
                       ('resumption_sales', releases)]:
        pd.DataFrame(rows).to_csv(args.output / f'{name}.csv', index=False, encoding='utf-8-sig')
    (args.output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(pd.DataFrame(releases).drop_duplicates(['투자월', '종목코드']).to_string(index=False))


if __name__ == '__main__':
    main()
