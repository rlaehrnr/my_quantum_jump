import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_last_business_day_us():
    try:
        df = fdr.DataReader('SPY', datetime.today() - timedelta(days=14))
        valid_days = df[df['Volume'] > 1000] 
        if not valid_days.empty: return valid_days.index[-1].strftime('%Y-%m-%d')
    except: pass
    return datetime.today().strftime('%Y-%m-%d')

def get_end_of_month(dt, months_ago):
    first_of_current = dt.replace(day=1)
    target_month = first_of_current - pd.DateOffset(months=months_ago - 1)
    return target_month - timedelta(days=1)

def calculate_return_unified(df_hist, target_date, current_price):
    try:
        past_df = df_hist[df_hist.index <= pd.to_datetime(target_date)]
        if past_df.empty: return 0.0
        base_price = past_df['Close'].iloc[-1]
        if base_price <= 0: return 0.0
        return round(((current_price / base_price) - 1) * 100, 2)
    except: return 0.0

def process_daily_ticker(row, start_date, today, dates, real_base_date_str):
    code, name, market = str(row['종목코드']).strip(), row['종목명'], row['시장']
    marcap = row.get('시가총액_raw', row.get('시가총액', 0))
    try:
        df_hist = fdr.DataReader(code, start_date, today)
        if df_hist.empty: return None
        if df_hist.index.tz is not None: df_hist.index = df_hist.index.tz_localize(None)
        curr_p = df_hist['Close'].iloc[-1]
        
        return {
            '기준일': real_base_date_str, '시장': market, '종목명': name, '종목코드': code, 
            '시가총액': marcap, '종가': curr_p,
            '1개월(%)': calculate_return_unified(df_hist, dates[1], curr_p),
            '3개월(%)': calculate_return_unified(df_hist, dates[3], curr_p),
            '6개월(%)': calculate_return_unified(df_hist, dates[6], curr_p),
            '12개월(%)': calculate_return_unified(df_hist, dates[12], curr_p)
        }
    except: return None

def run_daily_update(target_name, archive_folder, output_file, real_base_date_str, real_base_date, today, dates, start_date):
    print(f"\\n📌 [{target_name}] 데일리 업데이트 시작...")
    archive_files = sorted(glob.glob(f'{archive_folder}/only_*.csv'))
    if not archive_files:
        print(f"🚨 {archive_folder}에 데이터가 없습니다.")
        return
        
    latest_file = archive_files[-1]
    
    # 컬럼 매핑 호환성 (과거 SP500 파일 대응)
    df_latest = pd.read_csv(latest_file)
    if 'Date' in df_latest.columns and '종목선정일' not in df_latest.columns:
        df_latest = df_latest.rename(columns={'Date': '종목선정일', 'Ticker': '종목코드'})
    if 'Name' in df_latest.columns and '종목명' not in df_latest.columns:
        df_latest = df_latest.rename(columns={'Name': '종목명'})
    if '시장' not in df_latest.columns: df_latest['시장'] = 'US'
        
    universe = df_latest[['종목코드', '종목명', '시장']].drop_duplicates(subset=['종목코드'])
    if '시가총액_raw' in df_latest.columns: universe['시가총액_raw'] = df_latest['시가총액_raw']
    elif '시가총액' in df_latest.columns: universe['시가총액_raw'] = df_latest['시가총액']

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_daily_ticker, row, start_date, today, dates, real_base_date_str) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)
            
    if results:
        pd.DataFrame(results).to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ [{target_name}] 데일리 저장 완료: {output_file}")
        
        # 월간 파일 이번달수익률 최신화
        if '종목선정일' in df_latest.columns:
            csv_base_date = pd.to_datetime(df_latest['종목선정일'].iloc[0])
            updates = 0
            for idx, row in df_latest.iterrows():
                try:
                    df_h = fdr.DataReader(str(row['종목코드']), csv_base_date, today)
                    if not df_h.empty and df_h['Close'].iloc[0] > 0:
                        df_latest.at[idx, '이번달수익률'] = round(((df_h['Close'].iloc[-1] / df_h['Close'].iloc[0]) - 1) * 100, 2)
                        updates += 1
                except: pass
            if updates > 0:
                df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
                print(f"✅ [{target_name}] 월간 아카이브 동기화 완료!")

def main():
    os.makedirs('data', exist_ok=True)
    today = datetime.today()
    real_base_date_str = get_last_business_day_us()
    real_base_date = pd.to_datetime(real_base_date_str)
    
    dates = {1: get_end_of_month(real_base_date, 1), 3: get_end_of_month(real_base_date, 3), 6: get_end_of_month(real_base_date, 6), 12: get_end_of_month(real_base_date, 12)}
    start_date = get_end_of_month(real_base_date, 13)

    print(f"🚀 일간 통합 업데이트 시작 (기준일: {real_base_date_str})")
    
    # 1. SP500 업데이트
    run_daily_update('S&P 500', 'archive_sp500', 'data/momentum_data_daily_sp500.csv', real_base_date_str, real_base_date, today, dates, start_date)
    
    # 2. USA300 업데이트
    run_daily_update('USA 300', 'archive_usa', 'data/momentum_data_daily_usa300.csv', real_base_date_str, real_base_date, today, dates, start_date)
    
    print("\\n🎉 모든 일간 업데이트가 완료되었습니다!")

if __name__ == "__main__":
    main()
