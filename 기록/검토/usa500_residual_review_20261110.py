"""USA500 잔차 모멘텀 연구. 라이브 코드·상수·운영 data 변경 없음.

논문식36개월 OLS(절편 포함), 12-1M 잔차 평균/표준편차.
lag1=직전월까지 회귀, lag2=공표지연 근사로 직전월을 회귀에서도 제외.
역사자료만 쓰는 통제와, 과거시점 중첩검사를 통과한 Yahoo 이력 보충을 분리.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

from usa500_filter_review_20261110 import metrics, simulate, exposure_map, price_series


def fit_scores(archive, yahoo, factors, ids, month_pos, lag, supplement):
    """모든 검사는 이 회귀창 안의 과거 관측만 쓴다. 결측을0으로 채우지 않는다."""
    end = month_pos - lag + 1
    start = end - 36
    y = archive[start:end, ids].copy()
    original_ready = np.isfinite(y).all(axis=0)
    source = np.where(original_ready, 'archive', 'missing').astype(object)
    external = yahoo[start:end, ids]
    if supplement:
        candidates = np.where(~original_ready & np.isfinite(external).all(axis=0))[0]
        for j in candidates:
            overlap = np.isfinite(y[:, j]) & np.isfinite(external[:, j])
            if overlap.sum() < 12:
                continue
            diff = np.abs(y[overlap, j] - external[overlap, j])
            # 서로 다른 티커/가격정의를 섞지 않기 위한 사전 품질 기준.
            if np.median(diff) <= .001 and np.quantile(diff, .95) <= .01:
                y[:, j] = external[:, j]
                source[j] = 'yahoo_full_window'
    ready = np.isfinite(y).all(axis=0)
    score = np.full(len(ids), np.nan)
    beta = np.full((4, len(ids)), np.nan)
    f = factors[start:end]
    if len(f) != 36 or not np.isfinite(f).all():
        return score, source, beta
    x = np.column_stack([np.ones(36), f[:, :3]])
    excess = y[:, ready] - f[:, 3, None]
    b = np.linalg.pinv(x) @ excess
    residual = excess - x @ b  # 절편 alpha도 제거하며 score에 다시 더하지 않는다.
    formation = residual[-12:-1] if lag == 1 else residual[-11:]
    sd = formation.std(axis=0, ddof=1)
    z = np.divide(formation.mean(axis=0), sd, out=np.full(len(sd), np.nan), where=sd > 1e-10)
    score[ready], beta[:, ready] = z, b
    return score, source, beta


def parse_factors(path):
    raw = path.read_text(encoding='utf-8-sig')
    lines = [l for l in raw.splitlines() if len(l.split(',')[0].strip()) == 6 and l.split(',')[0].strip().isdigit()]
    f = pd.read_csv(io.StringIO('\n'.join(lines)), header=None, names=['month','Mkt-RF','SMB','HML','RF'])
    f.index = pd.PeriodIndex(f.month.astype(str), freq='M')
    return f[['Mkt-RF','SMB','HML','RF']] / 100


def run():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    root, out = Path(a.snapshot).resolve(), Path(a.output).resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    from utils import us_helpers as uh
    from utils.data_loader import load_archive_data
    raw = load_archive_data.__wrapped__('archive_usa', None)
    # 시계열 추정용 원수익은 전처리의 fillna(0)를 거치지 않는다.
    history_raw = raw.copy()
    history_raw['month'] = (pd.to_datetime(history_raw['종목선정일']).dt.to_period('M') + 1)
    history_raw['종목코드'] = history_raw['종목코드'].astype(str)
    history_raw['ret'] = pd.to_numeric(history_raw['이번달수익률'], errors='coerce') / 100
    history_raw = history_raw[history_raw.month <= pd.Period('2026-10')]
    assert not history_raw.duplicated(['month','종목코드']).any()
    master = uh.preprocess_us_data(raw, is_daily=False)
    master = master[master['투자월'] <= '2026-10'].copy()
    ticks = sorted(master['종목코드'].unique())
    lookup = {t:i for i,t in enumerate(ticks)}
    dates = pd.period_range('1995-01', '2026-10', freq='M')
    date_index = {str(m):i for i,m in enumerate(dates)}
    hist = history_raw.pivot(index='month', columns='종목코드', values='ret').reindex(index=dates, columns=ticks)
    archive = hist.to_numpy()
    yahoo_frame = pd.DataFrame(np.nan, index=dates, columns=ticks)
    price_frames = []
    for file in sorted((out/'monthly_prices').glob('*.csv')):
        q = pd.read_csv(file)
        q['month'] = pd.to_datetime(q.date).dt.to_period('M')
        q = q.drop_duplicates('month', keep='last').set_index('month').sort_index()
        if 'Adj Close' not in q: continue
        s = q['Adj Close'].reindex(dates)
        yahoo_frame[file.stem] = s.pct_change(fill_method=None)
        price_frames.append(q.reset_index().assign(ticker=file.stem))
    pd.concat(price_frames).to_csv(out/'downloaded_monthly_prices.csv.gz', index=False, compression={'method':'gzip','mtime':0})
    yahoo = yahoo_frame.reindex(columns=ticks).to_numpy()
    factor_frame = parse_factors(out/'F-F_Research_Data_Factors.csv')
    factors = factor_frame.reindex(dates).to_numpy()
    spy = price_series(root, 'SPY')
    timing = exposure_map(spy, 'ma12')
    px = pd.DataFrame({t:price_series(root,t) for t in ['TIP','VWO','VEA','VIXY']})
    r6 = px / px.shift(6) - 1
    ready = r6.notna().all(axis=1)
    cond = (r6[['TIP','VWO','VEA']] < 0).all(axis=1) & ((r6.VIXY < 0) | (r6.VIXY >= .4))
    m4 = {(p+1).strftime('%Y-%m'):bool(cond.loc[p]) for p in px.index if ready.loc[p]}
    groups = {m:d.sort_values('시가총액',ascending=False).head(500).copy() for m,d in master.groupby('투자월')}
    months = sorted(groups)
    stock_returns = master.pivot(index='투자월', columns='종목코드', values='이번달수익률').reindex(index=months, columns=ticks).fillna(0).to_numpy()/100
    pools = {m:uh.get_triple_momentum_us(g,100,'rank') for m,g in groups.items()}
    base_w = np.zeros_like(stock_returns)
    for i,m in enumerate(months):
        picks = pools[m].iloc[2:8]
        e = timing.get(m,1.) if not m4.get(m,False) else 0.
        if len(picks): base_w[i,[lookup[t] for t in picks['종목코드']]] = e/len(picks)
    all_rows, all_scores, coverage, bootstrap, sensitivity = [], [], [], {}, []
    monthly_frames = {}
    holding_rows = []
    base_gross, _, _ = simulate(base_w, stock_returns)
    independent_error = 0.
    for model, supplement in [('archive_only',False), ('supplemented',True)]:
        for lag in [1,2]:
            case = f'{model}_lag{lag}'
            variants = {v:np.zeros_like(stock_returns) for v in ['eligible_triple','residual_in_triple','residual_all_top6','raw12_all_top6']}
            for i,m in enumerate(months):
                g = groups[m]
                ids = np.array([lookup[t] for t in g['종목코드']])
                z, source, beta = fit_scores(archive,yahoo,factors,ids,date_index[m],lag,supplement)
                scored = g.assign(residual_score=z, history_source=source)
                valid = scored[np.isfinite(z)].copy()
                coverage.append({'case':case,'month':m,'eligible':len(valid),'archive':int((valid.history_source=='archive').sum()),'yahoo':int((valid.history_source=='yahoo_full_window').sum())})
                if m < ('2000-02' if supplement else '2002-02'): continue
                q = valid[['종목코드','residual_score','history_source']].copy()
                q.columns = ['ticker','score','source'];q['case']=case;q['month']=m
                for k,label in enumerate(['alpha','beta_market','beta_size','beta_value']):
                    q[label]=beta[k,np.isfinite(z)]
                all_scores.append(q)
                # 같은 후보 집합에서 기존 모멘텀 순위와 잔차 순위를 비교한다.
                pool = pools[m][pools[m]['종목코드'].isin(valid['종목코드'])].copy()
                score_map = valid.set_index('종목코드')['residual_score']
                pool['residual_score'] = pool['종목코드'].map(score_map)
                chosen = {
                    'eligible_triple':pool.iloc[2:8],
                    'residual_in_triple':pool.sort_values('residual_score',ascending=False).iloc[2:8],
                    'residual_all_top6':valid.sort_values('residual_score',ascending=False).head(6),
                    'raw12_all_top6':uh.calc_us_momentum(valid).sort_values('12-1개월(%)',ascending=False).head(6),
                }
                e = timing.get(m,1.) if not m4.get(m,False) else 0.
                for v,picks in chosen.items():
                    if len(picks): variants[v][i,[lookup[t] for t in picks['종목코드']]] = e/len(picks)
                # 매50개월 첫 유효종목은 lstsq로 독립 회귀·잔차를 대조한다.
                if i%50==0 and len(valid):
                    j = int(np.flatnonzero(np.isfinite(z))[0]);t=ids[j]
                    end=date_index[m]-lag+1;begin=end-36
                    y = archive[begin:end,t] if source[j]=='archive' else yahoo[begin:end,t]
                    f=factors[begin:end];x=np.column_stack([np.ones(36),f[:,:3]])
                    b=np.linalg.lstsq(x,y-f[:,3],rcond=None)[0]
                    residual=y-f[:,3]-x@b
                    formation=residual[-12:-1] if lag==1 else residual[-11:]
                    expected=formation.mean()/formation.std(ddof=1)
                    independent_error=max(independent_error,abs(expected-z[j]),float(np.max(np.abs(b-beta[:,j]))))
            variants['original_triple'] = base_w
            # 기존 규칙과의 병행을 고정50:50 한 안만 진단한다. 비중 최적화 없음.
            variants['blend50_original_residual'] = .5*base_w + .5*variants['residual_all_top6']
            variants['original_fixed75'] = .75*base_w
            for name,w in variants.items():
                begin = '2000-02' if supplement else '2002-02'
                mask=np.array(months)>=begin
                w=w[mask];ret=stock_returns[mask];ms=np.array(months)[mask]
                assert np.all(w>=0) and np.all(w.sum(axis=1)<=1+1e-12)
                gross,net,turnover=simulate(w,ret)
                frame=pd.DataFrame({'month':ms,'gross':gross,'net25bp':net,'turnover':turnover,'exposure':w.sum(axis=1),'holdings':(w>0).sum(axis=1)})
                key=f'{case}__{name}';monthly_frames[key]=frame
                frame.to_csv(out/f'{key}_monthly.csv',index=False)
                for bp in [10,25,50]:
                    _,cost_net,_=simulate(w,ret,bp/10000)
                    sensitivity.append({'case':case,'variant':name,'one_way_bp':bp,**metrics(cost_net)})
                for ii,jj in np.argwhere(w>0): holding_rows.append({'case':case,'variant':name,'month':ms[ii],'ticker':ticks[jj],'weight':w[ii,jj],'return':ret[ii,jj]})
                for period,lo,hi in [('all',begin,'2026-10'),('common_2002','2002-02','2026-10'),('through2025',begin,'2025-12'),('2002_2009','2002-02','2009-12'),('2010_2019','2010-01','2019-12'),('2020_2026','2020-01','2026-10')]:
                    part=frame[(frame.month>=lo)&(frame.month<=hi)]
                    for column in ['gross','net25bp']:
                        all_rows.append({'case':case,'variant':name,'period':period,'cost':column,**metrics(part[column]),'mean_exposure':float(part.exposure.mean()),'mean_holdings_when_invested':float(part.loc[part.exposure>0,'holdings'].mean())})
            # 같은 월의 쌍을 보존하는 블록 추출. 사후 탐색이며 미사용 검증이 아니다.
            rng=np.random.default_rng(20261110)
            for alternative,control in [('residual_in_triple','eligible_triple'),('residual_all_top6','raw12_all_top6')]:
                aa=monthly_frames[f'{case}__{alternative}'];bb=monthly_frames[f'{case}__{control}']
                mask=aa.month<='2025-12';delta=np.log1p(aa.loc[mask,'net25bp'].to_numpy())-np.log1p(bb.loc[mask,'net25bp'].to_numpy());n=len(delta)
                idx=((rng.integers(0,n,size=(10000,(n+5)//6))[:,:,None]+np.arange(6))%n).reshape(10000,-1)[:,:n]
                samples=np.expm1(delta[idx].mean(axis=1)*12)
                bootstrap[f'{case}__{alternative}']={'control':control,'relative_annual_return':float(np.expm1(delta.mean()*12)),'interval95':list(np.quantile(samples,[.025,.975]))}
    table=pd.DataFrame(all_rows);table.to_csv(out/'comparison.csv',index=False)
    pd.DataFrame(sensitivity).to_csv(out/'cost_sensitivity.csv',index=False)
    pd.concat(all_scores).to_csv(out/'signal_scores.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    pd.DataFrame(holding_rows).to_csv(out/'holdings.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    pd.DataFrame(coverage).to_csv(out/'coverage.csv',index=False)
    uh.get_spy_timing_map=lambda n:{m:v==0 for m,v in timing.items()};uh.get_multi4_cond1_map=lambda:m4
    live,_=uh.run_backtest_triple_us_m4.__wrapped__(master,1999,2026,12,True,True,100,3,8,pd.DataFrame(),universe_n=500)
    live_error=float(np.max(np.abs(live['🛡️ 3·6·12 교집합 + 멀티4'].to_numpy()/100-base_gross)))
    assert live_error<1e-12 and independent_error<1e-10,(live_error,independent_error)
    # 3시점에서 미래 입력을 잘라도 회귀·공급원 결정·점수가 동일해야 한다.
    for m in ['2009-12','2019-12','2025-12']:
        pos=date_index[m];ids=np.array([lookup[t] for t in groups[m]['종목코드']])
        for lag in [1,2]:
            for sup in [False,True]:
                z,source,b=fit_scores(archive,yahoo,factors,ids,pos,lag,sup)
                zz,ss,bb=fit_scores(archive[:pos],yahoo[:pos],factors[:pos],ids,pos,lag,sup)
                assert np.allclose(z,zz,equal_nan=True) and np.array_equal(source,ss) and np.allclose(b,bb,equal_nan=True)
    source_hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'monthly_prices').glob('*.csv')}
    source_hashes['F-F_Research_Data_Factors.csv']=hashlib.sha256((out/'F-F_Research_Data_Factors.csv').read_bytes()).hexdigest()
    (out/'input_sha256.json').write_text(json.dumps(source_hashes,indent=2),encoding='utf-8')
    download_status=pd.read_csv(out/'download_status.csv')
    summary={'input_commit':(root/'commit.txt').read_text().strip(),'factor_last_month':str(factor_frame.index.max()),'downloaded_tickers':len(price_frames),'download_status':{str(k):int(v) for k,v in download_status.groupby('status').size().items()},'archive_tickers':len(ticks),'live_334_monthly_max_error':live_error,'independent_regression_error':independent_error,'future_truncation_checks':12,'bootstrap':bootstrap,'lag2_publication_assumption':'month t trade: regression through t-2; exact historical publication timestamps and data vintages not verified','original_full_334_month_gross':metrics(base_gross)}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='bootstrap'},ensure_ascii=False,indent=2))
    print(table[(table.period=='all')&(table.cost=='gross')][['case','variant','months','cagr','mdd','sharpe']].to_string(index=False))


if __name__=='__main__':
    warnings.filterwarnings('ignore',category=RuntimeWarning)
    run()
