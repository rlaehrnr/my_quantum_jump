"""KRX 원천 월별 재구성 vs 기존 아카이브 대조 + 2011 필터 진단.

python 기록/검토/kospi_overlap_audit.py --source-dir <marcap폴더> --output <새폴더>
라이브 파일을 수정하지 않고, 기존 전략 엔진에 입력만 교체한다.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils import calculator as c
from utils.archive_store import load_frames

MOM = ['1개월(%)','3개월(%)','6개월(%)','12개월(%)']
ENS = '앙상블 (50:50 전략)'


def reconstruct(source_dir):
    monthly, manifest = [], {}
    for year in range(2008, 2027):
        path = source_dir / f'marcap-{year}.parquet'
        d = pd.read_parquet(path)
        d = d[(d.MarketId == 'STK') & d.Code.str.endswith('0')].copy()
        d = d.sort_values(['Code','Date'])
        d['month'] = d.Date.dt.to_period('M')
        reference = d.Close - d.Changes
        valid = (d.Close > 0) & (reference > 0)
        # 기준가격 불능은 별도 기록. 거래 없는 선박펀드 등의 이상행을 수익률로 만들지 않음.
        d['factor'] = (d.Close / reference).where(valid)
        factors = d.groupby(['month','Code']).factor.prod(min_count=1).rename('month_factor')
        last_day = d.groupby('month').Date.transform('max')
        snap = d[d.Date == last_day].set_index(['month','Code'])
        snap = snap.join(factors)[['Date','Name','Close','Volume','Marcap','month_factor']]
        monthly.append(snap.reset_index())
        manifest[path.name] = {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'invalid_reference_rows':int((~valid).sum())}
        print(f'집계 {year}', flush=True)
    m = pd.concat(monthly, ignore_index=True)
    grid = pd.period_range('2008-01','2026-12',freq='M')
    f = m.pivot(index='month',columns='Code',values='month_factor').reindex(grid)
    level = f.cumprod()
    retmaps = {n:(level/level.shift(n)-1)*100 for n in [1,3,6,12]}
    close = m.pivot(index='month',columns='Code',values='Close').reindex(grid)
    rawret = (close/close.shift(1)-1)*100
    rows=[]
    for month, snapshot in m.groupby('month'):
        invest = month+1
        if not pd.Period('2010-01') <= invest <= pd.Period('2026-09'):
            continue
        snapshot = snapshot[(snapshot.Volume>0)&(snapshot.Close>0)&(snapshot.Marcap>0)]
        snapshot = snapshot.sort_values('Marcap',ascending=False).head(200)
        for rank, r in enumerate(snapshot.itertuples(), 1):
            code=r.Code
            row={'투자월':str(invest),'투자연도':invest.year,'종목선정일':str(r.Date.date()),'종목코드':code,'종목명':r.Name,'시가총액':r.Marcap,'종가':r.Close,'거래량':r.Volume,'순위':rank}
            for n,col in zip([1,3,6,12],MOM): row[col]=round(retmaps[n].at[month,code],2)
            row['이번달수익률']=round((f.at[invest,code]-1)*100,2)
            row['raw_return']=round(rawret.at[invest,code],2)
            rows.append(row)
    return pd.DataFrame(rows), manifest


def annual(r):
    return ((1+r[ENS]/100).groupby(r['투자월'].str[:4]).prod()-1)*100


def run(data, index, gold):
    data=data.copy()
    data[MOM+['이번달수익률']]=data[MOM+['이번달수익률']].fillna(0)
    # 앱 로더의 억원 단위 반올림까지 재현(동률 때 정렬 결과에도 영향).
    if '시가총액(억)' not in data:
        data['시가총액(억)']=(data['시가총액']/1e8).round(0)
    with patch.object(c,'_load_kospi_index',return_value=index),patch.object(c,'get_gold_krw_monthly',return_value=gold):
        return c.run_backtest_k200(data,2014,2026,6,True,(1,6),(1,2),30,30,trading_cost_pct=.25,gold_returns=gold.ret.to_dict(),use_gold=True,use_gold_ma=True,gold_ma_months=6)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-dir',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists(): raise SystemExit('새 출력 폴더를 지정하세요')
    args.output.mkdir(parents=True)
    new,manifest=reconstruct(args.source_dir)
    new.to_csv(args.output/'reconstructed.csv',index=False,encoding='utf-8-sig')
    previous=load_frames(str(ROOT/'기록/2026-11-05-KOSPI2010-자료검증/candidate_archive'))
    prior=new.merge(previous,on=['투자월','종목코드'],suffixes=('_new','_prior'))
    validation={col:float((prior[col+'_new']-prior[col+'_prior']).abs().max()) for col in MOM+['이번달수익률']}
    old=load_frames(str(ROOT/'archive_kospi'))
    old['종목코드']=old['종목코드'].astype(str).str.zfill(6)
    old=old[old['종목코드'].str.endswith('0') & old['투자월'].between('2014-02','2026-09')].copy()
    overlap=new[new['투자월'].between('2014-02','2026-09')].copy()
    merged=overlap.merge(old,on=['투자월','종목코드'],suffixes=('_new','_old'))
    comparisons=[]
    for month,g in merged.groupby('투자월'):
        rec={'투자월':month,'common_codes':len(g)}
        for col in MOM+['이번달수익률']:
            a=pd.to_numeric(g[col+'_new'],errors='coerce');b=pd.to_numeric(g[col+'_old'],errors='coerce')
            valid=a.notna()&b.notna()
            delta=(a-b).abs()
            rec[col+'_count']=int(valid.sum());rec[col+'_mae']=float(delta[valid].mean());rec[col+'_max']=float(delta[valid].max())
        comparisons.append(rec)
    pd.DataFrame(comparisons).to_csv(args.output/'field_comparison.csv',index=False,encoding='utf-8-sig')
    # 기존 모멘텀이 어느 관측월 수익에 대응하는지 대조. 미래 월과의 일치 여부도 검사.
    alignment=[]
    for shift in [-2,-1,0,1,2]:
        n=new[['투자월','종목코드','1개월(%)','이번달수익률']].copy()
        n['투자월']=(pd.PeriodIndex(n['투자월'],freq='M')+shift).astype(str)
        g=old[['투자월','종목코드','1개월(%)','이번달수익률']].merge(n,on=['투자월','종목코드'],suffixes=('_old','_new'))
        for col in ['1개월(%)','이번달수익률']:
            a=pd.to_numeric(g[col+'_old'],errors='coerce');b=pd.to_numeric(g[col+'_new'],errors='coerce'); valid=a.notna()&b.notna()
            alignment.append({'new_month_shift':shift,'field':col,'count':int(valid.sum()),'corr':float(a[valid].corr(b[valid])),'mae':float((a-b)[valid].abs().mean())})
    pd.DataFrame(alignment).to_csv(args.output/'month_alignment.csv',index=False,encoding='utf-8-sig')
    # 지수도 화면의 공통 공급 경로를 그대로 사용한다. Yahoo/Naver 차이로
    # MA 경계에 걸린 월의 투자 여부가 달라지는 것을 피한다.
    idx=c._load_kospi_index.__wrapped__()
    if idx.empty: raise RuntimeError('지수 시세 없음')
    if idx.index.tz is not None: idx.index=idx.index.tz_localize(None)
    idx.index=idx.index.normalize()
    idx.to_csv(args.output/'source_kospi.csv',encoding='utf-8-sig')
    spot=pd.read_csv(ROOT/'data/krx_gold_price.csv',parse_dates=['날짜']).set_index('날짜')['종가'].sort_index()
    ext=pd.read_csv(ROOT/'data/krx_gold_recent.csv',parse_dates=['날짜']).set_index('날짜')['종가'].sort_index()
    last=spot.index.max(); factor=spot.iloc[-1]/ext[ext.index<=last].iloc[-1]
    daily=pd.concat([spot,ext[ext.index>last]*factor])
    gold=daily.groupby(daily.index.to_period('M')).last().to_frame('price');gold.index=gold.index.astype(str);gold['ret']=gold.price.pct_change()*100
    gold.to_csv(args.output/'common_gold.csv',encoding='utf-8-sig')
    variants={'old':old,'reconstructed':overlap}
    # 동일한 기존 종목집합 안에서 모멘텀·보유수익 교체 효과를 따로 본다.
    for kind,fields in [('old_new_momentum',MOM),('old_new_forward',['이번달수익률']),('old_new_both',MOM+['이번달수익률'])]:
        d=old.merge(overlap[['투자월','종목코드']+fields],on=['투자월','종목코드'],how='left',suffixes=('','_replacement'))
        for col in fields:
            match=overlap.set_index(['투자월','종목코드']).index
            matched=pd.MultiIndex.from_frame(d[['투자월','종목코드']]).isin(match)
            d.loc[matched,col]=d.loc[matched,col+'_replacement']
            d=d.drop(columns=col+'_replacement')
        variants[kind]=d
    outputs={};annuals={}
    for label,d in variants.items():
        r,t,details=run(d,idx,gold)
        r.to_csv(args.output/f'{label}_monthly.csv',index=False,encoding='utf-8-sig')
        t.to_csv(args.output/f'{label}_trades.csv',index=False,encoding='utf-8-sig')
        outputs[label]=r;annuals[label]=annual(r)
        print(label,annual(r).round(3).to_dict(),flush=True)
    pd.DataFrame(annuals).to_csv(args.output/'annual_comparison.csv',encoding='utf-8-sig')
    # 2011 원가격이 아닌 기존 예비 결과 기준으로 필터의 실제/공격 반사실을 검산.
    folder=ROOT/'기록/2026-11-05-KOSPI2010-자료검증'
    # 현재 Naver 경로가 최근 3000행만 주면 2011을 포함하지 못한다.
    # 2011 진단은 예비 실험 당시 저장해 둔 Yahoo 지수를 사용한다.
    diagnostic_idx=pd.read_csv(folder/'source_kospi.csv',index_col=0,parse_dates=True)
    diagnostic_idx.index=pd.to_datetime(diagnostic_idx.index,utc=True).tz_localize(None).normalize()
    detail=pd.read_csv(folder/'research_details.csv'); y=detail[detail['투자월'].str.startswith('2011')].copy()
    atk=ENS+' · 공격시_수익률(%)'
    diag={'actual_annual':float(((1+y[ENS]/100).prod()-1)*100),'always_attack_annual':float(((1+y[atk]/100).prod()-1)*100)}
    for mode,mask in [('stock',y.invested),('defense',~y.invested)]:
        diag[mode+'_months']=int(mask.sum());diag[mode+'_compound']=float(((1+y.loc[mask,ENS]/100).prod()-1)*100)
    archive=previous[previous['투자월'].str.startswith('2011')]
    ma=diagnostic_idx.Close.rolling(120).mean()
    for i,row in y.iterrows():
        s=archive[archive['투자월']==row['투자월']];date=pd.Timestamp(s['종목선정일'].iloc[0]); ix=diagnostic_idx[diagnostic_idx.index<=date].index[-1]
        y.loc[i,'선정일']=str(date.date());y.loc[i,'음수1M']=int((s['1개월(%)']<0).sum());y.loc[i,'음수3M']=int((s['3개월(%)']<0).sum())
        y.loc[i,'KOSPI']=float(diagnostic_idx.loc[ix,'Close']);y.loc[i,'120MA']=float(ma.loc[ix]);y.loc[i,'MA이탈']=bool(diagnostic_idx.loc[ix,'Close']<ma.loc[ix])
    y.to_csv(args.output/'2011_filter_diagnosis.csv',index=False,encoding='utf-8-sig')
    insufficient=[]
    for month,g in old.groupby('투자월'):
        if len(idx[idx.index<=pd.Timestamp(g['종목선정일'].iloc[0])])<120: insufficient.append(month)
    report={'index_source_start':str(idx.index.min().date()),'index_source_rows':len(idx),'index_warmup_insufficient_months':insufficient,'prior_reconstruction_max_errors':validation,'source_manifest':manifest,'2011':diag,'annual':{k:v.to_dict() for k,v in annuals.items()}}
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'validation':validation,'2011':diag},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__': main()
