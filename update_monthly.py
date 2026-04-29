import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- [기존 헬퍼 함수 유지] ---
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

# --- [개별 종목 처리 워커 함수] ---
def process_monthly_ticker(row, start_date, base_date, dates, invest_year, invest_month_str, base_date_str):
    code = row['Code']
    name = row['Name']
    market = row['시장']
    marcap = row['Marcap']
    
    try:
        df_hist = fdr.DataReader(code, start_date, base_date)
        if df_hist.empty: return None
        
        base_price = df_hist['Close'].iloc[-1]
        curr_vol = df_hist['Volume'].iloc[-1] if 'Volume' in df_hist.columns else 0
        
        # 주식 수 역산 및 시총 재계산
        shares = marcap / row['Close'] if row['Close'] > 0 else 0
        calc_marcap = int(base_price * shares)
        
        record = {
            '투자연도': invest_year,
            '투자월': invest_month_str,
            '종목선정일': base_date_str,
            '종목코드': code,
            '종목명': name,
            '시장': market,  # 💡 시장 정보 추가 (중요!)
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

def generate_monthly_archive():
    print("🚀 [최적화] 월간 아카이브 생성 시작 (멀티스레딩 적용)...")
    
    today = datetime.today()
    invest_year = today.year
    invest_month_str = today.strftime('%Y-%m')
    
    # 1. 선정일(지난달 말일) 기준 잡기
    first_day_of_current = today.replace(day=1)
    last_day_prev = first_day_of_current - pd.Timedelta(days=1)
    df_idx = fdr.DataReader('KS11', last_day_prev - pd.Timedelta(days=10), last_day_prev)
    base_date = df_idx.index[-1]
    base_date_str = base_date.strftime('%Y-%m-%d')
    
    print(f"✅ 신규 투자월: {invest_month_str} (선정일 기준: {base_date_str})")

    dates = {
        '1개월': get_end_of_month(base_date, 1),
        '3개월': get_end_of_month(base_date, 3),
        '6개월': get_end_of_month(base_date, 6),
        '12개월': get_end_of_month(base_date, 12)
    }
    start_date = dates['12개월'] - pd.Timedelta(days=15)

    # 2. 유니버스 세팅 및 시장 정보 태깅
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    df_kospi['Code'] = df_kospi['Code'].astype(str).str.zfill(6)
    df_kosdaq['Code'] = df_kosdaq['Code'].astype(str).str.zfill(6)
    
    df_kospi['시장'] = 'KOSPI'
    df_kosdaq['시장'] = 'KOSDAQ'
    
    df_kospi = df_kospi[df_kospi['Code'].str.endswith('0')]
    df_kosdaq = df_kosdaq[df_kosdaq['Code'].str.endswith('0')]
    
    k200_df = df_kospi.sort_values('Marcap', ascending=False).head(200).copy()
    k150_df = df_kospi.sort_values('Marcap', ascending=False).head(150).copy()
    d150_df = df_kosdaq.sort_values('Marcap', ascending=False).head(150).copy()
    korea300_df = pd.concat([k150_df, d150_df]).copy()
    
    all_target_df = pd.concat([k200_df, korea300_df]).drop_duplicates(subset=['Code']).copy()

    # 3. 멀티스레딩으로 데이터 고속 계산
    print(f"📊 총 {len(all_target_df)}개 종목 모멘텀 고속 계산 중...")
    monthly_records_dict = {}

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker, row, start_date, base_date, dates, invest_year, invest_month_str, base_date_str) for _, row in all_target_df.iterrows()]
        
        for future in as_completed(futures):
            res = future.result()
            if res:
                code, record = res
                monthly_records_dict[code] = record

    # 4. 파일 분리 및 저장
    os.makedirs('archive_kospi', exist_ok=True)
    os.makedirs('archive_korea', exist_ok=True)
    
    file_suffix = invest_month_str.replace("-", "_")
    
    # KOSPI 200 저장
    k200_records = [monthly_records_dict[c] for c in k200_df['Code'] if c in monthly_records_dict]
    if k200_records:
        pd.DataFrame(k200_records).to_csv(f'archive_kospi/only_kospi_{file_suffix}.csv', index=False, encoding='utf-8-sig')

    # KOREA 300 저장
    korea300_records = [monthly_records_dict[c] for c in korea300_df['Code'] if c in monthly_records_dict]
    if korea300_records:
        pd.DataFrame(korea300_records).to_csv(f'archive_korea/only_korea_{file_suffix}.csv', index=False, encoding='utf-8-sig')
        
    print(f"🎉 {invest_month_str} 아카이브 생성 완벽 완료!")

if __name__ == "__main__":
    generate_monthly_archive()
