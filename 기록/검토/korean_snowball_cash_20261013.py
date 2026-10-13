"""Research only: compare negative-defense cash rule; never edit live strategy/data."""
from pathlib import Path
import sys, json, hashlib, subprocess
import numpy as np
import pandas as pd

ROOT = Path.cwd()
assert (ROOT / 'utils' / 'snowball.py').is_file(), 'Run from repository root'
sys.path.insert(0, str(ROOT))
from utils import snowball as sb
OUT = ROOT / '기록' / '2026-10-13-한국스노우볼-현금검토'
OUT.mkdir(exist_ok=True)

def plain(fn):
    return getattr(fn, '__wrapped__', fn)

def no_network(*args):
    raise AssertionError(f'Local data unavailable: {args}')

sb._http_csv = no_network
cutoff = pd.Period('2026-09', freq='M')
def trim(p):
    p = p.loc[p.index <= cutoff].copy()
    assert p.index[-1] == cutoff
    assert p.index.equals(pd.period_range(p.index[0], cutoff, freq='M'))
    return p

us = trim(plain(sb.load_monthly_prices)())
configs = [
    ('또 ISA', trim(plain(sb.load_ko_prices)()), sb.compute_signals_ko,
     sb.run_backtest_ko, sb.KO_DEFENSE, sb.KO_DEF_WIN, 'defense_scores', False),
    ('또 연금', trim(plain(sb.load_pen_prices)()), sb.compute_signals_pension,
     sb.run_backtest_pension, sb.PEN_DEFENSE, sb.PEN_DEF_WIN, 'defense_scores', False),
    ('쏘 연금', trim(plain(sb.load_ssopen_prices)()), sb.compute_signals_ssopen,
     sb.run_backtest_ssopen, sb.SSOPEN_DEFENSE, sb.SSOPEN_DEF_WINDOWS, 'defense_scores', True),
    ('맘 비과세', trim(plain(sb.load_mamtax_prices)()), sb.compute_signals_mamtax,
     sb.run_backtest_mamtax, sb.MAMTAX_DEFENSE, sb.MAMTAX_DEF_WIN, 'def_scores', True),
]

def weights(holds):
    if isinstance(holds, dict):
        return dict(holds)
    return {t: 1 / len(holds) for t in holds}

def score_independent(p, candidates, win):
    # Use explicit windows instead of the live disparity/returns helpers.
    arr = np.full((len(p), len(candidates)), np.nan)
    for j, t in enumerate(candidates):
        values = p[t].to_numpy(dtype=float)
        for i, current in enumerate(values):
            if isinstance(win, list):
                if i >= max(win) and np.isfinite(current) and all(np.isfinite(values[i-w]) for w in win):
                    arr[i,j] = sum(current / values[i-w] - 1 for w in win)
            elif i >= win-1:
                window = values[i-win+1:i+1]
                if np.isfinite(window).all():
                    arr[i,j] = current / (sum(window) / win) - 1
    return pd.DataFrame(arr, index=p.index, columns=candidates)

def sim(p, signals, live, scores, candidates, cost, variant):
    prev = {}
    records = []
    for _, row in live.iterrows():
        m, nm = pd.Period(row.signal_month, freq='M'), pd.Period(row.hold_month, freq='M')
        assert nm == m + 1
        s = signals.loc[str(m)]
        d = scores.loc[m].dropna()
        negative = bool(len(d) and (d < 0).all())
        cash = bool(variant and bool(s.defensive) and negative)
        w = {} if cash else weights(s.holds)
        if w:
            assert abs(sum(w.values()) - 1) < 1e-12
        gross = 0.0
        for t, weight in w.items():
            p0, p1 = float(p.loc[m,t]), float(p.loc[nm,t])
            assert np.isfinite(p0) and np.isfinite(p1) and p0 > 0
            gross += weight * (p1/p0 - 1)
        bought = sum(max(w.get(t, 0)-prev.get(t, 0),0) for t in set(w)|set(prev))
        tc = bought * cost
        records.append(dict(signal_month=str(m), hold_month=str(nm),
            defensive=bool(s.defensive), cash=cash, all_negative=negative,
            n_defense_available=len(d), full_defense=len(d)==len(candidates),
            best_defense_score=float(d.max()) if len(d) else None,
            weights=json.dumps(w, sort_keys=True), gross=gross, cost=tc, bought=bought,
            ret=gross-tc))
        prev = w
    return pd.DataFrame(records)

