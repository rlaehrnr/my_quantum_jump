import requests
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    except:
        return 0.0

def process_ticker(row, start_date, today, dates):
    code = row['Code']
    name = row['Name']
    market = row['시장']
    marcap = row['Marcap']
    
    try:
        df_hist = fdr.DataReader(code, start_date, today)
        if df_hist.empty: return None
        
        curr_price = df_hist['Close'].iloc[-1]
        curr_vol = df_hist['Volume'].iloc[-1] if 'Volume' in df_hist.columns else 0
        
        record = {
            '종목코드': code, 
            '종목명': name, 
            '시장': market,
            '기준일': today.strftime('%Y-%m-%d'),
            '시가총액': marcap, 
            '종가': curr_price, 
            '거래량': curr_vol,
            '1개월(%)': calculate_return_unified(df_hist, dates['1개월'], curr_price),
            '3개월(%)': calculate_return_unified(df_hist, dates['3개월'], curr_price),
            '6개월(%)': calculate_return_unified(df_hist, dates['6개월'], curr_price),
            '12개월(%)': calculate_return_unified(df_hist, dates['12개월'], curr_price)
        }
        return code, record, df_hist
    except:
        return None

def update_all_daily_momentum():
    print("🚀 [최적화 버전] 데일리 수익률 (KR/US) 및 VIX 데이터 동기화 시작...")
    today = datetime.today()
    base_date = today.strftime('%Y-%m-%d')
    os.makedirs('data', exist_ok=True)

    print("📈 미국 VIX 지수 데이터 업데이트 중...")
    try:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/^VIX?interval=1d&range=5y"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers)
        data = res.json()
        timestamps = data['chart']['result'][0]['timestamp']
        quote = data['chart']['result'][0]['indicators']['quote'][0]
        df_vix = pd.DataFrame({'날짜': pd.to_datetime(timestamps, unit='s'), '시가': quote['open'], '고가': quote['high'], '저가': quote['low'], '종가': quote['close']}).dropna()
        df_vix['날짜'] = df_vix['날짜'].dt.strftime('%Y-%m-%d')
        df_vix['변동 %'] = df_vix['종가'].pct_change().multiply(100).round(2).astype(str) + '%'
        df_vix[['날짜', '종가', '시가', '고가', '저가', '변동 %']].to_csv('data/vix data.csv', index=False, encoding='utf-8-sig')
        print("✅ VIX 지수 업데이트 성공!")
    except Exception as e: print(f"🚨 VIX 다운로드 실패: {e}")

    print("🔄 한국 및 미국 주식 시장 데이터 로드 중...")
    df_kospi = fdr.StockListing('KOSPI')
    df_kosdaq = fdr.StockListing('KOSDAQ')
    df_kospi['Code'] = df_kospi['Code'].astype(str).str.zfill(6)
    df_kosdaq['Code'] = df_kosdaq['Code'].astype(str).str.zfill(6)
    df_kospi['시장'], df_kosdaq['시장'] = 'KOSPI', 'KOSDAQ'
    
    df_kospi = df_kospi[df_kospi['Code'].str.endswith('0')].copy()
    df_kosdaq = df_kosdaq[df_kosdaq['Code'].str.endswith('0')].copy()
    
    k200_df = df_kospi.sort_values('Marcap', ascending=False).head(200).copy()
    k150_df = df_kospi.sort_values('Marcap', ascending=False).head(150).copy()
    d150_df = df_kosdaq.sort_values('Marcap', ascending=False).head(150).copy()
    korea300_df = pd.concat([k150_df, d150_df]).copy()
    
    all_target_df = pd.concat([k200_df, korea300_df]).drop_duplicates(subset=['Code']).copy()

    # 💡 [추가] 미국 S&P 500 목록 가져오기
    try:
        df_sp500 = fdr.StockListing('S&P500')
        df_sp500['Code'] = df_sp500['Symbol'].str.replace('.', '-', regex=False)
        df_sp500['Name'] = df_sp500['Symbol'] if 'Name' not in df_sp500.columns else df_sp500['Name']
        df_sp500['시장'] = 'S&P500'
        df_sp500['Marcap'] = 0
        all_target_df = pd.concat([all_target_df, df_sp500[['Code', 'Name', '시장', 'Marcap']]]).drop_duplicates(subset=['Code']).copy()
    except Exception as e:
        print(f"⚠️ S&P 500 목록 로드 실패: {e}")
        df_sp500 = pd.DataFrame()

    shares_dict = {row['Code']: row['Marcap']/row['Close'] for _, row in all_target_df.iterrows() if row.get('Close', 0) > 0}
    
    last_month_end = get_end_of_month(today, 1)
    dates = { '1개월': last_month_end, '3개월': get_end_of_month(today, 3), '6개월': get_end_of_month(today, 6), '12개월': get_end_of_month(today, 12) }
    start_date = dates['12개월'] - timedelta(days=15)
    
    print(f"📊 총 {len(all_target_df)}개 종목 주가 동시 다운로드 중...")
    price_cache = {}
    daily_records_dict = {}
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_ticker, row, start_date, today, dates) for _, row in all_target_df.iterrows()]
        for future in as_completed(futures):
            result = future.result()
            if result:
                code, record, df_hist = result
                daily_records_dict[code] = record
                price_cache[code] = df_hist

    k200_records = [daily_records_dict[c] for c in k200_df['Code'] if c in daily_records_dict]
    pd.DataFrame(k200_records).to_csv('data/momentum_data_daily.csv', index=False, encoding='utf-8-sig')
    
    korea300_records = [daily_records_dict[c] for c in korea300_df['Code'] if c in daily_records_dict]
    pd.DataFrame(korea300_records).to_csv('data/momentum_data_daily_korea.csv', index=False, encoding='utf-8-sig')

    # 💡 [추가] 미국 데일리 파일 저장
    if not df_sp500.empty:
        sp500_records = [daily_records_dict[c] for c in df_sp500['Code'] if c in daily_records_dict]
        pd.DataFrame(sp500_records).to_csv('data/momentum_data_daily_sp500.csv', index=False, encoding='utf-8-sig')

    print("✅ 데일리 모멘텀 저장 완료!")

    def sync_archive_returns(archive_folder):
        archive_files = sorted(glob.glob(f'{archive_folder}/only_*.csv'))
        if not archive_files: return
        latest_file = archive_files[-1]
        df_latest = pd.read_csv(latest_file, dtype={'종목코드': str, 'Ticker': str})
        
        target_col = '종목선정일' if '종목선정일' in df_latest.columns else 'Date'
        code_col = '종목코드' if '종목코드' in df_latest.columns else 'Ticker'
        ret_col = '이번달수익률' if '이번달수익률' in df_latest.columns else 'Forward_1M_Return(%)'
        
        if target_col in df_latest.columns:
            csv_base_date = df_latest[target_col].iloc[0]
            for idx, row in df_latest.iterrows():
                code = str(row[code_col]).zfill(6) if 'archive_kospi' in archive_folder or 'archive_korea' in archive_folder else str(row[code_col])
                df_h = price_cache.get(code, pd.DataFrame())
                if df_h.empty:
                    try: df_h = fdr.DataReader(code, csv_base_date, today)
                    except: pass
                
                if not df_h.empty:
                    curr_p = df_h['Close'].iloc[-1]
                    df_latest.at[idx, ret_col] = calculate_return_unified(df_h, csv_base_date, curr_p)
            
            df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
            print(f"✅ {archive_folder} 월별 아카이브 동기화 완료!")

    sync_archive_returns('archive_kospi')
    sync_archive_returns('archive_korea')
    sync_archive_returns('archive_sp500') # 💡 미국 월별 아카이브도 이번달 수익률 채워줌
    print("🎉 고속 업데이트 완벽 종료!")

if __name__ == "__main__":
    update_all_daily_momentum()
