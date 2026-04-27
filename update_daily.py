import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
import glob

def get_end_of_month(dt, months_ago):
    first_of_current = dt.replace(day=1)
    target_month = first_of_current - pd.DateOffset(months=months_ago - 1)
    return target_month - timedelta(days=1)

def update_daily_momentum():
    print("🚀 데일리 모멘텀 수집 봇 가동 시작...")
    today = datetime.today()
    base_date = today.strftime('%Y-%m-%d')
    print(f"✅ 데일리 기준일: {base_date}")

    # ==========================================
    # 1. 데일리 실시간 순위 데이터 생성
    # ==========================================
    print("✅ 거래소 데이터 다운로드 중...")
    df_krx = fdr.StockListing('KOSPI')
    
    # 우선주 제외
    df_krx['Code'] = df_krx['Code'].astype(str).str.zfill(6)
    df_krx = df_krx[df_krx['Code'].str.endswith('0')].copy()
    df_k200 = df_krx.sort_values('Marcap', ascending=False).head(200).copy()
    
    dates = {
        '1개월': get_end_of_month(today, 1),
        '3개월': get_end_of_month(today, 3),
        '6개월': get_end_of_month(today, 6),
        '12개월': get_end_of_month(today, 12)
    }
    
    start_date = dates['12개월'] - timedelta(days=15) 
    print(f"✅ 데일리 수익률 계산 중... (1M 기준: {dates['1개월'].strftime('%Y-%m-%d')})")
    
    records = []
    for idx, row in df_k200.iterrows():
        code = row['Code']
        try:
            df_hist = fdr.DataReader(code, start_date, today)
            if df_hist.empty: continue
            
            curr_price = df_hist['Close'].iloc[-1]
            def get_ret(target_dt):
                past_df = df_hist[df_hist.index <= target_dt]
                if past_df.empty: return 0.0
                return round(((curr_price / past_df['Close'].iloc[-1]) - 1) * 100, 2)
            
            records.append({
                '종목코드': code, '종목명': row['Name'], '시가총액': row['Marcap'], '기준일': base_date,
                '1개월(%)': get_ret(dates['1개월']), '3개월(%)': get_ret(dates['3개월']),
                '6개월(%)': get_ret(dates['6개월']), '12개월(%)': get_ret(dates['12개월']),
                '이번달수익률': 0.0 # 데일리는 진행 중이므로 0 고정
            })
        except: continue
            
    df_final = pd.DataFrame(records)
    os.makedirs('data', exist_ok=True)
    df_final.to_csv('data/momentum_data_daily.csv', index=False, encoding='utf-8-sig')
    print("🎉 데일리 데이터 업데이트 완료!")

    # ==========================================
    # 2. 💡 [새로운 기능] 최신 월간 백테스트 파일 업데이트
    # ==========================================
    print("✅ 최신 월간 파일(archive_kospi) '이번달수익률' 자동 갱신 시작...")
    archive_files = sorted(glob.glob('archive_kospi/only_kospi_*.csv'))
    
    if archive_files:
        latest_file = archive_files[-1] # 가장 최근 파일 (예: 2026_04.csv)
        print(f"📌 타겟 파일: {latest_file}")
        
        df_latest = pd.read_csv(latest_file, dtype={'종목코드': str})
        df_latest['종목코드'] = df_latest['종목코드'].astype(str).str.zfill(6)
        
        if not df_latest.empty and '종목선정일' in df_latest.columns:
            base_date_m = df_latest['종목선정일'].iloc[0]
            print(f"📌 종목선정일({base_date_m})부터 오늘까지의 수익률로 덮어쓰기 중...")
            
            for idx, row in df_latest.iterrows():
                code = row['종목코드']
                try:
                    df_hist_m = fdr.DataReader(code, base_date_m, today)
                    if not df_hist_m.empty and len(df_hist_m) >= 1:
                        base_p = df_hist_m['Close'].iloc[0] # 종목선정일 주가
                        curr_p = df_hist_m['Close'].iloc[-1] # 오늘 주가
                        if base_p > 0:
                            df_latest.at[idx, '이번달수익률'] = round(((curr_p / base_p) - 1) * 100, 2)
                except: pass
                    
            df_latest.to_csv(latest_file, index=False, encoding='utf-8-sig')
            print(f"🎉 {latest_file} 업데이트 완료! (웹페이지가 이제 빛의 속도로 켜집니다)")
    else:
        print("⚠️ archive_kospi 폴더에 업데이트할 파일이 없습니다.")

if __name__ == "__main__":
    update_daily_momentum()
