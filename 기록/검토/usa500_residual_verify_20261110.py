"""저장된 잔차 실험 산출물을 회귀·비중·비용 수식으로 별도 검산한다."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from usa500_residual_review_20261110 import fit_scores


def synthetic_checks():
    rng=np.random.default_rng(712)
    f=np.c_[rng.normal(0,.03,(48,3)),np.full(48,.002)]
    known=np.array([.004,1.2,-.4,.7])
    count=0
    for lag in [1,2]:
        end=40-lag+1;start=end-36
        x=np.c_[np.ones(36),f[start:end,:3]]
        noise=rng.normal(0,.02,36)
        epsilon=noise-x@np.linalg.lstsq(x,noise,rcond=None)[0]
        y=f[start:end,3]+x@known+epsilon
        a=np.full((48,1),np.nan);a[start:end,0]=y;ext=a.copy()
        z,source,b=fit_scores(a,ext,f,np.array([0]),40,lag,False)
        form=epsilon[-12:-1] if lag==1 else epsilon[-11:]
        assert np.allclose(b[:,0],known) and np.isclose(z[0],form.mean()/form.std(ddof=1));count+=1
        a[start,0]=np.nan
        z,source,b=fit_scores(a,ext,f,np.array([0]),40,lag,True)
        assert source[0]=='yahoo_full_window' and np.isfinite(z[0]);count+=1
        bad=ext.copy();bad[start:end,0]+=.05
        z,source,b=fit_scores(a,bad,f,np.array([0]),40,lag,True)
        assert np.isnan(z[0]);count+=1
        a[start:start+26,0]=np.nan
        z,source,b=fit_scores(a,ext,f,np.array([0]),40,lag,True)
        assert np.isnan(z[0]);count+=1
    return count


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output)
    holdings=pd.read_csv(out/'holdings.csv.gz')
    lookup={(c,v):g for (c,v),g in holdings.groupby(['case','variant'])}
    max_error=0.;count=0;short={}
    for file in sorted(out.glob('*__*_monthly.csv')):
        case,variant=file.name.removesuffix('_monthly.csv').split('__')
        frame=pd.read_csv(file)
        expect=list(pd.period_range(frame.month.iloc[0],frame.month.iloc[-1],freq='M').astype(str))
        assert list(frame.month)==expect and np.isfinite(frame[['gross','net25bp','turnover']]).all().all()
        g=lookup[(case,variant)];by_month={m:q for m,q in g.groupby('month')}
        previous={}
        for _,r in frame.iterrows():
            q=by_month.get(r.month,pd.DataFrame(columns=['ticker','weight','return']))
            w=dict(zip(q.ticker,q.weight));ret=dict(zip(q.ticker,q['return']))
            gross=sum(v*ret[t] for t,v in w.items())
            trade=sum(abs(w.get(t,0)-previous.get(t,0)) for t in w.keys()|previous.keys())
            net=(1-.0025*trade)*(1+gross)-1
            assert all(v>=0 for v in w.values()) and sum(w.values())<=1+1e-12
            assert abs(sum(w.values())-r.exposure)<1e-12
            max_error=max(max_error,abs(gross-r.gross),abs(trade-r.turnover),abs(net-r.net25bp))
            previous={t:v*(1+ret[t])/(1+gross) for t,v in w.items()}
            count+=1
        short[file.stem]=int(((frame.exposure>0)&(frame.holdings<6)).sum())
    assert count==8652 and max_error<1e-12,(count,max_error)
    table=pd.read_csv(out/'comparison.csv');metric_error=0.
    for _,row in table.iterrows():
        frame=pd.read_csv(out/f'{row.case}__{row.variant}_monthly.csv')
        bounds={'all':('1900-01','2099-12'),'common_2002':('2002-02','2026-10'),'through2025':('1900-01','2025-12'),'2002_2009':('2002-02','2009-12'),'2010_2019':('2010-01','2019-12'),'2020_2026':('2020-01','2026-10')}
        lo,hi=bounds[row.period];r=frame.loc[(frame.month>=lo)&(frame.month<=hi),row.cost].to_numpy()
        # 누적곱 대신 지수·로그식으로 CAGR과 MDD를 별도 계산한다.
        log_equity=np.r_[0,np.log1p(r).cumsum()]
        cagr=np.expm1(log_equity[-1]*12/len(r))
        mdd=np.expm1(log_equity-np.maximum.accumulate(log_equity)).min()
        metric_error=max(metric_error,abs(cagr-row.cagr),abs(mdd-row.mdd))
    assert metric_error<1e-12
    summary=json.loads((out/'summary.json').read_text())
    assert summary['download_status'].get('YFRateLimitError',0)==0,'요청제한 미해소: 보충자료를 완전한 조회 시도로 보고하지 않는다'
    # 사후 추가한 고정50:50 병행안 대 현금25% 대조. 진정한 미사용 검증 아님.
    blend=pd.read_csv(out/'supplemented_lag2__blend50_original_residual_monthly.csv')
    fixed=pd.read_csv(out/'supplemented_lag2__original_fixed75_monthly.csv')
    mask=blend.month<='2025-12';x=blend.loc[mask,'net25bp'].to_numpy();y=fixed.loc[mask,'net25bp'].to_numpy();n=len(x)
    rng=np.random.default_rng(20261110)
    idx=((rng.integers(0,n,size=(10000,(n+5)//6))[:,:,None]+np.arange(6))%n).reshape(10000,-1)[:,:n]
    delta=np.log1p(x)-np.log1p(y)
    rel=np.expm1(delta[idx].mean(axis=1)*12)
    sharpes=(x[idx].mean(axis=1)/x[idx].std(axis=1)-y[idx].mean(axis=1)/y[idx].std(axis=1))*np.sqrt(12)
    diagnostic={'note':'사후 추가한50:50·고정75대조,2025년까지,6개월블록10000회,다중비교보정없음,실현위험정확일치아님',
                'relative_annual_return':float(np.expm1(delta.mean()*12)),
                'relative_annual_ci95':list(np.quantile(rel,[.025,.975])),
                'sharpe_difference':float((x.mean()/x.std()-y.mean()/y.std())*np.sqrt(12)),
                'sharpe_difference_ci95':list(np.quantile(sharpes,[.025,.975]))}
    (out/'blend_diagnostic.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
    result={'synthetic_regression_and_source_checks':synthetic_checks(),'saved_variant_months_recomputed':count,'saved_holding_rows':len(holdings),'return_trade_cost_max_error':max_error,'log_form_cagr_mdd_max_error':metric_error,'fewer_than_six_invested_months':short,'live_comparison_error':summary['live_334_monthly_max_error'],'regression_reference_error':summary['independent_regression_error'],'future_truncation_checks':summary['future_truncation_checks']}
    result['script_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('usa500_residual*20261110.py')}
    (out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['fewer_than_six_invested_months','script_sha256']},indent=2))


if __name__=='__main__':main()
