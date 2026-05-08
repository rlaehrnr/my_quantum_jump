import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime
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
    except:
        return 0.0

def process_monthly_ticker_us(row, start_date, base_date, dates, base_date_str):
    code = str(row['종목코드']).strip()
    name = row['종목명']
    market = row['시장']
    
    try:
        df_hist = fdr.DataReader(code, start_date, base_date)
        if df_hist.empty: return None
        if df_hist.index.tz is not None: df_hist.index = df_hist.index.tz_localize(None)
        
        base_price = df_hist['Close'].iloc[-1]
        
        ret_1m = calculate_past_return(df_hist, dates[1], base_price)
        ret_3m = calculate_past_return(df_hist, dates[3], base_price)
        ret_6m = calculate_past_return(df_hist, dates[6], base_price)
        ret_12m = calculate_past_return(df_hist, dates[12], base_price)
        
        return {
            '종목선정일': base_date_str,
            '시장': market,
            '종목명': name,
            '종목코드': code,
            '시가총액': 0, 
            '종가': base_price,
            '1개월(%)': ret_1m,
            '3개월(%)': ret_3m,
            '6개월(%)': ret_6m,
            '12개월(%)': ret_12m,
            '이번달수익률': 0.0 # 데일리 스크립트가 나중에 채워줍니다.
        }
    except: return None

def main():
    archive_folder = 'archive_usa'
    os.makedirs(archive_folder, exist_ok=True)
    
    archive_files = sorted(glob.glob(f'{archive_folder}/usa300_*.csv'))
    if not archive_files:
        print("🚨 아카이브 폴더에 이전 데이터가 없습니다. usa300_YYYY_MM.csv 파일을 넣어주세요.")
        return
        
    latest_file = archive_files[-1]
    print(f"📌 최신 유니버스 300종목 상속 (출처: {latest_file})")
    df_latest = pd.read_csv(latest_file)
    universe = df_latest[['종목코드', '종목명', '시장']].drop_duplicates()
    
    # 이번 달을 계산하기 위한 기준일 (보통 전월 말일)
    today = datetime.today()
    base_date = get_end_of_month(today, 1)
    base_date_str = base_date.strftime('%Y-%m-%d')
    invest_year = base_date.year
    invest_month_str = f"{invest_year}-{base_date.month:02d}"
    
    dates = {
        1: get_end_of_month(base_date, 1),
        3: get_end_of_month(base_date, 3),
        6: get_end_of_month(base_date, 6),
        12: get_end_of_month(base_date, 12)
    }
    start_date = get_end_of_month(base_date, 13)
    
    print(f"📊 {invest_month_str} (기준일: {base_date_str}) 모멘텀 계산 시작...")
    
    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker_us, row, start_date, base_date, dates, base_date_str) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)
            
    if results:
        df_res = pd.DataFrame(results)
        output_filename = f"{archive_folder}/usa300_{invest_year}_{base_date.month:02d}.csv"
        df_res.to_csv(output_filename, index=False, encoding='utf-8-sig')
        print(f"✅ 월간 모멘텀 데이터 저장 완료: {output_filename}")
    else:
        print("🚨 데이터 수집 실패")

if __name__ == "__main__":
    main()
