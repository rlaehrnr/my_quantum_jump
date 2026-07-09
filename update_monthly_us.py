import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_end_of_month(dt, months_ago):
    first_of_current = dt.replace(day=1)
    target_month = first_of_current - pd.DateOffset(months=months_ago - 1)
    return target_month - pd.Timedelta(days=1)

def calculate_past_return(df_hist, target_date, base_price):
    try:
        past_df = df_hist[df_hist.index <= pd.to_datetime(target_date)]
        if past_df.empty or base_price <= 0: return 0.0
        base_val = past_df['Close'].iloc[-1]
        return round(((base_price / base_val) - 1) * 100, 2)
    except: return 0.0

def process_monthly_ticker(row, start_date, base_date, dates, base_date_str, invest_year, invest_month_dash):
    code, name, market = str(row['종목코드']).strip(), row['종목명'], row['시장']
    marcap = row.get('시가총액_raw', row.get('시가총액', 0))
    try:
        df_hist = fdr.DataReader(code, start_date, base_date)
        if df_hist.empty: return None
        if df_hist.index.tz is not None: df_hist.index = df_hist.index.tz_localize(None)
        base_price = df_hist['Close'].iloc[-1]
        
        return {
            # 💡 [한국 방식 동일] 투자연도/투자월을 파일에 직접 기록 → 로더가 파일명에 의존하지 않음
            '투자연도': invest_year,
            '투자월': invest_month_dash,
            '종목선정일': base_date_str, '시장': market, '종목명': name, '종목코드': code, 
            '시가총액': marcap, '종가': base_price,
            '1개월(%)': calculate_past_return(df_hist, dates[1], base_price),
            '3개월(%)': calculate_past_return(df_hist, dates[3], base_price),
            '6개월(%)': calculate_past_return(df_hist, dates[6], base_price),
            '12개월(%)': calculate_past_return(df_hist, dates[12], base_price),
            '이번달수익률': 0.0
        }
    except: return None

# ----------------- [전략 1] USA 500 유니버스 추출 (Nasdaq 스크리너, 시총·거래소·ADR 포함) -----------------
import requests

_NASDAQ_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://www.nasdaq.com',
    'Referer': 'https://www.nasdaq.com/',
}

