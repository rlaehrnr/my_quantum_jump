import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime
import os
import time

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
    print("🚀 매월 1일: 신규 월간 아카이브 생성 봇 가동...")
    
    # 1. 날짜 세팅 (매월 1일에 실행된다고 가정)
    today = datetime.today()
    invest_year = today.year
    invest_month_str = today.strftime('%Y-%m') # 예: 2026-05
    
    # 전월 마지막 거래일(선정일) 찾기
    first_day_of_month = today.replace(day=1)
    last_day_prev = first_day_of_month - pd.Timedelta(days=1)
    df_idx = fdr.DataReader('KS11', last_day_prev - pd.Timedelta(days=10), last_day_prev)
    base_date = df_idx.index[-1]
    base_date_str = base_date.strftime('%Y-%m-%d')
    
    print(f"✅ 신규 투자월: {invest_month_str} (기준일: {base_date_str})")

    # 모멘텀 측정을 위한 1, 3, 6, 12개월 전 말일
    dates = {
        '1개월': get_end_of_month(base_date, 1),
        '3개월': get_end_of_month(base_date, 3),
        '6개월': get_end_of_month(base_date, 6),
        '12개월': get_end_of_month(base_date, 12)
    }
    start_date = dates['12개월'] - pd.Timedelta(days=15)

    # 2. 시장 데이터 다운로드
    df_kospi = fdr.StockListing('KOSPI')
    df_kospi['Code'] = df_kospi['Code'].astype(str).str.zfill(6)
    df_kospi = df_kospi[df_kospi['Code'].str.endswith('0')]
    
    df_kosdaq = fdr.StockListing('KOSDAQ')
    df_kosdaq['Code'] = df_kosdaq['Code'].astype(str).str.zfill(6)
    df_kosdaq = df_kosdaq[df_kosdaq['Code'].str.endswith('0')]
    
    k200 = df_kospi.sort_values('Marcap', ascending=False).head(200)
    korea300 = pd.concat([
        df_kospi.sort_values('Marcap', ascending=False).head(150),
        df_kosdaq.sort_values('Marcap', ascending=False).head(150)
    ])
    
    shares_dict_k200 = {row['Code']: row['Marcap']/row['Close'] for _, row in k200.iterrows() if row['Close'] > 0}
    shares_dict_korea = {row['Code']: row['Marcap']/row['Close'] for _, row in korea300.iterrows() if row['Close'] > 0}

    # 3. 데이터 추출 공통 함수
    def build_archive(universe_df, shares_dict):
        records = []
        for _, row in universe_df.iterrows():
            code = row['Code']
            try:
                df_hist = fdr.DataReader(code, start_date, base_date)
                if df_hist.empty: continue
                
                base_price = df_hist['Close'].iloc[-1]
                curr_vol = df_hist['Volume'].iloc[-1] if 'Volume' in df_hist.columns else 0
                calc_marcap = int(base_price * shares_dict.get(code, 0))
                
                records.append({
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
                    '이번달수익률': 0.0 # 생성 시점에는 0, 이후 데일리 봇이 매일 갱신함
                })
            except: continue
        return pd.DataFrame(records)

    # 4. 각각 파일 생성 및 저장
    os.makedirs('archive_kospi', exist_ok=True)
    os.makedirs('archive_korea', exist_ok=True)
    
    print("▶️ KOSPI 200 데이터 생성 중...")
    df_k200_final = build_archive(k200, shares_dict_k200)
    if not df_k200_final.empty:
        df_k200_final.to_csv(f'archive_kospi/only_kospi_{invest_month_str.replace("-", "_")}.csv', index=False, encoding='utf-8-sig')

    print("▶️ KOREA 통합 300 데이터 생성 중...")
    df_korea_final = build_archive(korea300, shares_dict_korea)
    if not df_korea_final.empty:
        df_korea_final.to_csv(f'archive_korea/only_korea_{invest_month_str.replace("-", "_")}.csv', index=False, encoding='utf-8-sig')
        
    print(f"🎉 {invest_month_str} 신규 파일 2종 자동 생성 완료!")

if __name__ == "__main__":
    generate_monthly_archive()
