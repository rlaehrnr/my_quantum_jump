import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_end_of_month(dt, months_ago):
    first_of_current = dt.replace(day=1)
    target_month = first_of_current - pd.DateOffset(months=months_ago - 1)
    return target_month - pd.Timedelta(days=1)

def calculate_past_return(df_hist, target_date, base_price):
    try:
        past_df = df_hist[df_hist.index <= pd.to_datetime(target_date)]
        if past_df.empty or base_price <= 0: return 0.0
        base_val = past_df['Close'].iloc[-1]
        return round(((base_price / base_val) - 1) * 100, 2)
    except:
        return 0.0

# 💡 [핵심 복구] 선생님의 오리지널 시가총액 추출 로직을 USA300에 맞게 부활시켰습니다!
def get_top_us_stocks(market, limit=150):
    print(f"📥 {market} 시장 데이터 로드 중...")
    try:
        df = fdr.StockListing(market)
        if df.empty: return pd.DataFrame()
        
        # 시가총액 컬럼 동적 탐색
        cap_col = [c for c in df.columns if '시가총액' in c or ('mar' in c.lower() and 'cap' in c.lower())]
        if not cap_col: return pd.DataFrame()
        
        target_col = cap_col[0]
        # 숫자형 변환 및 정렬
        df['시가총액_raw'] = pd.to_numeric(df[target_col].astype(str).str.replace(',', '').str.replace('.0', '', regex=False), errors='coerce')
        df = df.dropna(subset=['시가총액_raw'])
        df_top = df.sort_values('시가총액_raw', ascending=False).head(limit).copy()
        
        # 컬럼명 표준화
        code_col = 'Code' if 'Code' in df_top.columns else 'Symbol'
        name_col = 'Name' if 'Name' in df_top.columns else 'Company'
        
        df_top = df_top.rename(columns={code_col: '종목코드', name_col: '종목명'})
        df_top['시장'] = market
        df_top['종목코드'] = df_top['종목코드'].astype(str).str.replace('.', '-', regex=False)
        
        return df_top[['종목코드', '종목명', '시장', '시가총액_raw']]
    except Exception as e:
        print(f"🚨 {market} 종목 로드 실패: {e}")
        return pd.DataFrame()

def process_monthly_ticker_us(row, start_date, base_date, dates, base_date_str):
    code = str(row['종목코드']).strip()
    name = row['종목명']
    market = row['시장']
    marcap = row['시가총액_raw']
    
    try:
        df_hist = fdr.DataReader(code, start_date, base_date)
        if df_hist.empty: return None
        if df_hist.index.tz is not None: df_hist.index = df_hist.index.tz_localize(None)
        
        base_price = df_hist['Close'].iloc[-1]
        
        ret_1m = calculate_past_return(df_hist, dates[1], base_price)
        ret_3m = calculate_past_return(df_hist, dates[3], base_price)
        ret_6m = calculate_past_return(df_hist, dates[6], base_price)
        ret_12m = calculate_past_return(df_hist, dates[12], base_price)
        
        return {
            '종목선정일': base_date_str,
            '시장': market,
            '종목명': name,
            '종목코드': code,
            '시가총액': marcap, 
            '종가': base_price,
            '1개월(%)': ret_1m,
            '3개월(%)': ret_3m,
            '6개월(%)': ret_6m,
            '12개월(%)': ret_12m,
            '이번달수익률': 0.0 # 데일리가 나중에 채워줍니다.
        }
    except: return None

def main():
    archive_folder = 'archive_usa'
    os.makedirs(archive_folder, exist_ok=True)
    
    # 1. 유니버스 생성: 나스닥 상위 150 + 뉴욕 상위 150
    print("📌 USA 300 유니버스(NASDAQ 150 + NYSE 150) 실시간 추출 시작...")
    df_ndq = get_top_us_stocks('NASDAQ', 150)
    df_nyse = get_top_us_stocks('NYSE', 150)
    
    universe = pd.concat([df_ndq, df_nyse]).drop_duplicates(subset=['종목코드'])
    if universe.empty:
        print("🚨 유니버스 추출에 실패했습니다.")
        return
        
    print(f"✅ 총 {len(universe)}개 유니버스 구성 완료.")

    # 2. 이번 달을 계산하기 위한 기준일 세팅 (보통 전월 말일)
    today = datetime.today()
    base_date = get_end_of_month(today, 1)
    base_date_str = base_date.strftime('%Y-%m-%d')
    invest_year = base_date.year
    invest_month_str = f"{invest_year}-{base_date.month:02d}"
    
    dates = {
        1: get_end_of_month(base_date, 1),
        3: get_end_of_month(base_date, 3),
        6: get_end_of_month(base_date, 6),
        12: get_end_of_month(base_date, 12)
    }
    start_date = get_end_of_month(base_date, 13)
    
    print(f"📊 {invest_month_str} (기준일: {base_date_str}) 모멘텀 계산 시작...")
    
    results = []
    # 3. 쓰레드풀을 이용한 고속 백그라운드 데이터 다운로드 및 계산
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_monthly_ticker_us, row, start_date, base_date, dates, base_date_str) for _, row in universe.iterrows()]
        for future in as_completed(futures):
            res = future.result()
            if res: results.append(res)
            
    if results:
        df_res = pd.DataFrame(results)
        # 파일명은 usa300_2026_05.csv 형태로 저장됩니다.
        output_filename = f"{archive_folder}/usa300_{invest_year}_{base_date.month:02d}.csv"
        df_res.to_csv(output_filename, index=False, encoding='utf-8-sig')
        print(f"🎉 성공! 새로운 유니버스가 반영된 월간 데이터 저장 완료: {output_filename}")
    else:
        print("🚨 데이터 수집 실패")

if __name__ == "__main__":
    main()
