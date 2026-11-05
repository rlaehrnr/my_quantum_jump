"""1~2위 유지, 사전 고정한 8개 위험관리 대안 비교. 연구 전용."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from utils import calculator as c

ENS='앙상블 (50:50 전략)'
PERF='🔥 퍼펙트 상승 (1~6위)'
HORSE='🐎 달리는 말 (1~2위)'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=ROOT/'기록/2026-11-05-KOSPI-2010-202610-확정')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise SystemExit('새 출력폴더를 지정하세요')
    spec=importlib.util.spec_from_file_location('top4',Path(__file__).with_name('kospi_top4_comparison.py'))
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    stats=helper.stats
    source=args.input
    stocks=pd.read_csv(source/'reconstructed_stocks.csv',dtype={'종목코드':str})
    cols=['1개월(%)','3개월(%)','6개월(%)','12개월(%)','이번달수익률']
    stocks[cols]=stocks[cols].fillna(0);stocks['시가총액(억)']=(stocks['시가총액']/1e8).round(0)
    index=pd.read_csv(source/'source_kospi_complete.csv',index_col=0,parse_dates=True)
    gold=pd.read_csv(source/'gold_monthly.csv',index_col=0)
    baseline=pd.read_csv(source/'monthly_returns.csv');baseline['중지 사유']=baseline['중지 사유'].fillna('')
    detail=pd.read_csv(source/'details.csv')

    def run(ma=6,gma=6,use_gold=True):
        with patch.object(c,'_load_kospi_index',return_value=index),patch.object(c,'get_gold_krw_monthly',return_value=gold):
            return c.run_backtest_k200(stocks,2010,2026,ma,True,(1,6),(1,2),30,30,trading_cost_pct=.25,gold_returns=gold.ret.to_dict(),use_gold=use_gold,use_gold_ma=use_gold,gold_ma_months=gma)

    actual,_,_=run()
    pd.testing.assert_frame_equal(actual,baseline,check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    returns=pd.DataFrame({'투자월':baseline['투자월'],'baseline':baseline[ENS]})
    exposure=pd.DataFrame({'투자월':baseline['투자월']})
    # 비중은 전월 말에 결정. 현금금리0, 레버리지 없음.
    returns['portfolio_75_cash25']=baseline[ENS]*.75
    stock_weight=pd.Series(np.where(baseline.invested,.75,1.))
    returns['stock_75_cash25']=baseline[ENS]*stock_weight
    returns['perfect75_horse25']=baseline[PERF]*.75+baseline[HORSE]*.25
    assert (returns.loc[~baseline.invested,'perfect75_horse25']-baseline.loc[~baseline.invested,ENS]).abs().max()<1e-10
    past_vol=(baseline[ENS]/100).rolling(12).std(ddof=1).mul(np.sqrt(12)).shift(1)
    risk_weight=(.15/past_vol).clip(upper=1).fillna(1)
    returns['vol_target15']=baseline[ENS]*risk_weight
    exposure['vol_target15']=risk_weight
    exposure['past_12m_annual_vol']=past_vol
    # 12개월이 쌓일 때까지 비중1. 미래 손실로 초기 비중을 줄이지 않는다.
    assert risk_weight.iloc[:12].eq(1).all() and risk_weight.between(0,1).all()
    outputs={}
    for label,kwargs in [('index_ma3',{'ma':3}),('gold_ma3',{'gma':3}),('cash_defense_no_gold',{'use_gold':False})]:
        r,t,d=run(**kwargs)
        assert r['투자월'].equals(baseline['투자월'])
        returns[label]=r[ENS]
        outputs[label]=(r,t,d)
    extension=baseline['중지 사유'].str.contains('하락장 연장',regex=False)
    returns['no_gold_extension']=baseline[ENS].where(~extension,detail[ENS+' · 공격시_수익률(%)'])
    assert len(returns)==202 and returns.drop(columns='투자월').notna().all().all()

    # 월말MDD 구간을 주식·금·현금의 로그수익 기여로 분해.
    wealth=pd.concat([pd.Series([1.]),(1+baseline[ENS]/100).cumprod()],ignore_index=True)
    dd=wealth/wealth.cummax()-1;trough=int(dd.idxmin());peak=int(wealth.iloc[:trough+1].idxmax())
    affected=detail.iloc[peak:trough].copy()
    affected['asset']=np.where(affected.invested,'stock',affected['방어자산'].fillna('cash'))
    contributions={}
    for asset,g in affected.groupby('asset'):
        contributions[asset]={'months':len(g),'compound_pct':float(((1+g[ENS]/100).prod()-1)*100),'log_contribution':float(np.log1p(g[ENS]/100).sum())}
    assert abs(sum(x['log_contribution'] for x in contributions.values())-np.log(wealth.iloc[trough]/wealth.iloc[peak]))<1e-10
    report={'fixed_candidates':list(returns.columns[1:]),'max_drawdown_peak':baseline['투자월'].iloc[peak-1] if peak else '2009-12','max_drawdown_trough':baseline['투자월'].iloc[trough-1],'drawdown_contributions':contributions,'variants':{}}
    for col in returns.columns[1:]:
        v={'full':stats(returns[col]),'segments':{}}
        for start,end in [('2010-01','2013-12'),('2014-01','2019-12'),('2020-01','2026-10'),('2014-01','2026-10')]:
            mask=returns['투자월'].between(start,end)
            v['segments'][start+'~'+end]=stats(returns.loc[mask,col])
        v['years']={year:stats(g[col]) for year,g in returns.groupby(returns['투자월'].str[:4])}
        report['variants'][col]=v
    report['exposure']={'vol_target15_mean':float(risk_weight.mean()),'vol_target15_min':float(risk_weight.min()),'extension_months':int(extension.sum())}
    # 사전고정 후보9개를 본 뒤 추가한 해석용 참고값. 평균노출비중은 사후 계산값이며
    # 새 운용규칙으로 추천하거나 미사용 검증으로 취급하지 않는다.
    refs={'portfolio50_cash50':.5,'constant_mean_vol_exposure_posthoc':float(risk_weight.mean())}
    reference_returns=pd.DataFrame({'투자월':baseline['투자월']})
    report['posthoc_references']={}
    for name,weight in refs.items():
        reference_returns[name]=baseline[ENS]*weight
        report['posthoc_references'][name]={'weight':weight,**stats(reference_returns[name])}
    report['input_sha256']={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in ['reconstructed_stocks.csv','source_kospi_complete.csv','gold_monthly.csv','monthly_returns.csv']}
    report['limitations']=['같은 과거구간을 본 뒤 제안한 탐색으로 표본외 검증 아님','초기 금프록시·기업행동/상폐정산 미검증 한계 동일','월별비중은 엔진의 순수익/내재비용에 비례 적용, 현금이자0, 정밀 체결비용 미반영','고정비중·변동성목표가 미래MDD 상한을 보장하지 않음','후보 조합이나 격자 최적화 없음; 라이브 수정 없음']
    args.output.mkdir(parents=True)
    returns.to_csv(args.output/'monthly_comparison.csv',index=False,encoding='utf-8-sig')
    exposure.to_csv(args.output/'exposure.csv',index=False,encoding='utf-8-sig')
    reference_returns.to_csv(args.output/'posthoc_reference_returns.csv',index=False,encoding='utf-8-sig')
    affected.to_csv(args.output/'drawdown_interval.csv',index=False,encoding='utf-8-sig')
    annual=(1+returns.drop(columns='투자월')/100).groupby(returns['투자월'].str[:4]).prod().sub(1).mul(100)
    annual.to_csv(args.output/'annual_comparison.csv',encoding='utf-8-sig')
    for label,(r,t,d) in outputs.items():
        r.to_csv(args.output/f'{label}_monthly.csv',index=False,encoding='utf-8-sig')
        t.to_csv(args.output/f'{label}_trades.csv',index=False,encoding='utf-8-sig')
        d.to_csv(args.output/f'{label}_details.csv',index=False,encoding='utf-8-sig')
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for label,v in report['variants'].items():
        rows.append({'variant':label,**v['full'],'early_cagr':v['segments']['2010-01~2013-12']['cagr_pct'],'post2014_cagr':v['segments']['2014-01~2026-10']['cagr_pct'],'post2014_mdd':v['segments']['2014-01~2026-10']['monthly_mdd_pct'],'2011_return':float(annual.loc['2011',label])})
    table=pd.DataFrame(rows);table.to_csv(args.output/'comparison.csv',index=False,encoding='utf-8-sig')
    print(table.round(4).to_string(index=False),flush=True)
    print(json.dumps({'drawdown':contributions,'exposure':report['exposure'],'posthoc_references':report['posthoc_references']},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
