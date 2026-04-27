import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os

def update_daily_momentum():
    print("🚀 데일리 모멘텀 수집 봇 가동 시작...")
    
    # 1. 오늘 날짜 및 기준일 세팅
    today = datetime.today()
    base_date = today.strftime('%Y-%m-%d')
    print(f"✅ 기준일: {base_date}")

    # 2. 한국 주식 전체 종목(KOSPI) 시가총액 순으로 불러오기
    print("✅ 거래소 데이터(시가총액 순) 다운로드 중...")
    df_krx = fdr.StockListing('KOSPI')
    
    # 시가총액 상위 200개 종목 필터링 (KOSPI 200 근사치)
    df_k200 = df_krx.sort_values('Marcap', ascending=False).head(200).copy()
    
    # 3. 과거 날짜 계산
    dates = {
        '1개월': today - pd.DateOffset(months=1),
        '3개월': today - pd.DateOffset(months=3),
        '6개월': today - pd.DateOffset(months=6),
        '12개월': today - pd.DateOffset(months=12)
    }
    
    # 4. 과거 주가 일괄 다운로드 (1년치)
    start_date = dates['12개월'] - timedelta(days=10) # 여유 있게
    print("✅ 과거 1년치 주가 데이터 다운로드 중... (약 10~30초 소요)")
    tickers = df_k200['Code'].tolist()
    
    # yfinance나 fdr로 여러 종목 주가를 한방에 가져오기가 무거우므로,
    # 개별 종목별로 모멘텀 수익률 계산
    records = []
    
    for idx, row in df_k200.iterrows():
        code = row['Code']
        name = row['Name']
        marcap = row['Marcap']
        
        try:
            df_hist = fdr.DataReader(code, start_date, today)
            if df_hist.empty: continue
            
            curr_price = df_hist['Close'].iloc[-1]
            
            # 수익률 계산 함수 (해당 날짜와 가장 가까운 과거 영업일 종가 기준)
            def get_ret(target_dt):
                past_df = df_hist[df_hist.index <= target_dt]
                if past_df.empty: return 0.0
                past_price = past_df['Close'].iloc[-1]
                return round(((curr_price / past_price) - 1) * 100, 2)
            
            records.append({
                '종목코드': code,
                '종목명': name,
                '시가총액': marcap,
                '기준일': base_date,
                '1개월(%)': get_ret(dates['1개월']),
                '3개월(%)': get_ret(dates['3개월']),
                '6개월(%)': get_ret(dates['6개월']),
                '12개월(%)': get_ret(dates['12개월']),
                '이번달수익률': 0.0 # 데일리는 아직 월말이 아니므로 0
            })
            
        except Exception as e:
            continue
            
    # 5. 데이터프레임 정리 및 저장
    df_final = pd.DataFrame(records)
    
    # 모멘텀 스코어 (단순 합산 예시)
    df_final['모멘텀스코어'] = df_final['1개월(%)'] + df_final['3개월(%)'] + df_final['6개월(%)'] + df_final['12개월(%)']
    
    os.makedirs('data', exist_ok=True)
    df_final.to_csv('data/momentum_data_daily.csv', index=False, encoding='utf-8-sig')
    print("🎉 데일리 데이터 업데이트 완료! (data/momentum_data_daily.csv)")

if __name__ == "__main__":
    update_daily_momentum()
