"""연구용 종목별 월별 조정가격 수집. 운영 data 파일을 수정하지 않는다."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time

import pandas as pd


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--workers', type=int, default=6)
    p.add_argument('--retry-rate-limited', action='store_true')
    a = p.parse_args()
    root, out = Path(a.snapshot), Path(a.output)
    prices = out / 'monthly_prices'
    prices.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted((root / 'archive_usa').glob('only_*.csv')):
        d = pd.read_csv(f)
        if '종목코드' in d:
            rows.extend(d['종목코드'].dropna().astype(str))
    tickers = sorted(set(rows))
    import yfinance as yf
    # Ticker.history는 개별 인스턴스별 파서를 쓴다. 공유 결과 dict가 있는
    # yf.download를 여러 스레드에서 중첩 호출하지 않는다.
    def fetch(t):
        file = prices / f'{t}.csv'
        if file.exists():
            return dict(ticker=t, status='cached', rows=len(pd.read_csv(file)))
        symbol = t.replace('.', '-')
        for attempt in range(2):
            try:
                d = yf.Ticker(symbol).history(start='1995-01-01', end='2026-11-01',
                                              interval='1mo', auto_adjust=False,
                                              actions=True, timeout=15)
                if d.empty:
                    return dict(ticker=t, yahoo_symbol=symbol, status='empty', rows=0)
                wanted = [c for c in ['Close', 'Adj Close', 'Dividends', 'Stock Splits'] if c in d]
                d = d[wanted].copy()
                d.index = d.index.tz_localize(None) if d.index.tz is not None else d.index
                d.index.name = 'date'
                d.to_csv(file, encoding='utf-8')
                return dict(ticker=t, yahoo_symbol=symbol, status='ok', rows=len(d),
                            first=str(d.index.min().date()), last=str(d.index.max().date()),
                            sha256=hashlib.sha256(file.read_bytes()).hexdigest())
            except Exception as e:
                if type(e).__name__ == 'YFRateLimitError':
                    return dict(ticker=t, yahoo_symbol=symbol, status=type(e).__name__, rows=0)
                if attempt == 1:
                    return dict(ticker=t, yahoo_symbol=symbol, status=type(e).__name__, rows=0)
                time.sleep(.5)
    if a.retry_rate_limited:
        previous = pd.read_csv(out/'download_status.csv').to_dict(orient='records')
        by_ticker = {r['ticker']:r for r in previous}
        retry = [r['ticker'] for r in previous if r['status']=='YFRateLimitError']
        completed=0
        for t in retry:
            result=fetch(t)
            by_ticker[t]=result
            if result['status']=='YFRateLimitError':
                print('rate limit still active; stopped retry batch',flush=True)
                break
            completed+=1
            if completed%25==0:
                print(f'retry completed={completed}/{len(retry)}',flush=True)
                pd.DataFrame(by_ticker.values()).sort_values('ticker').to_csv(out/'download_status.csv',index=False)
            time.sleep(1)
        pd.DataFrame(by_ticker.values()).sort_values('ticker').to_csv(out/'download_status.csv',index=False)
        print('retry batch processed',completed,flush=True)
        return
    status = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for future in as_completed([ex.submit(fetch, t) for t in tickers]):
            status.append(future.result())
            if len(status) % 50 == 0:
                pd.DataFrame(status).to_csv(out / 'download_status.csv', index=False)
                good = sum(x['rows'] > 0 for x in status)
                print(f'completed={len(status)}/{len(tickers)} available={good}', flush=True)
    pd.DataFrame(status).sort_values('ticker').to_csv(out / 'download_status.csv', index=False)
    print(json.dumps({'tickers':len(tickers), 'available':sum(x['rows'] > 0 for x in status)}, indent=2))


if __name__ == '__main__':
    main()
