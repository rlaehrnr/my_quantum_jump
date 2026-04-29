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
    print("🚀 [최적화 버전] 데일리 수익률 및 VIX 데이터 동기화 시작...")
    today = datetime.today()
    base_date = today.strftime('%Y-%m-%d')
    
    os.makedirs('data', exist_ok=True)

    # ==========================================
    # 💡 [신규 추가] VIX 지수 자동 다운로드 로직
    # ==========================================
    print("📈 미국 VIX 지수 데이터 업데이트 중...")
    try:
        # VIX 지수를 넉넉하게 과거부터 수집 (VIX 또는 ^VIX)
        try: df_vix = fdr.DataReader('VIX', '2015-01-01', today)
        except: df_vix = fdr.DataReader('^VIX', '2015-01-01', today)
        
        if not df_vix.empty:
            df_vix = df_vix.reset_index()
            # 파일 포맷 맞추기
            df_vix.rename(columns={'Date': '날짜', 'Close': '종가', 'Open': '시가', 'High': '고가', 'Low': '저가'}, inplace=True)
            if 'Change' in df_vix.columns:
                df_vix['변동 %'] = (df_vix['Change'] * 100).round(2).astype(str) + '%'
            else:
                df_vix['변동 %'] = df_vix['종가'].pct_change().multiply(100).round(2).astype(str) + '%'
                
            df_vix['날짜'] = df_vix['날짜'].dt.strftime('%Y-%m-%d')
            cols = ['날짜', '종가', '시가', '고가', '저가', '변동 %']
            df_vix[cols].to_csv('data/vix data.csv', index=False, encoding='utf-8-sig')
            print("✅ VIX 지수 업데이트 완료!")
    except Exception as e:
        print(f"⚠️ VIX 지수 업데이트 실패: {e}")

    # ==========================================
    # 1. 한국 시장 유니버스 세팅
    # ==========================================
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
    shares_dict = {row['Code']: row['Marcap']/row['Close'] for _, row in all_target_df.iterrows() if row['Close'] > 0}
    
    last_month_end = get_end_of_month(today, 1)
    dates = { '1개월': last_month_end, '3개월': get_end_of_month(today, 3), '6개월': get_end_of_month(today, 6), '12개월': get_end_of_month(today, 12) }
    start_date = dates['12개월'] - timedelta(days=15)
    
    # ==========================================
    # 2. 멀티스레딩 데이터 수집
    # ==========================================
    print(f"📊 총 {len(all_target_df)}개 종목 동시 다운로드 중...")
    price_cache = {}
    daily_records_dict = {}
    
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(process_ticker, row, start_date, today, dates) for _, row in all_target_df.iterrows()]
        
        for future in as_completed(futures):
            result = future.result()
            if result:
                code, record, df_hist = result
                daily_records_dict[code] = record
                price_cache[code] = df_hist

    # 3. 데일리 파일 저장
    k200_records = [daily_records_dict[c] for c in k200_df['Code'] if c in daily_records_dict]
    pd.DataFrame(k200_records).to_csv('data/momentum_data_daily.csv', index=False, encoding='utf-8-sig')
    
    korea300_records = [daily_records_dict[c] for c in korea300_df['Code'] if c in daily_records_dict]
    pd.DataFrame(korea300_records).to_csv('data/momentum_data_daily_korea.csv', index=False, encoding='utf-8-sig')
    print("✅ 데일리 종목 파일 저장 완료!")

    # 4. 월간 아카이브 동기화
    def sync_archive_returns(archive_folder):
        archive_files = sorted(glob.glob(f'{archive_folder}/momentum_*.csv'))
        if not archive_files: return
        latest_file = archive_files[-1]
        df_latest = pd.read_csv(latest_file, dtype={'종목코드': str})
        
        if '종목선정일' in df_latest.columns:
            csv_base_date = df_latest['종목선정일'].iloc[0]
            for idx, row in df_latest.iterrows():
                code = row['종목코드'].zfill(6)
                df_h = price_cache.get(code, pd.DataFrame())
                if df_h.empty:
                    try: df_h = fdr.DataReader(code, csv_base_date, today)
                    except: pass
                
                if not df_h.empty:
                    curr_p = df_h['Close'].iloc[-1]
                    df_latest.at[idx, '이번달수익률'] = calculate_return_unified(df_h, csv_base_date, curr_p)
                    past_df = df_h[df_h.index <= pd.to_datetime(csv_base_date)]
                    if not past_df.empty:
                        bp = past_df['Close'].iloc[-1]
                        df_latest.at[idx, '종가'] = bp
                        df_latest.at[idx, '시가총액'] = int(bp * shares_dict.get(code, 0))
            
            df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
            print(f"✅ {archive_folder} 동기화 완료!")

    sync_archive_returns('archive_kospi')
    sync_archive_returns('archive_korea')
    print("🎉 고속 업데이트 완료!")

if __name__ == "__main__":
    update_all_daily_momentum()
