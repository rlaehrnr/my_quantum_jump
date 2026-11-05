"""퍼펙트1~6 고정, 달리는말1~2 vs 1~4. 저장된202개월 입력으로만 비교한다."""
import argparse
from decimal import Decimal, getcontext
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from utils import calculator as c

PERF='🔥 퍼펙트 상승 (1~6위)'
ENS='앙상블 (50:50 전략)'


def stats(series):
    getcontext().prec=45
    wealth=Decimal(1);peak=wealth;worst=Decimal(0)
    for x in series:
        wealth*=1+Decimal(str(x))/100
        peak=max(peak,wealth);worst=min(worst,wealth/peak-1)
    curve=pd.concat([pd.Series([1.]),(1+series/100).cumprod()],ignore_index=True)
    cagr=float((wealth**(Decimal(12)/len(series))-1)*100)
    mdd=float(worst*100)
    assert abs(cagr-(curve.iloc[-1]**(12/len(series))-1)*100)<1e-10
    assert abs(mdd-(curve/curve.cummax()-1).min()*100)<1e-10
    return {'months':len(series),'cagr_pct':cagr,'monthly_mdd_pct':mdd,'worst_month_pct':float(series.min()),'final_multiple':float(wealth)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=ROOT/'기록/2026-11-05-KOSPI-2010-202610-확정')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists(): raise SystemExit('새 출력폴더를 지정하세요')
    stocks=pd.read_csv(args.input/'reconstructed_stocks.csv',dtype={'종목코드':str})
    cols=['1개월(%)','3개월(%)','6개월(%)','12개월(%)','이번달수익률']
    stocks[cols]=stocks[cols].fillna(0)
    stocks['시가총액(억)']=(stocks['시가총액']/1e8).round(0)
    index=pd.read_csv(args.input/'source_kospi_complete.csv',index_col=0,parse_dates=True)
    gold=pd.read_csv(args.input/'gold_monthly.csv',index_col=0)
    results={};trades={}
    with patch.object(c,'_load_kospi_index',return_value=index),patch.object(c,'get_gold_krw_monthly',return_value=gold):
        for count in [2,4]:
            r,t,d=c.run_backtest_k200(stocks,2010,2026,6,True,(1,6),(1,count),30,30,trading_cost_pct=.25,gold_returns=gold.ret.to_dict(),use_gold=True,use_gold_ma=True,gold_ma_months=6)
            assert len(r)==202 and r['투자월'].tolist()==pd.period_range('2010-01','2026-10',freq='M').astype(str).tolist()
            results[count]=r;trades[count]=t
    baseline=pd.read_csv(args.input/'monthly_returns.csv')
    # CSV 왕복 때 빈 문자열이 NaN으로 읽히는 텍스트 열만 복원한다.
    baseline['중지 사유']=baseline['중지 사유'].fillna('')
    pd.testing.assert_frame_equal(results[2],baseline,check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    pd.testing.assert_series_equal(results[2][PERF],results[4][PERF])
    pd.testing.assert_frame_equal(results[2][['투자월','invested','중지 사유']],results[4][['투자월','invested','중지 사유']])
    # 종목별 거래기록에서 별도 평균·비용 계산으로 달리는말과 앙상블을 검산한다.
    max_error=0.
    for count,r in results.items():
        for row in r[r.invested].itertuples(index=False,name=None):
            month=row[0];t=trades[count]
            sample=t[(t['투자월']==month)&(t['전략']=='달리는말')]['수익률(%)']
            independent=(sample.mean() if len(sample) else 0)-.5
            actual=r.loc[r['투자월']==month,f'🐎 달리는 말 (1~{count}위)'].iloc[0]
            max_error=max(max_error,abs(independent-actual))
    assert max_error<1e-10
    args.output.mkdir(parents=True)
    annuals={};report={}
    for count,r in results.items():
        r.to_csv(args.output/f'top{count}_monthly.csv',index=False,encoding='utf-8-sig')
        trades[count].to_csv(args.output/f'top{count}_trades.csv',index=False,encoding='utf-8-sig')
        yearly=(1+r[[ENS,f'🐎 달리는 말 (1~{count}위)']]/100).groupby(r['투자월'].str[:4]).prod().sub(1).mul(100)
        annuals[f'앙상블_top{count}']=yearly[ENS]
        report[str(count)]={'ensemble':stats(r[ENS]),'running_horse':stats(r[f'🐎 달리는 말 (1~{count}위)'])}
        report[str(count)]['segments']={}
        for start,end in [('2010-01','2013-12'),('2014-01','2019-12'),('2020-01','2026-10')]:
            report[str(count)]['segments'][start+'~'+end]=stats(r.loc[r['투자월'].between(start,end),ENS])
    pd.DataFrame(annuals).to_csv(args.output/'annual_comparison.csv',encoding='utf-8-sig')
    diff=results[4][ENS]-results[2][ENS]
    metadata={'results':report,'top4_better_months':int((diff>1e-10).sum()),'top4_worse_months':int((diff< -1e-10).sum()),'same_months':int((diff.abs()<=1e-10).sum()),
              'independent_trade_aggregation_max_error':max_error,'baseline_reproduced':True,
              'input_sha256':{name:hashlib.sha256((args.input/name).read_bytes()).hexdigest() for name in ['reconstructed_stocks.csv','source_kospi_complete.csv','gold_monthly.csv']},
              'assumptions':['퍼펙트1~6 고정, 달리는말1~2/1~4만 비교','필터·금방어·비용·202개월 입력 동일','기간 구간분석은 연속운용 월수익을 잘라 초기원금1로 환산','인적분할/상폐정산 미검증 및 2014이전 금프록시 한계 동일','사후 비교이며 독립 표본외 검증 아님; 라이브 변경 없음']}
    (args.output/'summary.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False,indent=2),flush=True)
    print(pd.DataFrame(annuals).round(4).to_string(),flush=True)


if __name__=='__main__':main()
