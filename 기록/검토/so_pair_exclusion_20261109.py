"""연구용. EWY·SMH 동시 보유만 제한하며 라이브 파일은 수정하지 않는다."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from so_correlation_rank_skip_20261106 import choose, sb
from so_volatility_validation_20261105 import stats, bootstrap


def replace_pair(signals, fixed_ewy=False):
    altered = signals.copy(deep=True)
    events = []
    for month, row in signals.iterrows():
        holds = row['holds']
        if not isinstance(holds, list) or set(holds) != {'EWY', 'SMH'}:
            continue
        keep = 'EWY' if fixed_ewy else holds[0]
        ranked = row[[f'score_{asset}' for asset in sb.SO_OFFENSE_ASSETS]].astype(float).sort_values(ascending=False)
        candidates = [key.removeprefix('score_') for key in ranked.index
                      if key.removeprefix('score_') not in holds and row[f'abs_{key.removeprefix("score_")}'] > 0]
        replacement = candidates[0] if candidates else None
        picks = [keep, replacement] if replacement else [keep]
        altered.at[month, 'holds'] = picks
        altered.at[month, 'hold'] = '·'.join(picks)
        events.append(dict(signal_month=str(month), hold_month=str(month+1),
                           original='·'.join(holds), keep=keep, replacement=replacement,
                           proposed='·'.join(picks)))
    return altered, events


def check(prices, original, selected, bt, mode):
    """현재 순위·4개월선은 원가격 사칙연산으로, 순수익은 종목별로 독립 검산."""
    previous = {}
    errors = []
    for month, row in original.iterrows():
        holds = row['holds']
        if holds is None:
            continue
        expected = holds
        if set(holds) == {'EWY','SMH'}:
            keep = 'EWY' if mode == 'fixed_ewy' else holds[0]
            scores = {asset: sum(float(prices.loc[month,asset])/float(prices.loc[month-k,asset])-1
                                for k in [1,3,6,12]) for asset in sb.SO_OFFENSE_ASSETS}
            candidates = [asset for asset in sb.SO_OFFENSE_ASSETS if asset not in holds and
                          prices.loc[month,asset] > sum(float(prices.loc[month-k,asset]) for k in range(4))/4]
            expected = [keep, max(candidates, key=scores.get)] if candidates else [keep]
        assert expected == selected.at[month,'holds'], (month,expected,selected.at[month,'holds'])
        assert set(expected) != {'EWY','SMH'}
        if month+1 not in bt.index:
            continue
        current = {asset:1/len(expected) for asset in expected}
        gross = sum(weight*(float(prices.loc[month+1,asset])/float(prices.loc[month,asset])-1)
                    for asset,weight in current.items())
        cost = .0025*sum(max(weight-previous.get(asset,0),0) for asset,weight in current.items())
        error = abs(gross-cost-bt.at[month+1,'ret_strategy'])
        assert error < 1e-12
        errors.append(error)
        previous = current
    return max(errors)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    out=parser.parse_args().output
    out.mkdir(parents=True,exist_ok=True)
    def offline(*args,**kwargs):
        raise AssertionError('로컬 원격 스냅샷만 사용')
    sb._http_csv=offline
    prices=sb.load_monthly_prices.__wrapped__().loc[:'2026-10']
    sig=sb.compute_signals_so.__wrapped__(prices)
    pair,events=replace_pair(sig)
    old,_=replace_pair(sig,True)
    correlations=prices[sb.SO_OFFENSE_ASSETS].pct_change(fill_method=None).rolling(24).corr()
    corr,_=choose(sig,correlations,.7)
    variants={'base':sig,'pair_rank':pair,'pair_fixed_ewy_prior':old,'correlation_24_070_prior':corr}
    periods={'full':('2011-08','2026-10'),'pre2026':('2011-08','2025-12'),'2026_observed':('2026-01','2026-10')}
    records=[]
    details=[]
    reports={}
    results={}
    for name,signals in variants.items():
        bt=sb.run_backtest_samsung.__wrapped__(prices,signals,cost=.0025)
        bt.index=pd.PeriodIndex(bt.hold_month,freq='M')
        assert bt.index.equals(pd.period_range('2011-08','2026-10',freq='M'))
        results[name]=bt
        for label,(start,end) in periods.items():
            records.append(dict(variant=name,period=label,**stats(bt.loc[start:end,'ret_strategy'])))
        for month,row in bt.iterrows():
            details.append(dict(variant=name,hold_month=str(month),signal_month=str(month-1),
                                hold=row['hold'],gross=row.ret_gross,cost=row.cost,net=row.ret_strategy))
    base=results['base']
    for name in ['pair_rank','pair_fixed_ewy_prior']:
        error=check(prices,sig,variants[name],results[name], 'fixed_ewy' if name=='pair_fixed_ewy_prior' else 'rank')
        reports[name]=dict(independent_max_error=error,bootstrap={period:bootstrap(base.loc[:end,'ret_strategy'],results[name].loc[:end,'ret_strategy'])
                                                                for period,end in [('full','2026-10'),('pre2026','2025-12')]})
    for cut in ['2016-12','2025-12','2026-06','2026-09']:
        short=sb.compute_signals_so.__wrapped__(prices.loc[:cut])
        picks,_=replace_pair(short)
        pd.testing.assert_series_equal(picks.hold,pair.loc[:cut,'hold'])
    for event in events:
        month=pd.Period(event['hold_month'],'M')
        event.update(base_net=float(base.at[month,'ret_strategy']),pair_net=float(results['pair_rank'].at[month,'ret_strategy']))
    costs=[]
    for fee in [0,.001,.0025,.005,.01]:
        for name in ['base','pair_rank']:
            bt=sb.run_backtest_samsung.__wrapped__(prices,variants[name],cost=fee)
            costs.append(dict(variant=name,cost=fee,**stats(bt.ret_strategy)))
    report=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                prices_sha256=hashlib.sha256(prices.to_csv().encode()).hexdigest(),
                primary='pair_rank',monthly_count=len(base),events=events,prefix_invariance=True,
                missing_replacement_count=sum(event['replacement'] is None for event in events),
                latest={name:signals.iloc[-1]['hold'] for name,signals in variants.items()},
                comparisons=reports)
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(records).to_csv(out/'summary.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(details).to_csv(out/'monthly.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(events).to_csv(out/'pair_events.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(costs).to_csv(out/'costs.csv',index=False,encoding='utf-8-sig')
    print('CHECK_OK 183 months per variant; pair selection/return independent checks; 4 prefix cuts')
    print(pd.DataFrame(records)[['variant','period','n','cagr','mdd','vol','sharpe','cumulative']].to_string(index=False))
    print(pd.DataFrame(events).to_string(index=False))


if __name__=='__main__':
    main()
