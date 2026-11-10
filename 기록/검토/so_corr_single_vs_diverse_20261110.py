"""연구용. 상관>=0.70일 때 1위100%와 저상관 차순위50:50 비교."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from so_correlation_rank_skip_20261106 import sb
from so_volatility_validation_20261105 import bootstrap, stats

WINDOWS = [12, 24, 36]
THRESHOLD = .70
PERIODS = {'full': ('2011-08','2026-10'), 'pre2026': ('2011-08','2025-12'),
           '2017_2021': ('2017-01','2021-12'), '2022_2025': ('2022-01','2025-12'),
           '2026_observed': ('2026-01','2026-10')}


def select(signals, matrix, policy):
    altered = signals.copy(deep=True)
    events = []
    for month, row in signals.iterrows():
        original = row['holds']
        if row['defensive'] or not isinstance(original,list) or len(original)!=2:
            continue
        first, second = original
        corrs = matrix.loc[(month,first)]
        if pd.isna(corrs[second]) or corrs[second] < THRESHOLD:
            continue
        picks = [first]
        replacement = None
        if policy=='diverse':
            ranked = row[[f'score_{asset}' for asset in sb.SO_OFFENSE_ASSETS]].astype(float).sort_values(ascending=False)
            for field in ranked.index:
                asset = field.removeprefix('score_')
                if asset not in original and row[f'abs_{asset}']>0 and pd.notna(corrs[asset]) and corrs[asset]<THRESHOLD:
                    replacement=asset
                    picks.append(asset)
                    break
        altered.at[month,'holds']=picks
        altered.at[month,'hold']='·'.join(picks)
        events.append(dict(signal_month=str(month),hold_month=str(month+1),original='·'.join(original),
                           chosen='·'.join(picks),original_corr=float(corrs[second]),replacement=replacement,
                           chosen_corr=float(corrs[replacement]) if replacement else None,
                           single_fallback=(policy=='diverse' and replacement is None)))
    return altered,events


def verify(prices,signals,selected,bt,window,policy):
    previous={}
    max_error=0.
    for month,row in signals.iterrows():
        original=row['holds']
        if original is None:
            continue
        expected=original
        if not row['defensive'] and len(original)==2:
            first,second=original
            history=prices.loc[:month].tail(window+1)
            def corr(asset):
                raw=history[[first,asset]].to_numpy()
                if len(raw)!=window+1 or not np.isfinite(raw).all():
                    return np.nan
                return float(np.corrcoef((raw[1:]/raw[:-1]-1).T)[0,1])
            if corr(second)>=THRESHOLD:
                expected=[first]
                if policy=='diverse':
                    scores={asset:sum(float(prices.loc[month,asset])/float(prices.loc[month-k,asset])-1 for k in [1,3,6,12])
                            for asset in sb.SO_OFFENSE_ASSETS}
                    eligible=[asset for asset in sb.SO_OFFENSE_ASSETS if asset not in original
                              and prices.loc[month,asset]>sum(float(prices.loc[month-k,asset]) for k in range(4))/4
                              and corr(asset)<THRESHOLD]
                    if eligible:
                        expected.append(max(eligible,key=scores.get))
        assert expected==selected.at[month,'holds'], (month,window,policy)
        if month+1 not in bt.index:
            continue
        current={asset:1/len(expected) for asset in expected}
        gross=sum(weight*(float(prices.loc[month+1,asset])/float(prices.loc[month,asset])-1) for asset,weight in current.items())
        fee=.0025*sum(max(weight-previous.get(asset,0),0) for asset,weight in current.items())
        error=abs(gross-fee-bt.at[month+1,'ret_strategy'])
        assert error<1e-12
        max_error=max(max_error,error)
        previous=current
    return max_error


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    out=parser.parse_args().output
    out.mkdir(parents=True,exist_ok=True)
    def offline(*args,**kwargs):
        raise AssertionError('로컬 원격 스냅샷만 사용')
    sb._http_csv=offline
    prices=sb.load_monthly_prices.__wrapped__().loc[:'2026-10']
    sig=sb.compute_signals_so.__wrapped__(prices)
    returns=prices[sb.SO_OFFENSE_ASSETS].pct_change(fill_method=None)
    def run(s,cost=.0025):
        bt=sb.run_backtest_samsung.__wrapped__(prices,s,cost=cost)
        bt.index=pd.PeriodIndex(bt.hold_month,freq='M')
        assert bt.index.equals(pd.period_range('2011-08','2026-10',freq='M'))
        return bt
    variants={'base':sig}
    event_rows=[]
    selected_events={}
    for window in WINDOWS:
        matrix=returns.rolling(window).corr()
        for policy in ['single','diverse']:
            name=f'w{window}_{policy}'
            chosen,events=select(sig,matrix,policy)
            for cut in ['2019-12','2025-12','2026-06','2026-09']:
                short=sb.compute_signals_so.__wrapped__(prices.loc[:cut])
                s2,_=select(short,returns.loc[:cut].rolling(window).corr(),policy)
                pd.testing.assert_series_equal(s2.hold,chosen.loc[:cut,'hold'])
            variants[name]=chosen
            selected_events[name]=events
            event_rows.extend(dict(variant=name,**event) for event in events if event['hold_month']<='2026-10')
    results={name:run(s) for name,s in variants.items()}
    summaries=[]
    monthly=[]
    costs=[]
    checks={}
    for name,bt in results.items():
        for label,(start,end) in PERIODS.items():
            summaries.append(dict(variant=name,period=label,**stats(bt.loc[start:end,'ret_strategy'])))
        for month,row in bt.iterrows():
            monthly.append(dict(variant=name,hold_month=str(month),signal_month=str(month-1),hold=row['hold'],
                                gross=row.ret_gross,cost=row.cost,net=row.ret_strategy))
        for fee in [0,.0025,.005,.01]:
            z=bt if fee==.0025 else run(variants[name],fee)
            for label,(start,end) in PERIODS.items():
                if label in ['full','pre2026']:
                    costs.append(dict(variant=name,fee=fee,period=label,**stats(z.loc[start:end,'ret_strategy'])))
        if name!='base':
            window=int(name.split('_')[0][1:])
            policy=name.split('_')[1]
            events=[e for e in selected_events[name] if e['hold_month']<='2026-10']
            checks[name]=dict(independent_max_error=verify(prices,sig,variants[name],bt,window,policy),
                              trigger_months=len(events),single_fallback_months=sum(e['single_fallback'] for e in events),
                              actual_single_months=int(bt['hold'].isin(sb.SO_OFFENSE_ASSETS).sum()))
    comparisons={}
    for window in WINDOWS:
        a,b=results[f'w{window}_single'],results[f'w{window}_diverse']
        comparisons[str(window)]={label:bootstrap(a.loc[:end,'ret_strategy'],b.loc[:end,'ret_strategy'])
                                 for label,end in [('full','2026-10'),('pre2026','2025-12')]}
    metadata=dict(source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  prices_sha256=hashlib.sha256(prices.to_csv().encode()).hexdigest(),cutoff='2026-10',primary_window=24,
                  threshold=THRESHOLD,comparison='>=',replacement_requirement='<',fallback='first100',
                  prefix_invariant=True,checks=checks,diverse_minus_single=comparisons,
                  latest={name:s.iloc[-1]['hold'] for name,s in variants.items()})
    (out/'results.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(summaries).to_csv(out/'summary.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(monthly).to_csv(out/'monthly.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(event_rows).to_csv(out/'events.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(costs).to_csv(out/'costs.csv',index=False,encoding='utf-8-sig')
    print('CHECK_OK 183 months per variant; 6 alternatives independently reconciled; 4 causal prefixes each')
    print(pd.DataFrame(summaries).query("period in ['full','pre2026','2026_observed']")[[
        'variant','period','cagr','mdd','vol','sharpe','worst_month','cumulative']].to_string(index=False))
    print(json.dumps(checks,ensure_ascii=False))


if __name__=='__main__':
    main()
