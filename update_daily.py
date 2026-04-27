import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os

# 💡 [핵심 1] 오늘 날짜를 기준으로, N개월 전의 "말일"을 정확히 계산하는 함수
def get_end_of_month(dt, months_ago):
    # 예: 오늘이 4월 27일이면 -> 이번 달 1일(4월 1일)로 변경
    first_of_current = dt.replace(day=1)
    # 거기서 (N-1)개월을 뺌 (1개월 전이면 4월 1일 그대로 유지)
    target_month = first_of_current - pd.DateOffset(months=months_ago - 1)
    # 거기서 하루를 빼면 무조건 이전 달의 말일이 됨 (4월 1일 - 1일 = 3월 31일)
    return target_month - timedelta(days=1)

def update_daily_momentum():
    print("🚀 데일리 모멘텀 수집 봇 가동 시작...")
    
    # 1. 오늘 날짜 및 기준일 세팅
    today = datetime.today()
    base_date = today.strftime('%Y-%m-%d')
    print(f"✅ 데일리 기준일: {base_date}")

    # 2. 한국 주식 전체 종목(KOSPI) 시가총액 순으로 불러오기
    print("✅ 거래소 데이터 다운로드 중...")
    df_krx = fdr.StockListing('KOSPI')
    
    # 💡 [핵심 2] 우선주 제외 로직 (종목코드 끝자리가 '0'인 종목만 남김)
    df_krx['Code'] = df_krx['Code'].astype(str).str.zfill(6)
    df_krx = df_krx[df_krx['Code'].str.endswith('0')].copy()
    
    # 시가총액 상위 200개 종목 필터링 (KOSPI 200 근사치)
    df_k200 = df_krx.sort_values('Marcap', ascending=False).head(200).copy()
    
    # 3. 과거 월말 날짜 세팅 (1, 3, 6, 12개월 전 말일)
    dates = {
        '1개월': get_end_of_month(today, 1),
        '3개월': get_end_of_month(today, 3),
        '6개월': get_end_of_month(today, 6),
        '12개월': get_end_of_month(today, 12)
    }
    
    print(f"📌 [적용된 수익률 기준일] 1M: {dates['1개월'].strftime('%Y-%m-%d')}, 3M: {dates['3개월'].strftime('%Y-%m-%d')}")
    
    # 4. 과거 주가 일괄 다운로드 (1년치 + 여유분)
    start_date = dates['12개월'] - timedelta(days=15) 
    print("✅ 과거 주가 데이터 다운로드 및 수익률 계산 중... (약 10~30초 소요)")
    
    records = []
    
    for idx, row in df_k200.iterrows():
        code = row['Code']
        name = row['Name']
        marcap = row['Marcap']
        
        try:
            df_hist = fdr.DataReader(code, start_date, today)
            if df_hist.empty: continue
            
            curr_price = df_hist['Close'].iloc[-1]
            
            # 수익률 계산 함수 (타겟 날짜와 가장 가까운 '과거 영업일 종가' 기준)
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
                '이번달수익률': 0.0 # 데일리는 아직 월말이 아니므로 0 고정
            })
            
        except Exception as e:
            continue
            
    # 5. 데이터프레임 정리 및 저장
    df_final = pd.DataFrame(records)
    
    # 모멘텀 스코어 (단순 합산 - 필요 시 사용)
    df_final['모멘텀스코어'] = df_final['1개월(%)'] + df_final['3개월(%)'] + df_final['6개월(%)'] + df_final['12개월(%)']
    
    os.makedirs('data', exist_ok=True)
    df_final.to_csv('data/momentum_data_daily.csv', index=False, encoding='utf-8-sig')
    print("🎉 데일리 데이터 업데이트 완료! (data/momentum_data_daily.csv)")

if __name__ == "__main__":
    update_daily_momentum()
