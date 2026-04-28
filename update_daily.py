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

# 💡 [핵심 수정] 수익률 계산 로직을 하나로 통일 (가장 가까운 과거 종가 기준)
def calculate_return_unified(df_hist, target_date, current_price):
    try:
        # target_date(예: 3월 31일) 혹은 그 직전의 가장 가까운 종가를 찾습니다.
        past_df = df_hist[df_hist.index <= pd.to_datetime(target_date)]
        if past_df.empty: return 0.0
        base_price = past_df['Close'].iloc[-1]
        if base_price <= 0: return 0.0
        return round(((current_price / base_price) - 1) * 100, 2)
    except:
        return 0.0

def update_daily_momentum():
    print("🚀 수익률 동기화 봇 가동 시작...")
    today = datetime.today()
    base_date = today.strftime('%Y-%m-%d')
    
    # 1. 기초 데이터 로드
    df_krx = fdr.StockListing('KOSPI')
    df_krx['Code'] = df_krx['Code'].astype(str).str.zfill(6)
    df_krx = df_krx[df_krx['Code'].str.endswith('0')].copy()
    
    shares_dict = {row['Code']: row['Marcap']/row['Close'] for _, row in df_krx.iterrows() if row['Close'] > 0}
    df_k200 = df_krx.sort_values('Marcap', ascending=False).head(200).copy()
    
    # 기준일 설정 (이번 달 수익률의 기준인 전월 말일)
    last_month_end = get_end_of_month(today, 1) # 3월 31일
    
    dates = {
        '1개월': last_month_end,
        '3개월': get_end_of_month(today, 3),
        '6개월': get_end_of_month(today, 6),
        '12개월': get_end_of_month(today, 12)
    }
    start_date = dates['12개월'] - timedelta(days=15) 
    
    records, price_cache = [], {}
    
    # ==========================================
    # [A] 데일리 데이터 수집
    # ==========================================
    for idx, row in df_k200.iterrows():
        code = row['Code']
        try:
            df_hist = fdr.DataReader(code, start_date, today)
            if df_hist.empty: continue
            price_cache[code] = df_hist
            curr_price = df_hist['Close'].iloc[-1]
            curr_vol = df_hist['Volume'].iloc[-1] if 'Volume' in df_hist.columns else 0
            
            records.append({
                '종목코드': code, '종목명': row['Name'], '기준일': base_date,
                '시가총액': row['Marcap'], '종가': curr_price, '거래량': curr_vol,
                '1개월(%)': calculate_return_unified(df_hist, dates['1개월'], curr_price),
                '3개월(%)': calculate_return_unified(df_hist, dates['3개월'], curr_price),
                '6개월(%)': calculate_return_unified(df_hist, dates['6개월'], curr_price),
                '12개월(%)': calculate_return_unified(df_hist, dates['12개월'], curr_price)
            })
        except: continue
            
    df_final = pd.DataFrame(records)
    os.makedirs('data', exist_ok=True)
    df_final.to_csv('data/momentum_data_daily.csv', index=False, encoding='utf-8-sig')

    # ==========================================
    # [B] 월간 파일 '이번달수익률' 동기화 (데일리와 동일 로직 적용)
    # ==========================================
    archive_files = sorted(glob.glob('archive_kospi/only_kospi_*.csv'))
    if archive_files:
        latest_file = archive_files[-1]
        df_latest = pd.read_csv(latest_file, dtype={'종목코드': str})
        df_latest['종목코드'] = df_latest['종목코드'].astype(str).str.zfill(6)
        
        if '종목선정일' in df_latest.columns:
            # CSV 파일에 적힌 실제 선정일 (예: 2026-03-31)
            csv_base_date = df_latest['종목선정일'].iloc[0]
            print(f"📌 {latest_file} 파일을 선정일 {csv_base_date} 기준으로 동기화합니다.")
            
            for idx, row in df_latest.iterrows():
                code = row['종목코드']
                df_h = price_cache.get(code, pd.DataFrame())
                if df_h.empty:
                    try: df_h = fdr.DataReader(code, csv_base_date, today)
                    except: pass
                
                if not df_h.empty:
                    curr_p = df_h['Close'].iloc[-1]
                    # 💡 데일리 탭과 100% 동일한 함수를 사용하여 '이번달수익률' 갱신
                    sync_ret = calculate_return_unified(df_h, csv_base_date, curr_p)
                    df_latest.at[idx, '이번달수익률'] = sync_ret
                    
                    # 시총/종가도 선정일 당시의 데이터로 보정
                    past_df = df_h[df_h.index <= pd.to_datetime(csv_base_date)]
                    if not past_df.empty:
                        bp = past_df['Close'].iloc[-1]
                        df_latest.at[idx, '종가'] = bp
                        df_latest.at[idx, '시가총액'] = int(bp * shares_dict.get(code, 0))
            
            df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
            print(f"🎉 동기화 완료: 대우건설 수익률이 이제 일치할 것입니다.")

if __name__ == "__main__":
    update_daily_momentum()