def fetch_screener_exchange(exchange):
    """
    Nasdaq 공식 스크리너에서 거래소별 전체 종목(시가총액 포함) 로드.
    exchange: 'NASDAQ' | 'NYSE' | 'AMEX'
    반환 컬럼: 종목코드, 종목명, 시장, 시가총액_raw(=시가총액, 백만달러 단위)
    """
    url = ("https://api.nasdaq.com/api/screener/stocks"
           f"?tableonly=true&limit=10000&download=true&exchange={exchange}")
    try:
        r = requests.get(url, headers=_NASDAQ_HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json().get('data') or {}
        rows = data.get('rows')
        if rows is None:
            rows = (data.get('table') or {}).get('rows')
        if not rows:
            print(f"⚠️ [{exchange}] 스크리너 응답에 rows 없음")
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        if 'symbol' not in df.columns or 'marketCap' not in df.columns:
            print(f"⚠️ [{exchange}] 예상 컬럼 없음: {list(df.columns)[:8]}")
            return pd.DataFrame()

        # 시가총액: '$1,234,567,890' / '1234567890' / '' → 숫자(달러) → 백만달러 단위
        cap_usd = pd.to_numeric(
            df['marketCap'].astype(str).str.replace(r'[\$,]', '', regex=True).str.strip().replace('', '0'),
            errors='coerce').fillna(0)
        out = pd.DataFrame({
            '종목코드': (df['symbol'].astype(str).str.strip()
                          .str.replace('/', '-', regex=False)
                          .str.replace('.', '-', regex=False)),
            '종목명': df.get('name', df['symbol']).astype(str).str.strip(),
            '시장': exchange,
            '시가총액_raw': (cap_usd / 1_000_000.0).round(1),   # 백만달러 (기존 파일과 동일 스케일)
        })
        # 이상치 제거: 빈 티커 / 지나치게 긴 티커(워런트·유닛 등) / 시총 0
        out = out[out['종목코드'].str.fullmatch(r'[A-Z][A-Z0-9\-]{0,6}', na=False)]
        return out
    except Exception as e:
        print(f"🚨 [{exchange}] 스크리너 실패: {e}")
        return pd.DataFrame()

def _company_key(name):
    """복수 클래스(GOOGL/GOOG, BRK-A/BRK-B 등)를 한 회사로 묶기 위한 정규화 키."""
    n = str(name)
    for sep in [' Class ', ' Depositary Shares', ' Depository Shares',
                ' Common Stock', ' Capital Stock', ' Ordinary Shares',
                ' American Depositary', ' Sponsored ADR', ' ADR',
                ' Registered', ' New York Registry', ' Subordinate Voting',
                ' Preferred', ' Units', ' Warrant']:
        i = n.find(sep)
        if i != -1:
            n = n[:i]
    return n.strip().rstrip('.,').lower()

def _drop_dupes_and_junk(all_us):
    """
    비보통주(채권/워런트/예탁증서 조각 등) 제외 + 회사당 1개(시총 최대 클래스)만 남김.
    반환: 정제된 DataFrame(시총 내림차순). head(N)은 호출측에서.
    """
    name_lc = all_us['종목명'].astype(str).str.lower()
    junk = (
        name_lc.str.contains(r'\bnotes?\b', regex=True, na=False)          # 채권(Notes/Note)
        | name_lc.str.contains('debenture', na=False)
        | name_lc.str.contains('warrant', na=False)
        | name_lc.str.contains('depositary shares representing', na=False)  # GOOGM/GOOGN 류
        | name_lc.str.contains(r'\d\.\d+\s*%', regex=True, na=False)        # '5.350%' 쿠폰(채권·우선주)
    )
    kept = all_us[~junk].sort_values('시가총액_raw', ascending=False)
    kept = kept.drop_duplicates(subset=['종목코드'], keep='first')
    kept['_company'] = kept['종목명'].map(_company_key)
    kept = kept.drop_duplicates(subset=['_company'], keep='first')          # 회사당 최고 시총 1개
    return kept.drop(columns=['_company']), int(junk.sum())

def generate_usa500(base_date, dates, start_date, base_date_str, invest_year, invest_month_str, invest_month_dash, top_n=500):
    print(f"\n📌 [USA 500] 유니버스 추출 시작 (Nasdaq 스크리너, NASDAQ+NYSE 통합 시총 상위 {top_n})...")
    parts = [p for p in [fetch_screener_exchange('NASDAQ'), fetch_screener_exchange('NYSE')] if not p.empty]
    if not parts:
        print("🚨 [USA 500] 유니버스 소스를 불러오지 못해 생성을 건너뜁니다(기존 파일 유지).")
        return

    all_us = pd.concat(parts, ignore_index=True)
    all_us = all_us[all_us['시가총액_raw'] > 0]

    # 🧹 비보통주 제외 + 회사당 1클래스(시총 최대)만 → 그러고도 top_n 채우도록 head는 마지막에
    cleaned, n_junk = _drop_dupes_and_junk(all_us)
    universe = cleaned.head(top_n).reset_index(drop=True)
    if universe.empty:
        print("🚨 [USA 500] 유효 시총 종목이 없어 건너뜁니다.")
        return

    n_nas = int((universe['시장'] == 'NASDAQ').sum()); n_nys = int((universe['시장'] == 'NYSE').sum())
    print(f"   └ 정제 후 후보 {len(cleaned)}종목(비보통주 {n_junk}개 제외·복수클래스 통합) → 상위 {len(universe)} 선정")
    print(f"   └ 유니버스 {len(universe)}종목 (NASDAQ {n_nas} / NYSE {n_nys})")
    print(f"   └ 시총 1~5위: {universe['종목명'].head(5).tolist()}")
    print(f"   └ TSM 포함? {'예' if (universe['종목코드']=='TSM').any() else '아니오'} / 중복확인 GOOG {(universe['종목코드']=='GOOG').any()} GOOGM {(universe['종목코드']=='GOOGM').any()}")

    os.makedirs('archive_usa', exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker, row, start_date, base_date, dates, base_date_str, invest_year, invest_month_dash) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)

    if results:
        out = pd.DataFrame(results).sort_values('시가총액', ascending=False).reset_index(drop=True)
        out.insert(0, '순위', range(1, len(out) + 1))   # 시총 순위(월별·데일리 전체순위와 동일 기준)
        output_file = f"archive_usa/only_usa500_{invest_month_str}.csv"
        out.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ [USA 500] 월간 데이터 ({len(out)}종목) 저장 완료: {output_file}")

