import pandas as pd
import os

def split_korea_data():
    print("🚀 데이터 분할 봇 가동 시작...")
    
    # 1. 파일 불러오기 (인코딩 자동 감지)
    file_path = '코스닥피_2015_2026.csv'
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig', dtype={'종목코드': str})
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding='cp949', dtype={'종목코드': str})
        
    # 2. 필수 컬럼 정리
    df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
    
    # 앱에서 '종가' 컬럼을 사용하므로, 만약 '기준가'로 되어 있다면 이름 변경
    if '기준가' in df.columns:
        df.rename(columns={'기준가': '종가'}, inplace=True)

    # 3. 폴더 생성
    output_dir = 'archive_korea'
    os.makedirs(output_dir, exist_ok=True)

    # 4. 선정일 기준으로 월별 쪼개기
    # 예: 선정일이 2015-01-30 이면 투자 시작월은 2015년 2월(2015_02)
    grouped = df.groupby('종목선정일')
    
    for base_date, group in grouped:
        dt = pd.to_datetime(base_date)
        
        # 다음 달을 '투자월'로 계산
        invest_month = dt + pd.DateOffset(months=1)
        year = invest_month.year
        month_str = invest_month.strftime('%Y-%m')
        file_suffix = invest_month.strftime('%Y_%m')
        
        # 데이터프레임에 투자연도/투자월 기둥 세우기
        month_df = group.copy()
        month_df['투자연도'] = year
        month_df['투자월'] = month_str
        
        # 파일 저장
        file_name = f"only_korea_{file_suffix}.csv"
        file_path = os.path.join(output_dir, file_name)
        
        month_df.to_csv(file_path, index=False, encoding='utf-8-sig')
        print(f"✅ {file_name} 저장 완료 (종목수: {len(month_df)})")
        
    print("🎉 모든 데이터가 성공적으로 쪼개져 archive_korea 폴더에 저장되었습니다!")

if __name__ == "__main__":
    split_korea_data()
