import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import glob
import time

def get_end_of_month(dt, months_ago):
    first_of_current = dt.replace(day=1)
    target_month = first_of_current - pd.DateOffset(months=months_ago - 1)
    return target_month - timedelta(days=1)

def update_daily_momentum():
    print("🚀 데일리 수집 봇 가동 시작...")
    today = datetime.today()
    base_date = today.strftime('%Y-%m-%d')
    
    # 1. 한국거래소 데이터 (현재 주식수 역산용)
    df_krx = fdr.StockListing('KOSPI')
    df_krx['Code'] = df_krx['Code'].astype(str).str.zfill(6)
    df_krx = df_krx[df_krx['Code'].str.endswith('0')].copy()
    
    # 시가총액 계산을 위한 발행주식수 근사치 딕셔너리
    shares_dict = {}
    for _, r in df_krx.iterrows():
        if r['Close'] > 0:
            shares_dict[r['Code']] = r['Marcap'] / r['Close']

    df_k200 = df_krx.sort_values('Marcap', ascending=False).head(200).copy()
    
    dates = {
        '1개월': get_end_of_month(today, 1),
        '3개월': get_end_of_month(today, 3),
        '6개월': get_end_of_month(today, 6),
        '12개월': get_end_of_month(today, 12)
    }
    start_date = dates['12개월'] - timedelta(days=15) 
    
    # ==========================================
    # [A] 데일리 실시간 파일 생성 (종가, 거래량, 시총 포함)
    # ==========================================
    records = []
    price_cache = {} 
    
    for idx, row in df_k200.iterrows():
        code = row['Code']
        try:
            df_hist = fdr.DataReader(code, start_date, today)
            if df_hist.empty: continue
            
            price_cache[code] = df_hist # 캐시 저장
            curr_price = df_hist['Close'].iloc[-1]
            curr_vol = df_hist['Volume'].iloc[-1] if 'Volume' in df_hist.columns else 0
            
            def get_ret(target_dt):
                past_df = df_hist[df_hist.index <= target_dt]
                if past_df.empty: return 0.0
                return round(((curr_price / past_df['Close'].iloc[-1]) - 1) * 100, 2)
            
            records.append({
                '종목코드': code, '종목명': row['Name'], '기준일': base_date,
                '시가총액': row['Marcap'], '종가': curr_price, '거래량': curr_vol,
                '1개월(%)': get_ret(dates['1개월']), '3개월(%)': get_ret(dates['3개월']),
                '6개월(%)': get_ret(dates['6개월']), '12개월(%)': get_ret(dates['12개월']),
                '이번달수익률': 0.0 
            })
        except: continue
            
    df_final = pd.DataFrame(records)
    os.makedirs('data', exist_ok=True)
    df_final.to_csv('data/momentum_data_daily.csv', index=False, encoding='utf-8-sig')
    print("🎉 데일리 데이터 업데이트 완료!")

    # ==========================================
    # [B] 최신 월간 파일 (선정일 종가/시총 보정 및 이번달 수익률 데일리 갱신)
    # ==========================================
    print("✅ 최신 월간 파일 '이번달수익률' 갱신 시작...")
    archive_files = sorted(glob.glob('archive_kospi/only_kospi_*.csv'))
    
    if archive_files:
        latest_file = archive_files[-1]
        df_latest = pd.read_csv(latest_file, dtype={'종목코드': str})
        df_latest['종목코드'] = df_latest['종목코드'].astype(str).str.zfill(6)
        
        if not df_latest.empty and '종목선정일' in df_latest.columns:
            base_date_m = df_latest['종목선정일'].iloc[0]
            base_dt = pd.to_datetime(base_date_m)
            
            for idx, row in df_latest.iterrows():
                code = row['종목코드']
                df_hist_m = price_cache.get(code, pd.DataFrame())
                
                if df_hist_m.empty:
                    try:
                        df_hist_m = fdr.DataReader(code, base_date_m, today)
                        time.sleep(0.1)
                    except: pass
                    
                if not df_hist_m.empty:
                    df_target = df_hist_m[df_hist_m.index >= base_dt]
                    if len(df_target) >= 1:
                        base_p = df_target['Close'].iloc[0] # 선정일 기준 종가
                        curr_p = df_target['Close'].iloc[-1] # 데일리 최신 종가
                        
                        if base_p > 0:
                            # 선정일 종가 및 시가총액 기록
                            df_latest.at[idx, '종가'] = base_p
                            shares = shares_dict.get(code, 0)
                            df_latest.at[idx, '시가총액'] = int(base_p * shares)
                            
                            # 💡 4월(이번 달) 수익률은 데일리 기준으로 덮어쓰기!
                            df_latest.at[idx, '이번달수익률'] = round(((curr_p / base_p) - 1) * 100, 2)
            
            df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
            print(f"🎉 {latest_file} 수익률 완벽 갱신 완료!")

if __name__ == "__main__":
    update_daily_momentum()