# ----------------- [전략 2] S&P 500 유니버스 추출 -----------------
def generate_sp500(base_date, dates, start_date, base_date_str, invest_year, invest_month_str, invest_month_dash):
    print("\n📌 [S&P 500] 유니버스 추출 시작...")
    try:
        df_sp500 = fdr.StockListing('S&P500')
        df_sp500 = df_sp500.rename(columns={'Symbol': '종목코드', 'Name': '종목명'})
        df_sp500['시장'] = 'US'
        df_sp500['시가총액_raw'] = 0
        df_sp500['종목코드'] = df_sp500['종목코드'].astype(str).str.replace('.', '-', regex=False)
        universe = df_sp500[['종목코드', '종목명', '시장', '시가총액_raw']].drop_duplicates(subset=['종목코드'])
    except: return

    os.makedirs('archive_sp500', exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker, row, start_date, base_date, dates, base_date_str, invest_year, invest_month_dash) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)
            
    if results:
        # 💡 [한국 방식 동일] S&P500의 파일명 규칙(only_sp500_YYYY_MM.csv)도 '현재 월' 기준으로 저장
        output_file = f"archive_sp500/only_sp500_{invest_month_str}.csv"
        pd.DataFrame(results).to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ [S&P 500] 월간 데이터 저장 완료: {output_file}")

def get_us_last_trading_day(today):
    """🇺🇸 지난달 '실제 마지막 거래일'을 찾는다.
    💡 데일리(update_daily_us.py)와 '동일한 소스'인 SPY(ETF) + 거래량 필터를 사용한다.
    지수 US500은 FDR 소스 갱신이 하루 늦게 반영될 때가 있어(선정일이 6/30이 아닌 6/29로 밀리는 원인),
    같은 시각에 도는 데일리(SPY)와 결과가 어긋난다. SPY로 통일해 이 지연을 제거한다.
    실패 시 달력상 말일로 폴백."""
    fallback = get_end_of_month(today, 1)  # 지난달 달력상 말일
    try:
        first_day_of_current = today.replace(day=1)
        last_day_prev = first_day_of_current - pd.Timedelta(days=1)  # 지난달 말일(달력 기준)
        # 종료일을 지정하지 않고 최신 거래일까지 받아온 뒤, 아래에서 '지난달 범위'로 자른다
        df = fdr.DataReader('SPY', last_day_prev - pd.Timedelta(days=15))
        if df.empty:
            return fallback
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        # 거래량이 실제로 찍힌 날만 남긴다(빈/부분 행 방지) — 데일리와 동일한 방어 로직
        if 'Volume' in df.columns:
            df = df[df['Volume'] > 1000]
        # 💡 실행이 늦어 이번 달 거래일이 섞여 들어와도 '지난달 말일 이하'로만 제한 (월 경계 안전장치)
        df = df[df.index <= pd.to_datetime(last_day_prev)]
        if df.empty:
            return fallback
        return df.index[-1]
    except:
        return fallback

def main():
    today = datetime.today()

    # 💡 [한국 방식 동일] 파일명/투자월은 '현재 월(이번 달)' 기준
    invest_year = today.year
    invest_month_str = today.strftime('%Y_%m')    # 파일명용 (예: 2026_06)
    invest_month_dash = today.strftime('%Y-%m')   # 투자월 컬럼용 (예: 2026-06)

    # 종목선정일(base_date)은 '지난달 마지막 실제 거래일'
    base_date = get_us_last_trading_day(today)
    base_date_str = base_date.strftime('%Y-%m-%d')

    dates = {1: get_end_of_month(base_date, 1), 3: get_end_of_month(base_date, 3), 6: get_end_of_month(base_date, 6), 12: get_end_of_month(base_date, 12)}
    start_date = get_end_of_month(base_date, 13)
    
    print(f"🚀 🇺🇸 월간 통합 업데이트 시작 (신규 투자월: {invest_month_dash}, 미국 기준 선정일: {base_date_str})")
    generate_sp500(base_date, dates, start_date, base_date_str, invest_year, invest_month_str, invest_month_dash)
    generate_usa500(base_date, dates, start_date, base_date_str, invest_year, invest_month_str, invest_month_dash, top_n=500)
    print(f"\n🎉 🇺🇸 {invest_month_dash} 미국 월간 업데이트가 완료되었습니다!")

if __name__ == "__main__":
    main()
