"""2010-01~2014-01 확장 후보를 라이브 엔진으로 검토한다(라이브 반영 없음)."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from utils import calculator as engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    prices = {}
    for ticker, label in [('GC=F', 'gold_futures'), ('KRW=X', 'usdkrw'), ('^KS11', 'kospi')]:
        data = yf.Ticker(ticker).history(start='2008-01-01', end='2014-04-01', auto_adjust=False)
        if data.empty:
            raise RuntimeError(f'빈 가격 응답: {ticker}')
        data.index = data.index.tz_localize(None).normalize()
        data.to_csv(output / f'source_{label}.csv', encoding='utf-8-sig')
        prices[label] = data['Close']
    # 미국 금 종가는 한국 장 마감 후 확정된다. 하루 뒤에 관측 가능하게 정렬한다.
    # 원달러에도 같은 보수적인 관측 지연을 적용한다.
    proxy = pd.concat([prices['gold_futures'], prices['usdkrw']], axis=1, keys=['gold', 'fx'], sort=True).sort_index().ffill().dropna()
    proxy.index = proxy.index + pd.Timedelta(days=1)
    daily = proxy.gold * proxy.fx / 31.1035
    # 한국의 마지막 거래일이 달력 월말보다 빠른 달에도 선정일 이후 시세를 쓰지 않는다.
    calendar = prices['kospi'].index
    daily = daily.reindex(daily.index.union(calendar)).sort_index().ffill().reindex(calendar).dropna()
    monthly = daily.groupby(daily.index.to_period('M')).last().to_frame('price')
    monthly.index = monthly.index.astype(str)
    monthly['ret'] = monthly.price.pct_change() * 100
    monthly.to_csv(output / 'gold_proxy_monthly.csv', encoding='utf-8-sig')
    archive = pd.concat([pd.read_csv(p, dtype={'종목코드': str}) for p in sorted((output / 'candidate_archive').glob('*.csv'))], ignore_index=True)
    # 라이브 페이지와 동일한 결측 모멘텀 처리.
    cols = ['1개월(%)','3개월(%)','6개월(%)','12개월(%)','이번달수익률']
    archive[cols] = archive[cols].fillna(0)
    with patch.object(engine, '_load_kospi_index', return_value=prices['kospi'].to_frame('Close')), patch.object(engine, 'get_gold_krw_monthly', return_value=monthly):
        results, trades, details = engine.run_backtest_k200(
            archive, 2010, 2014, 6, True, (1,6), (1,2), 30, 30,
            trading_cost_pct=.25, gold_returns=monthly.ret.to_dict(),
            use_gold=True, use_gold_ma=True, gold_ma_months=6)
    assert len(results) == 49 and results['투자월'].tolist() == list(pd.period_range('2010-01','2014-01',freq='M').astype(str))
    results.to_csv(output / 'research_monthly_returns.csv', index=False, encoding='utf-8-sig')
    trades.to_csv(output / 'research_trades.csv', index=False, encoding='utf-8-sig')
    details.to_csv(output / 'research_details.csv', index=False, encoding='utf-8-sig')
    stats = {}
    for name in results.columns:
        if name in ['투자월', 'invested', '중지 사유']:
            continue
        wealth = pd.concat([pd.Series([1.]), (1+results[name]/100).cumprod()], ignore_index=True)
        stats[name] = {'cagr_pct': float((wealth.iloc[-1]**(12/49)-1)*100), 'mdd_pct':float((wealth/wealth.cummax()-1).min()*100)}
    report = {'months':49, 'start':'2010-01','end':'2014-01','stats':stats,
              'status':'research_only', 'gold_proxy':'GC=F x KRW=X / 31.1035; both delayed one calendar day; sampled on KOSPI trading dates',
              'stock_months':int(results.invested.sum()),
              'limitations':['해당 시점 실제 KRX 금현물 거래 재현 아님', '기업행동 기준가격 보정; 배당·인적분할 수령주식·상폐 정산 검증 미완', '현재 아카이브와 완전 동일한 수익률 원천 아님; 2014-02 한미약품 4.56%p 차이', '표본외 검증 아님; 실전 기대수익률로 사용하지 않음']}
    (output / 'backtest_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
