"""재구성 주식 자료의 2010-01~2026-10 연속 백테스트. 라이브 파일 변경 없음."""
import argparse
from decimal import Decimal, getcontext
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

import FinanceDataReader as fdr
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from utils import calculator as c


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-dir',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists(): raise SystemExit('새 출력 폴더가 필요합니다')
    args.output.mkdir(parents=True)
    spec=importlib.util.spec_from_file_location('overlap',Path(__file__).with_name('kospi_overlap_audit.py'))
    audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    stocks,manifest=audit.reconstruct(args.source_dir,'2026-10')
    expected=pd.period_range('2010-01','2026-10',freq='M').astype(str).tolist()
    assert stocks.groupby('투자월').size().reindex(expected).eq(200).all()
    stocks.to_csv(args.output/'reconstructed_stocks.csv',index=False,encoding='utf-8-sig')
    naver=c._load_kospi_index.__wrapped__()
    historical=yf.Ticker('^KS11').history(start='2008-01-01',end='2026-11-01',auto_adjust=False)
    if historical.empty or naver.empty: raise RuntimeError('KOSPI 시세 없음')
    historical.index=historical.index.tz_localize(None).normalize()
    joint=naver.index.intersection(historical.index)[0]
    scale=naver.loc[joint,'Close']/historical.loc[joint,'Close']
    index=pd.concat([historical.loc[historical.index<naver.index.min(),['Close']]*scale,naver[['Close']]])
    index=index[index.index<='2026-10-31']
    assert index.index.min()<pd.Timestamp('2009-01-01')
    assert index.index.max()==pd.Timestamp('2026-10-30')
    index.to_csv(args.output/'source_kospi_complete.csv',encoding='utf-8-sig')
    etf=fdr.DataReader('411060','2021-12-15','2026-10-31')['Close'].dropna()
    etf.index=pd.to_datetime(etf.index).normalize()
    assert etf.index.max()==pd.Timestamp('2026-10-30')
    etf.to_csv(args.output/'source_gold_etf.csv',encoding='utf-8-sig')
    spot=pd.read_csv(ROOT/'data/krx_gold_price.csv',parse_dates=['날짜']).set_index('날짜')['종가'].sort_index()
    last=spot.index.max();factor=spot.iloc[-1]/etf[etf.index<=last].iloc[-1]
    real=pd.concat([spot,etf[etf.index>last]*factor])
    previous=ROOT/'기록/2026-11-05-KOSPI2010-자료검증'
    proxy_sources=[]
    for name in ['gold_futures','usdkrw']:
        src=pd.read_csv(previous/f'source_{name}.csv',index_col=0)
        # CSV의 거래일 라벨을 보존. UTC 변환은 영국 서머타임 환율의 날짜를
        # 전날로 밀 수 있으므로 날짜 문자열만 먼저 읽는다.
        src.index=pd.to_datetime(src.index.astype(str).str[:10])
        proxy_sources.append(src['Close'])
    proxy=pd.concat(proxy_sources,axis=1,keys=['gold','fx'],sort=True).sort_index().ffill().dropna()
    proxy.index+=pd.Timedelta(days=1)
    price=proxy.gold*proxy.fx/31.1035
    # 한국 선정일 이후 확정되는 미국 종가의 참조를 막는다.
    price=price.reindex(price.index.union(index.index)).sort_index().ffill().reindex(index.index).dropna()
    first=real.index.min();proxy_factor=real.iloc[0]/price.loc[first]
    daily=pd.concat([price[price.index<first]*proxy_factor,real])
    daily=daily[daily.index<='2026-10-31']
    daily.to_csv(args.output/'gold_daily_combined.csv',encoding='utf-8-sig')
    gold=daily.groupby(daily.index.to_period('M')).last().to_frame('price')
    gold.index=gold.index.astype(str);gold['ret']=gold.price.pct_change()*100
    gold.to_csv(args.output/'gold_monthly.csv',encoding='utf-8-sig')
    for col in audit.MOM+['이번달수익률']: stocks[col]=stocks[col].fillna(0)
    stocks['시가총액(억)']=(stocks['시가총액']/1e8).round(0)
    with patch.object(c,'_load_kospi_index',return_value=index),patch.object(c,'get_gold_krw_monthly',return_value=gold):
        r,t,detail=c.run_backtest_k200(stocks,2010,2026,6,True,(1,6),(1,2),30,30,trading_cost_pct=.25,gold_returns=gold.ret.to_dict(),use_gold=True,use_gold_ma=True,gold_ma_months=6)
    assert r['투자월'].tolist()==expected and len(r)==202
    r.to_csv(args.output/'monthly_returns.csv',index=False,encoding='utf-8-sig')
    t.to_csv(args.output/'trades.csv',index=False,encoding='utf-8-sig')
    detail.to_csv(args.output/'details.csv',index=False,encoding='utf-8-sig')
    getcontext().prec=45
    stats={}
    for col in r:
        if col in ['투자월','invested','중지 사유']:continue
        wealth=Decimal(1);peak=wealth;worst=Decimal(0)
        for x in r[col]:
            wealth*=1+Decimal(str(x))/100;peak=max(peak,wealth);worst=min(worst,wealth/peak-1)
        cagr=(wealth**(Decimal(12)/202)-1)*100
        # pandas 경로와 독립 Decimal 경로의 일치 확인.
        curve=pd.concat([pd.Series([1.]),(1+r[col]/100).cumprod()],ignore_index=True)
        assert abs(float(cagr)-(curve.iloc[-1]**(12/202)-1)*100)<1e-10
        assert abs(float(worst)*100-(curve/curve.cummax()-1).min()*100)<1e-10
        stats[col]={'cagr_pct':float(cagr),'monthly_mdd_pct':float(worst*100),'final_multiple':float(wealth),'october_2026_return_pct':float(r[col].iloc[-1])}
    annual=((1+r[list(stats)]/100).groupby(r['투자월'].str[:4]).prod()-1)*100
    annual.to_csv(args.output/'annual_returns.csv',encoding='utf-8-sig')
    report={'period':['2010-01','2026-10'],'months':202,'stats':stats,'stock_source_manifest':manifest,
            'index_join':str(joint.date()),'index_prefix_scale':float(scale),
            'gold_proxy_join':str(first.date()),'gold_proxy_scale':float(proxy_factor),
            'assumptions':['월말 MDD; 최초 원금1 포함','편도0.25%·엔진 왕복0.5% 비용','KRX 금 개장 전 국제금x환율 대체값, 미국/FX 관측 1달력일 지연','과거지수 Yahoo+현재Naver 접합, 120거래일 초기 이력 확보','종목 기업행동 기준가격 방식, 배당/인적분할 신주/상폐정산 미검증 예외 존재','라이브 코드와 아카이브는 변경하지 않음']}
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'months':202,'stats':stats,'last_index_day':str(index.index.max().date()),'last_gold_day':str(etf.index.max().date())},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
