import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 🇰🇷 KRX 종목 리스팅 (fdr.StockListing 대체)
# FDR 라이브러리의 StockListing은 KRX 실시간 + 단일날짜 캐시파일을 받는데,
# 특정 날짜 캐시파일이 비면 404로 죽는다. 여기서는 그 캐시 CSV를 직접 받되,
# 해당 날짜가 없으면 최근 영업일로 거슬러 올라가 견고하게 처리한다.
# KRX 실시간 질의가 없으므로 클라우드/CI IP 차단과 무관.
# 반환 컬럼: Code(6자리 str), Name, Marcap(시가총액), Close(종가)
# ==========================================
FDR_CACHE_BASE = "https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx"
_MARKET_ID = {'KOSPI': 'STK', 'KOSDAQ': 'KSQ', 'KONEX': 'KNX'}

def fetch_krx_listing(market, ref_date_str):
    base = pd.to_datetime(str(ref_date_str).replace('-', ''), format='%Y%m%d')
    df = None
    used_day = None
    for back in range(0, 11):  # 캐시 파일이 빈 날짜면 최대 10일 거슬러 올라감
        day = (base - pd.Timedelta(days=back)).strftime('%Y-%m-%d')
        url = f"{FDR_CACHE_BASE}/{day}.csv"
        try:
            tmp = pd.read_csv(url, index_col=0, dtype={'Code': str, 'MarketId': str})
        except Exception:
            tmp = None
        if tmp is not None and not tmp.empty:
            df, used_day = tmp, day
            break
    if df is None:
        raise RuntimeError(f"KRX 리스팅 캐시 조회 실패 (기준일 {ref_date_str} 부근 파일 없음)")
    if used_day != base.strftime('%Y-%m-%d'):
        print(f"   ↳ {market}: {ref_date_str} 캐시 없음 → {used_day} 사용")
    df = df[df['MarketId'] == _MARKET_ID[market]].copy()
    return pd.DataFrame({
        'Code': df['Code'].astype(str).str.zfill(6),
        'Name': df['Name'].astype(str),
        'Marcap': pd.to_numeric(df['Marcap'], errors='coerce').fillna(0).astype('int64'),
        'Close': pd.to_numeric(df['Close'], errors='coerce').fillna(0.0),
    })

# ==========================================
# 🇰🇷 한국 시장 유효 영업일 추출 (KOSPI 지수 기준)
# ==========================================
def get_last_business_day_kr():
    try:
        df = fdr.DataReader('KS11', datetime.today() - timedelta(days=14))
        valid_days = df[df['Volume'] > 1000] 
        if not valid_days.empty:
            return valid_days.index[-1].strftime('%Y-%m-%d')
    except:
        pass
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
    except:
        return 0.0

def process_ticker_kr(row, start_date, today, dates, real_base_date_str):
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
            '기준일': real_base_date_str, 
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

def update_daily_momentum_kr():
    print("🚀 [한국 전용] 데일리 수익률 업데이트 시작...")
    today = datetime.today()
    real_base_date_str = get_last_business_day_kr()
    print(f"✅ 정확한 한국 영업일 기준: {real_base_date_str}")
    
    os.makedirs('data', exist_ok=True)

    print("🔄 한국 주식 시장 데이터 로드 중... (FDR 캐시 직접 조회)")
    df_kospi = fetch_krx_listing('KOSPI', real_base_date_str)
    df_kosdaq = fetch_krx_listing('KOSDAQ', real_base_date_str)
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

    last_month_end = get_end_of_month(today, 1)
    dates = { '1개월': last_month_end, '3개월': get_end_of_month(today, 3), '6개월': get_end_of_month(today, 6), '12개월': get_end_of_month(today, 12) }
    start_date = dates['12개월'] - timedelta(days=15)
    
    print(f"📊 총 {len(all_target_df)}개 한국 종목 주가 다운로드 중...")
    price_cache = {}
    daily_records_dict = {}
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_ticker_kr, row, start_date, today, dates, real_base_date_str) for _, row in all_target_df.iterrows()]
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

    print("✅ 한국 데일리 모멘텀 저장 완료!")

    def sync_archive_returns(archive_folder):
        archive_files = sorted(glob.glob(f'{archive_folder}/only_*.csv'))
        if not archive_files: return
        latest_file = archive_files[-1]
        df_latest = pd.read_csv(latest_file, dtype={'종목코드': str})
        
        target_col = '종목선정일' if '종목선정일' in df_latest.columns else 'Date'
        code_col = '종목코드' 
        ret_col = '이번달수익률' if '이번달수익률' in df_latest.columns else 'Forward_1M_Return(%)'
        
        if target_col in df_latest.columns:
            csv_base_date = df_latest[target_col].iloc[0]
            for idx, row in df_latest.iterrows():
                code = str(row[code_col]).zfill(6)
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
    print("🎉 🇰🇷 한국 업데이트 완벽 종료!")

if __name__ == "__main__":
    update_daily_momentum_kr()
