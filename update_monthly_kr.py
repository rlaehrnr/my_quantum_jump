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

def process_monthly_ticker_kr(row, start_date, base_date, dates, invest_year, invest_month_str, base_date_str):
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

def generate_monthly_archive_kr():
    print("🚀 [한국 전용] 월간 아카이브 생성 시작...")
    
    today = datetime.today()
    invest_year = today.year
    invest_month_str = today.strftime('%Y_%m')
    
    # 한국 지수(KS11)를 기준으로 지난달 마지막 영업일 탐색
    first_day_of_current = today.replace(day=1)
    last_day_prev = first_day_of_current - pd.Timedelta(days=1)
    df_idx = fdr.DataReader('KS11', last_day_prev - pd.Timedelta(days=10), last_day_prev)
    base_date = df_idx.index[-1]
    base_date_str = base_date.strftime('%Y-%m-%d')
    
    print(f"✅ 🇰🇷 신규 투자월: {invest_month_str.replace('_', '-')} (한국 기준 선정일: {base_date_str})")

    dates = {'1개월': get_end_of_month(base_date, 1), '3개월': get_end_of_month(base_date, 3), '6개월': get_end_of_month(base_date, 6), '12개월': get_end_of_month(base_date, 12)}
    start_date = dates['12개월'] - pd.Timedelta(days=15)

    print("🔄 한국 거래소 종목 마스터 데이터 구축 중...")
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    df_kospi['Code'], df_kosdaq['Code'] = df_kospi['Code'].astype(str).str.zfill(6), df_kosdaq['Code'].astype(str).str.zfill(6)
    df_kospi['시장'], df_kosdaq['시장'] = 'KOSPI', 'KOSDAQ'
    
    df_kospi_f = df_kospi[df_kospi['Code'].str.endswith('0')].sort_values('Marcap', ascending=False).head(200)
    df_korea_f = pd.concat([df_kospi.sort_values('Marcap', ascending=False).head(150), df_kosdaq.sort_values('Marcap', ascending=False).head(150)]).drop_duplicates(subset=['Code'])
    
    all_target_df = pd.concat([df_kospi_f, df_korea_f]).drop_duplicates(subset=['Code']).copy()

    print(f"📊 총 {len(all_target_df)}개 한국 종목 모멘텀 계산 중...")
    monthly_records_dict = {}

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker_kr, row, start_date, base_date, dates, invest_year, invest_month_str.replace('_', '-'), base_date_str) for _, row in all_target_df.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res:
                code, record = res
                monthly_records_dict[code] = record

    os.makedirs('archive_kospi', exist_ok=True); os.makedirs('archive_korea', exist_ok=True)
    
    if df_kospi_f is not None:
        recs = [monthly_records_dict[c] for c in df_kospi_f['Code'] if c in monthly_records_dict]
        pd.DataFrame(recs).to_csv(f'archive_kospi/only_kospi_{invest_month_str}.csv', index=False, encoding='utf-8-sig')

    recs_k = [monthly_records_dict[c] for c in df_korea_f['Code'] if c in monthly_records_dict]
    pd.DataFrame(recs_k).to_csv(f'archive_korea/only_korea_{invest_month_str}.csv', index=False, encoding='utf-8-sig')

    print(f"🎉 🇰🇷 {invest_month_str.replace('_', '-')} 한국 아카이브 생성 완료!")

if __name__ == "__main__":
    generate_monthly_archive_kr()
