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

# ----------------- [전략 1] USA 300 유니버스 추출 -----------------
def get_top_us_stocks(market, limit=150):
    try:
        df = fdr.StockListing(market)
        if df.empty: return pd.DataFrame()
        cap_col = [c for c in df.columns if '시가총액' in c or ('mar' in c.lower() and 'cap' in c.lower())]
        if not cap_col: return pd.DataFrame()
        
        df['시가총액_raw'] = pd.to_numeric(df[cap_col[0]].astype(str).str.replace(',', '').str.replace('.0', '', regex=False), errors='coerce')
        df = df.dropna(subset=['시가총액_raw']).sort_values('시가총액_raw', ascending=False).head(limit)
        
        code_col = 'Code' if 'Code' in df.columns else 'Symbol'
        name_col = 'Name' if 'Name' in df.columns else 'Company'
        df = df.rename(columns={code_col: '종목코드', name_col: '종목명'})
        df['시장'] = market
        df['종목코드'] = df['종목코드'].astype(str).str.replace('.', '-', regex=False)
        return df[['종목코드', '종목명', '시장', '시가총액_raw']]
    except: return pd.DataFrame()

def generate_usa300(base_date, dates, start_date, base_date_str, invest_year, invest_month_str, invest_month_dash):
    print("\n📌 [USA 300] 유니버스 추출 시작...")
    universe = pd.concat([get_top_us_stocks('NASDAQ', 150), get_top_us_stocks('NYSE', 150)]).drop_duplicates(subset=['종목코드'])
    if universe.empty: return
    
    os.makedirs('archive_usa', exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker, row, start_date, base_date, dates, base_date_str, invest_year, invest_month_dash) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)
            
    if results:
        # 💡 [한국 방식 동일] 파일명을 '현재 월'(invest_month_str) 기준으로 저장 → 6월엔 only_usa300_2026_06.csv 생성
        output_file = f"archive_usa/only_usa300_{invest_month_str}.csv"
        pd.DataFrame(results).to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ [USA 300] 월간 데이터 저장 완료: {output_file}")

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
        # 💡 [한국 방식 동일] S&P500의 파일명 규칙(only_momentum_YYYY_MM.csv)도 '현재 월' 기준으로 저장
        output_file = f"archive_sp500/only_momentum_{invest_month_str}.csv"
        pd.DataFrame(results).to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ [S&P 500] 월간 데이터 저장 완료: {output_file}")

def get_us_last_trading_day(today):
    """🇺🇸 S&P500 지수(US500)를 기준으로 지난달 '실제 마지막 거래일'을 찾는다.
    한국이 KS11로 실거래일을 찾는 것과 동일한 방식. 실패 시 달력상 말일로 폴백."""
    fallback = get_end_of_month(today, 1)
    try:
        first_day_of_current = today.replace(day=1)
        last_day_prev = first_day_of_current - pd.Timedelta(days=1)
        df_idx = fdr.DataReader('US500', last_day_prev - pd.Timedelta(days=10), last_day_prev)
        if df_idx.empty:
            return fallback
        base_date = df_idx.index[-1]
        if base_date.tz is not None:
            base_date = base_date.tz_localize(None)
        return base_date
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
    generate_usa300(base_date, dates, start_date, base_date_str, invest_year, invest_month_str, invest_month_dash)
    print(f"\n🎉 🇺🇸 {invest_month_dash} 미국 월간 업데이트가 완료되었습니다!")

if __name__ == "__main__":
    main()
