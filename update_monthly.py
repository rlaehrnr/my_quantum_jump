import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime
import os

def get_end_of_month(dt, months_ago):
    first_of_current = dt.replace(day=1)
    target_month = first_of_current - pd.DateOffset(months=months_ago - 1)
    return target_month - pd.Timedelta(days=1)

def calculate_past_return(df_hist, target_date, base_price):
    try:
        past_df = df_hist[df_hist.index <= pd.to_datetime(target_date)]
        if past_df.empty or base_price <= 0: return 0.0
        return round(((base_price / past_df['Close'].iloc[-1]) - 1) * 100, 2)
    except:
        return 0.0

def generate_monthly_archive():
    print("🚀 [통합] 매월 1일: 신규 월간 아카이브 생성 봇 가동...")
    
    today = datetime.today()
    invest_year = today.year
    invest_month_str = today.strftime('%Y-%m')
    
    # 전월 마지막 거래일(선정일) 찾기
    first_day_of_month = today.replace(day=1)
    last_day_prev = first_day_of_month - pd.Timedelta(days=1)
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

    # 1. 전체 유니버스 정의
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    df_kospi['Code'] = df_kospi['Code'].astype(str).str.zfill(6)
    df_kosdaq['Code'] = df_kosdaq['Code'].astype(str).str.zfill(6)
    
    df_kospi = df_kospi[df_kospi['Code'].str.endswith('0')]
    df_kosdaq = df_kosdaq[df_kosdaq['Code'].str.endswith('0')]
    
    k200_df = df_kospi.sort_values('Marcap', ascending=False).head(200).copy()
    k150_df = df_kospi.sort_values('Marcap', ascending=False).head(150).copy()
    d150_df = df_kosdaq.sort_values('Marcap', ascending=False).head(150).copy()
    korea300_df = pd.concat([k150_df, d150_df]).copy()
    
    # 중복을 제거한 전체 타겟
    all_target_df = pd.concat([k200_df, korea300_df]).drop_duplicates(subset=['Code']).copy()
    
    # 2. 단 1회! 전체 종목 과거 주가 다운로드 및 계산
    print(f"📊 총 {len(all_target_df)}개 종목 주가 다운로드 및 모멘텀 계산 중...")
    monthly_records_dict = {}
    
    for _, row in all_target_df.iterrows():
        code = row['Code']
        try:
            df_hist = fdr.DataReader(code, start_date, base_date)
            if df_hist.empty: continue
            
            base_price = df_hist['Close'].iloc[-1]
            curr_vol = df_hist['Volume'].iloc[-1] if 'Volume' in df_hist.columns else 0
            
            # 주식 수 역산 및 시총 재계산
            shares = row['Marcap'] / row['Close'] if row['Close'] > 0 else 0
            calc_marcap = int(base_price * shares)
            
            monthly_records_dict[code] = {
                '투자연도': invest_year,
                '투자월': invest_month_str,
                '종목선정일': base_date_str,
                '종목코드': code,
                '종목명': row['Name'],
                '1개월(%)': calculate_past_return(df_hist, dates['1개월'], base_price),
                '3개월(%)': calculate_past_return(df_hist, dates['3개월'], base_price),
                '6개월(%)': calculate_past_return(df_hist, dates['6개월'], base_price),
                '12개월(%)': calculate_past_return(df_hist, dates['12개월'], base_price),
                '시가총액': calc_marcap,
                '종가': base_price,
                '거래량': curr_vol,
                '이번달수익률': 0.0
            }
        except: continue

    # 3. KOSPI 200과 KOREA 300으로 각각 분리하여 저장
    os.makedirs('archive_kospi', exist_ok=True)
    os.makedirs('archive_korea', exist_ok=True)
    
    k200_records = [monthly_records_dict[c] for c in k200_df['Code'] if c in monthly_records_dict]
    if k200_records:
        pd.DataFrame(k200_records).to_csv(f'archive_kospi/only_kospi_{invest_month_str.replace("-", "_")}.csv', index=False, encoding='utf-8-sig')

    korea300_records = [monthly_records_dict[c] for c in korea300_df['Code'] if c in monthly_records_dict]
    if korea300_records:
        pd.DataFrame(korea300_records).to_csv(f'archive_korea/only_korea_{invest_month_str.replace("-", "_")}.csv', index=False, encoding='utf-8-sig')
        
    print(f"🎉 {invest_month_str} KOSPI200 및 KOREA 통합 파일 생성 완벽 종료!")

if __name__ == "__main__":
    generate_monthly_archive()
