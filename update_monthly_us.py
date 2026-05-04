import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime
import os
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
    except:
        return 0.0

def process_monthly_ticker_us(row, start_date, base_date, dates, invest_year, invest_month_str, base_date_str):
    code = row['Code']
    name = row['Name']
    market = row['시장'] 
    marcap = row['Marcap']
    
    try:
        df_hist = fdr.DataReader(code, start_date, base_date)
        if df_hist.empty: return None
        
        if df_hist.index.tz is not None: df_hist.index = df_hist.index.tz_localize(None)
        
        base_price = df_hist['Close'].iloc[-1]
        curr_vol = df_hist['Volume'].iloc[-1] if 'Volume' in df_hist.columns else 0
        shares = marcap / row['Close'] if row.get('Close', 0) > 0 else 0
        calc_marcap = int(base_price * shares)
        
        record = {
            '투자연도': invest_year,
            '투자월': invest_month_str,
            '종목선정일': base_date_str,
            '종목코드': code,
            '종목명': name,
            '시장': market,
            '1개월(%)': calculate_past_return(df_hist, dates['1개월'], base_price),
            '3개월(%)': calculate_past_return(df_hist, dates['3개월'], base_price),
            '6개월(%)': calculate_past_return(df_hist, dates['6개월'], base_price),
            '12개월(%)': calculate_past_return(df_hist, dates['12개월'], base_price),
            '시가총액': calc_marcap,
            '종가': base_price,
            '거래량': curr_vol,
            '이번달수익률': 0.0
        }
        return code, record
    except:
        return None

def generate_monthly_archive_us():
    print("🚀 [미국 전용] 월간 아카이브 (시장 정보 포함) 생성 시작...")
    
    today = datetime.today()
    invest_year = today.year
    invest_month_str = today.strftime('%Y_%m')
    
    # 💡 [핵심] 미국 ETF(SPY)를 기준으로 지난달 마지막 영업일 탐색
    first_day_of_current = today.replace(day=1)
    last_day_prev = first_day_of_current - pd.Timedelta(days=1)
    df_idx = fdr.DataReader('SPY', last_day_prev - pd.Timedelta(days=10), last_day_prev)
    base_date = df_idx.index[-1]
    base_date_str = base_date.strftime('%Y-%m-%d')
    
    print(f"✅ 🇺🇸 신규 투자월: {invest_month_str.replace('_', '-')} (미국 기준 선정일: {base_date_str})")

    dates = {'1개월': get_end_of_month(base_date, 1), '3개월': get_end_of_month(base_date, 3), '6개월': get_end_of_month(base_date, 6), '12개월': get_end_of_month(base_date, 12)}
    start_date = dates['12개월'] - pd.Timedelta(days=15)

    print("🔄 미국 거래소(NYSE/NASDAQ) 종목 마스터 데이터 매핑 중...")
    try:
        us_ny = fdr.StockListing('NYSE')[['Symbol', 'Name']]
        us_ny['시장'] = 'NYSE'
        us_nq = fdr.StockListing('NASDAQ')[['Symbol', 'Name']]
        us_nq['시장'] = 'NASDAQ'
        us_master = pd.concat([us_ny, us_nq])
        us_master['Symbol'] = us_master['Symbol'].str.replace('.', '-', regex=False)
        us_market_map = dict(zip(us_master['Symbol'], us_master['시장']))
        us_name_map = dict(zip(us_master['Symbol'], us_master['Name']))
    except:
        us_market_map, us_name_map = {}, {}

    try:
        df_sp500 = fdr.StockListing('S&P500')
        df_sp500['Code'] = df_sp500['Symbol'].str.replace('.', '-', regex=False)
        df_sp500['시장'] = df_sp500['Code'].map(us_market_map).fillna('US')
        df_sp500['Name'] = df_sp500['Code'].map(us_name_map).fillna(df_sp500['Symbol'])
        df_sp500['Marcap'] = 0
    except:
        df_sp500 = pd.DataFrame()
        print("⚠️ S&P 500 목록 로드 실패")
        return

    all_target_df = df_sp500[['Code', 'Name', '시장', 'Marcap']].drop_duplicates(subset=['Code']).copy()

    print(f"📊 총 {len(all_target_df)}개 미국 종목 모멘텀 계산 중...")
    monthly_records_dict = {}

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker_us, row, start_date, base_date, dates, invest_year, invest_month_str.replace('_', '-'), base_date_str) for _, row in all_target_df.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res:
                code, record = res
                monthly_records_dict[code] = record

    os.makedirs('archive_sp500', exist_ok=True)
    
    if not df_sp500.empty:
        recs_s = [monthly_records_dict[c] for c in df_sp500['Code'] if c in monthly_records_dict]
        pd.DataFrame(recs_s).to_csv(f'archive_sp500/only_sp500_{invest_month_str}.csv', index=False, encoding='utf-8-sig')
        
    print(f"🎉 🇺🇸 {invest_month_str.replace('_', '-')} 미국 아카이브 생성 완료!")

if __name__ == "__main__":
    generate_monthly_archive_us()
