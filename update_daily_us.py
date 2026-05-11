import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import glob
import time
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

def process_daily_ticker(row, start_date, today, dates, real_base_date_str, csv_base_date=None):
    time.sleep(0.1) # 💡 야후 파이낸스 IP 차단(Rate Limit) 방지용 0.1초 딜레이
    
    code = str(row['종목코드']).strip()
    fdr_code = code.replace('.', '-') # 💡 BRK.B 같은 티커를 BRK-B로 자동 변환 (미국장 필수)
    name, market = row.get('종목명', code), row.get('시장', 'US')
    marcap = row.get('시가총액_raw', row.get('시가총액', 0))

    try:
        df_hist = fdr.DataReader(fdr_code, start_date, today)
        if df_hist.empty: return None
        if df_hist.index.tz is not None: df_hist.index = df_hist.index.tz_localize(None)
        
        curr_p = df_hist['Close'].iloc[-1]
        
        # 💡 [핵심 최적화] 일간 데이터 뽑을 때 '이번달수익률'도 한 번에 계산! (API 호출 절반으로 단축)
        this_month_ret = 0.0
        if csv_base_date is not None:
            month_df = df_hist[df_hist.index >= pd.to_datetime(csv_base_date)]
            if not month_df.empty and month_df['Close'].iloc[0] > 0:
                this_month_ret = round(((curr_p / month_df['Close'].iloc[0]) - 1) * 100, 2)

        return {
            '기준일': real_base_date_str, '시장': market, '종목명': name, '종목코드': code, 
            '시가총액': marcap, '종가': curr_p,
            '1개월(%)': calculate_return_unified(df_hist, dates[1], curr_p),
            '3개월(%)': calculate_return_unified(df_hist, dates[3], curr_p),
            '6개월(%)': calculate_return_unified(df_hist, dates[6], curr_p),
            '12개월(%)': calculate_return_unified(df_hist, dates[12], curr_p),
            '이번달수익률': this_month_ret # 아카이브 동기화를 위한 숨겨진 데이터
        }
    except: return None

def run_daily_update(target_name, archive_folder, output_file, real_base_date_str, real_base_date, today, dates, start_date):
    print(f"\n📌 [{target_name}] 데일리 업데이트 시작...")
    archive_files = sorted(glob.glob(f'{archive_folder}/only_*.csv'))
    if not archive_files:
        print(f"🚨 {archive_folder}에 데이터가 없습니다.")
        return
        
    latest_file = archive_files[-1]
    df_latest = pd.read_csv(latest_file)
    
    # 💡 엑셀 컬럼이 Ticker든 Symbol이든 문제없이 잡도록 방어 로직 강화
    rename_dict = {}
    for col in df_latest.columns:
        c_up = col.upper()
        if c_up in ['TICKER', 'SYMBOL']: rename_dict[col] = '종목코드'
        if c_up in ['NAME', 'COMPANY', 'SECURITY']: rename_dict[col] = '종목명'
        if c_up in ['DATE']: rename_dict[col] = '종목선정일'
    df_latest = df_latest.rename(columns=rename_dict)
    
    if '종목명' not in df_latest.columns: df_latest['종목명'] = df_latest['종목코드']
    if '시장' not in df_latest.columns: df_latest['시장'] = 'US'
        
    universe = df_latest[['종목코드', '종목명', '시장']].drop_duplicates(subset=['종목코드'])
    if '시가총액_raw' in df_latest.columns: universe['시가총액_raw'] = df_latest['시가총액_raw']
    elif '시가총액' in df_latest.columns: universe['시가총액_raw'] = df_latest['시가총액']

    csv_base_date = pd.to_datetime(df_latest['종목선정일'].iloc[0]) if '종목선정일' in df_latest.columns else None

    results = []
    # 💡 야후 서버 뻗음(429 Error) 방지를 위해 작업자 수를 20 -> 5 로 축소
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_daily_ticker, row, start_date, today, dates, real_base_date_str, csv_base_date) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)
            
    if results:
        res_df = pd.DataFrame(results)
        
        # 1. 일간 데일리 CSV 저장 (이번달수익률은 데일리용이 아니므로 제외)
        res_df.drop(columns=['이번달수익률']).to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"✅ [{target_name}] 데일리 데이터 ({len(res_df)}건) 저장 완료: {output_file}")
        
        # 2. [핵심] 아카이브 파일(only_*.csv)의 '이번달수익률' 일괄 최신화 (순식간에 처리됨)
        if csv_base_date is not None:
            ret_map = res_df.set_index('종목코드')['이번달수익률'].to_dict()
            df_latest['이번달수익률'] = df_latest['종목코드'].map(ret_map).fillna(df_latest.get('이번달수익률', 0.0))
            df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
            print(f"✅ [{target_name}] 월간 아카이브 (이번달수익률) 쾌속 동기화 완료!")
    else:
        print(f"❌ [{target_name}] 업데이트 실패 (야후 파이낸스에서 데이터를 가져오지 못했습니다).")

def main():
    os.makedirs('data', exist_ok=True)
    today = datetime.today()
    real_base_date_str = get_last_business_day_us()
    real_base_date = pd.to_datetime(real_base_date_str)
    
    dates = {1: get_end_of_month(real_base_date, 1), 3: get_end_of_month(real_base_date, 3), 6: get_end_of_month(real_base_date, 6), 12: get_end_of_month(real_base_date, 12)}
    start_date = get_end_of_month(real_base_date, 13)

    print(f"🚀 미국장 일간 통합 업데이트 시작 (기준일: {real_base_date_str})")
    
    # 1. SP500 업데이트
    run_daily_update('S&P 500', 'archive_sp500', 'data/momentum_data_daily_sp500.csv', real_base_date_str, real_base_date, today, dates, start_date)
    
    # 2. USA300 업데이트
    run_daily_update('USA 300', 'archive_usa', 'data/momentum_data_daily_usa300.csv', real_base_date_str, real_base_date, today, dates, start_date)
    
    print("\n🎉 모든 미국장 일간 업데이트가 완료되었습니다!")

if __name__ == "__main__":
    main()
