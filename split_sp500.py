import pandas as pd
import os

def split_sp500_data():
    # 1. 원본 파일 이름 (깃허브 최상위에 있는 파일명 그대로)
    file_path = 'sp500_퀀트데이터_2000_2025_Final_Cleaned_4.csv'
    
    # 2. 결과물을 저장할 폴더 생성
    output_dir = 'archive_sp500'
    os.makedirs(output_dir, exist_ok=True)

    print(f"🚀 데이터 읽는 중: {file_path}")
    
    try:
        df = pd.read_csv(file_path)
    except FileNotFoundError:
        print(f"🚨 에러: '{file_path}' 파일을 찾을 수 없습니다. 파일명이나 위치를 확인해주세요!")
        return

    # 3. 날짜 컬럼(Date)을 datetime 형식으로 변환하여 연-월(YYYY_MM) 문자열 추출
    # (예: '2023-05-31' -> '2023_05')
    df['Date'] = pd.to_datetime(df['Date'])
    df['YearMonth'] = df['Date'].dt.strftime('%Y_%m')

    # 4. 연-월 별로 그룹화하여 쪼개기
    grouped = df.groupby('YearMonth')
    
    count = 0
    for ym, group in grouped:
        # 분할용으로 만든 임시 컬럼은 다시 제거해줍니다
        save_df = group.drop(columns=['YearMonth'])
        
        # 파일명 지정 (한국 주식과 동일한 템플릿 적용: only_sp500_2023_05.csv)
        save_path = os.path.join(output_dir, f'only_sp500_{ym}.csv')
        
        # CSV로 저장 (인덱스 번호는 빼고 저장)
        save_df.to_csv(save_path, index=False, encoding='utf-8-sig')
        count += 1
        print(f"저장 완료: {save_path} ({len(save_df)}개 종목)")

    print(f"🎉 총 {count}개월 치의 S&P 500 데이터 분할 및 저장 완료!")
    print(f"이제 '{output_dir}' 폴더를 깃허브에 그대로 푸시(push)하시면 됩니다!")

if __name__ == "__main__":
    split_sp500_data()
