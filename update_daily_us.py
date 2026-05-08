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
        if not valid_days.empty:
            return valid_days.index[-1].strftime('%Y-%m-%d')
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

def process_ticker_us(row, start_date, today, dates, real_base_date_str):
    code = str(row['종목코드']).strip()
    name = row['종목명']
    market = row['시장']
    marcap = row['시가총액_raw'] if '시가총액_raw' in row else row.get('시가총액', 0)
    
    try:
        df_hist = fdr.DataReader(code, start_date, today)
        if df_hist.empty: return None
        
        if df_hist.index.tz is not None: df_hist.index = df_hist.index.tz_localize(None)
        
        curr_p = df_hist['Close'].iloc[-1]
        
        ret_1m = calculate_return_unified(df_hist, dates[1], curr_p)
        ret_3m = calculate_return_unified(df_hist, dates[3], curr_p)
        ret_6m = calculate_return_unified(df_hist, dates[6], curr_p)
        ret_12m = calculate_return_unified(df_hist, dates[12], curr_p)
        
        return {
            '기준일': real_base_date_str,
            '시장': market,
            '종목명': name,
            '종목코드': code,
            '시가총액': marcap,
            '종가': curr_p,
            '1개월(%)': ret_1m,
            '3개월(%)': ret_3m,
            '6개월(%)': ret_6m,
            '12개월(%)': ret_12m,
        }
    except: return None

def sync_archive_returns_us(archive_folder):
    archive_files = sorted(glob.glob(f'{archive_folder}/usa300_*.csv'))
    if not archive_files: return
    latest_file = archive_files[-1]
    
    df_latest = pd.read_csv(latest_file)
    if '종목선정일' in df_latest.columns:
        csv_base_date = pd.to_datetime(df_latest['종목선정일'].iloc[0])
        today = datetime.today()
        
        updates = 0
        for idx, row in df_latest.iterrows():
            code = str(row['종목코드'])
            try:
                df_h = fdr.DataReader(code, csv_base_date, today)
                if not df_h.empty:
                    curr_p = df_h['Close'].iloc[-1]
                    base_p = df_h['Close'].iloc[0]
                    if base_p > 0:
                        df_latest.at[idx, '이번달수익률'] = round(((curr_p / base_p) - 1) * 100, 2)
                        updates += 1
            except: pass
            
        if updates > 0:
            df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
            print(f"✅ 월간 파일({latest_file})의 '이번달수익률' 실시간 동기화 완료!")

def main():
    archive_folder = 'archive_usa'
    output_file = 'data/momentum_data_daily_usa300.csv'
    os.makedirs('data', exist_ok=True)
    
    archive_files = sorted(glob.glob(f'{archive_folder}/usa300_*.csv'))
    if not archive_files:
        print(f"🚨 {archive_folder} 폴더에 아카이브 파일이 없습니다.")
        return
        
    latest_file = archive_files[-1]
    print(f"📌 USA 300 유니버스 로드: {latest_file}")
    
    df_latest = pd.read_csv(latest_file)
    
    # 💡 유니버스 추출 시 시가총액 유지
    cols_to_extract = ['종목코드', '종목명', '시장']
    if '시가총액_raw' in df_latest.columns: cols_to_extract.append('시가총액_raw')
    elif '시가총액' in df_latest.columns: cols_to_extract.append('시가총액')
    universe = df_latest[cols_to_extract].drop_duplicates(subset=['종목코드'])
    
    today = datetime.today()
    real_base_date_str = get_last_business_day_us()
    real_base_date = pd.to_datetime(real_base_date_str)
    
    dates = {
        1: get_end_of_month(real_base_date, 1),
        3: get_end_of_month(real_base_date, 3),
        6: get_end_of_month(real_base_date, 6),
        12: get_end_of_month(real_base_date, 12)
    }
    start_date = get_end_of_month(real_base_date, 13)
    
    results = []
    print(f"🚀 데일리 데이터 생성 중... ({real_base_date_str} 기준)")
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_ticker_us, row, start_date, today, dates, real_base_date_str) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)
            
    if results:
        pd.DataFrame(results).to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"🎉 데일리 데이터 저장 완료: {output_file}")
        sync_archive_returns_us(archive_folder)
    else:
        print("🚨 데일리 데이터 수집 실패")

if __name__ == "__main__":
    main()