def metrics(frame):
    r = frame.ret.to_numpy()
    curve = np.cumprod(1+r)
    dd = curve / np.maximum.accumulate(np.r_[1.,curve])[1:] - 1
    return dict(n=len(r), start=frame.hold_month.iloc[0], end=frame.hold_month.iloc[-1],
        cagr=float(curve[-1]**(12/len(r))-1), cumulative=float(curve[-1]-1),
        mdd=float(dd.min()), worst_month=float(r.min()),
        mdd_trough=frame.hold_month.iloc[int(dd.argmin())],
        vol=float(r.std()*np.sqrt(12)), sharpe=float(r.mean()/r.std()*np.sqrt(12)),
        sortino=float(r.mean()/np.sqrt(np.mean(np.minimum(r,0)**2))*np.sqrt(12)))

def paired(a,b):
    delta = b.ret.to_numpy()-a.ret.to_numpy()
    changed = abs(delta)>1e-12
    d=delta[changed]
    logdiff=np.log1p(b.ret.to_numpy())-np.log1p(a.ret.to_numpy())
    rng=np.random.default_rng(20261013)
    n=len(delta)
    starts=rng.integers(0,n,size=(20000,(n+5)//6))
    indices=((starts[:,:,None]+np.arange(6))%n).reshape(20000,-1)[:,:n]
    boot=np.exp(logdiff[indices].mean(axis=1)*12)-1
    return dict(changed_return_months=int(changed.sum()),wins=int((d>0).sum()),
        losses=int((d<0).sum()),paired_t=float(delta.mean()/(delta.std(ddof=1)/np.sqrt(n))) if delta.std()>0 else 0,
        relative_annualized_ci95=np.quantile(boot,[.025,.975]).tolist())

report={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'cutoff':str(cutoff), 'cash_return':0, 'buy_cost':.0025,
    'rule':'Only existing defensive months; all available valid defense scores strictly < 0; empty scores never trigger.',
    'verification':{},'strategies':[]}
for name,p,signal_fn,bt_fn,candidates,win,key,needus in configs:
    signals = plain(signal_fn)(p,us) if needus else plain(signal_fn)(p)
    live = plain(bt_fn)(p,signals,cost=.0025)
    scores = score_independent(p,candidates,win)
    for m,s in signals.iterrows():
        if not isinstance(s.get(key),dict):
            continue
        values=s[key]
        if values:
            independent=scores.loc[pd.Period(m,freq='M')].dropna().to_dict()
            assert values.keys()==independent.keys(),(name,m,values,independent)
            for t in values:
                assert abs(values[t]-independent[t])<1e-10,(name,m,t)
    a=sim(p,signals,live,scores,candidates,.0025,False)
    b=sim(p,signals,live,scores,candidates,.0025,True)
    assert np.allclose(a.ret,live.ret_strategy,atol=1e-12,rtol=0)
    assert np.allclose(a.cost,live.cost,atol=1e-12,rtol=0)
    assert np.allclose(a.gross,live.ret_gross,atol=1e-12,rtol=0)
    assert a.hold_month.equals(b.hold_month)
    missing=[str(m) for m in pd.period_range(a.hold_month.iloc[0],cutoff,freq='M') if str(m) not in set(a.hold_month)]
    # The live pension engine skips unavailable-defense months in 2015-16.
    # Preserve that baseline for exact verification, but report a continuous suffix.
    continuous_start=str(pd.Period(missing[-1],freq='M')+1) if missing else a.hold_month.iloc[0]
    continuous_mask=a.hold_month>=continuous_start
    assert a.loc[continuous_mask,'hold_month'].tolist()==[str(m) for m in pd.period_range(continuous_start,cutoff,freq='M')]
    perf=sb.compute_performance(live)
    assert abs(metrics(a)['cagr']-perf['cagr'])<1e-12
    assert abs(metrics(a)['mdd']-perf['mdd'])<1e-12
    ready=scores.notna().all(axis=1)
    ready_month=scores.index[ready][0]
    mask=a.signal_month >= str(ready_month)
    periods={}
    for label,maskp in [('continuous',continuous_mask),('2022+',a.hold_month>='2022-01'),('defense_complete',mask)]:
        if maskp.any():
            periods[label]={'baseline':metrics(a.loc[maskp]),'cash':metrics(b.loc[maskp]),
                'cash_months':int(b.loc[maskp,'cash'].sum())}
    sensitivity={}
    for cost in [0.,.001,.005,.01]:
        aa=sim(p,signals,live,scores,candidates,cost,False)
        bb=sim(p,signals,live,scores,candidates,cost,True)
        sensitivity[str(cost)]={'baseline':metrics(aa),'cash':metrics(bb)}
    changed=b.cash
    cash_months=[]
    for i in b.index[changed]:
        cash_months.append(dict(month=b.loc[i,'hold_month'], baseline_net=float(a.loc[i,'ret']),
            baseline_gross=float(a.loc[i,'gross']),cash_net=float(b.loc[i,'ret']),
            n_available=int(b.loc[i,'n_defense_available']),best_score=float(b.loc[i,'best_defense_score']),
            baseline_weights=json.loads(a.loc[i,'weights'])))
    yearly=[]
    for year in sorted({s[:4] for s in a.hold_month}):
        yy=a.hold_month.str.startswith(year)
        yearly.append({'year':year,'n':int(yy.sum()),
            'baseline':float((1+a.loc[yy,'ret']).prod()-1),
            'cash':float((1+b.loc[yy,'ret']).prod()-1),
            'cash_months':int(b.loc[yy,'cash'].sum())})
    sha=hashlib.sha256(pd.util.hash_pandas_object(p,index=True).to_numpy().tobytes()).hexdigest()
    entry=dict(name=name,baseline=metrics(a),cash=metrics(b),cash_months=int(changed.sum()),
        defensive_months=int(a.defensive.sum()),cash_events=cash_months,
        cash_baseline_compound=float((1+a.loc[changed,'ret']).prod()-1),
        defense_ready_signal_month=str(ready_month),periods=periods,cost_sensitivity=sensitivity,
        paired=paired(a,b),yearly=yearly,input_price_sha256=sha,
        baseline_max_error=float(abs(a.ret-live.ret_strategy).max()),missing_live_months=missing,
        latest_signal={'month':signals.index[-1],'defensive':bool(signals.iloc[-1].defensive),
            'all_negative':bool(len(scores.iloc[-1].dropna()) and (scores.iloc[-1].dropna()<0).all())})
    report['strategies'].append(entry)
    combined=a.add_prefix('baseline_').join(b.add_prefix('cash_'))
    combined.to_csv(OUT/f'{name}-월별.csv',index=False,encoding='utf-8-sig')
    print(json.dumps({'name':name,'baseline':entry['baseline'],'cash':entry['cash'],
        'cash_months':entry['cash_months'],'cash_events':cash_months,'periods':periods,
        'paired':entry['paired'],'max_error':entry['baseline_max_error']},ensure_ascii=False),flush=True)
report['verification']={'baseline_months_checked':sum(s['baseline']['n'] for s in report['strategies']),
    'score_checks':'Explicit-window scores match live scores within 1e-10; no network; monthly continuity; live baseline gross/cost/net and CAGR/MDD matched.'}
(OUT/'결과.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

# Second, vectorized validation of cash returns and reentry costs.
for e in report['strategies']:
    f=pd.read_csv(OUT/(e['name']+'-월별.csv'))
    all_tickers=sorted({t for value in f.baseline_weights for t in json.loads(value)})
    w=pd.DataFrame([json.loads(value) for value in f.baseline_weights]).reindex(columns=all_tickers).fillna(0)
    w.loc[f.cash_cash.astype(bool)]=0
    purchases=(w-w.shift(1).fillna(0)).clip(lower=0).sum(axis=1)
    gross=f.baseline_gross.where(~f.cash_cash.astype(bool),0)
    error=float(abs(gross-.0025*purchases-f.cash_ret).max())
    assert error<1e-12
    e['variant_max_error']=error
report['verification']['variant_checks']='Vectorized target-weight changes independently verify cash gross/net and reentry buy costs for all 525 months within 1e-12.'
(OUT/'결과.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
