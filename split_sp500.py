import pandas as pd
import os

def split_sp500_data():
    # 1. 원본 파일 이름 (가장 최신 파일명으로 반영)
    file_path = 'sp500_퀀트데이터_2000_2025_Final_Cleaned.csv'
    
    output_dir = 'archive_sp500'
    os.makedirs(output_dir, exist_ok=True)

    print(f"🚀 데이터 읽는 중: {file_path}")
    
    try:
        df = pd.read_csv(file_path)
    except FileNotFoundError:
        print(f"🚨 에러: '{file_path}' 파일을 찾을 수 없습니다. 파일명이나 위치를 확인해주세요!")
        return

    # 2. 날짜 컬럼(Date)을 datetime 형식으로 변환
    df['Date'] = pd.to_datetime(df['Date'])
    
    # 💡 [핵심 수정] 선정일 기준 익월(다음 달)을 투자월로 지정
    # 예: 2026-03-31 -> 2026_04
    # 월말 날짜에 15일 정도를 더해서 무조건 다음 달로 넘어가게 한 뒤 연_월 추출
    df['TargetMonth'] = (df['Date'] + pd.Timedelta(days=15)).dt.strftime('%Y_%m')

    # 3. 타겟월(익월) 별로 그룹화하여 쪼개기
    grouped = df.groupby('TargetMonth')
    
    count = 0
    for ym, group in grouped:
        # 분할용으로 만든 임시 컬럼은 다시 제거해줍니다
        save_df = group.drop(columns=['TargetMonth'])
        
        # 파일명 지정 (투자월 기준으로 저장: only_sp500_2026_04.csv)
        save_path = os.path.join(output_dir, f'only_sp500_{ym}.csv')
        
        # CSV로 저장 (인덱스 번호는 빼고 저장)
        save_df.to_csv(save_path, index=False, encoding='utf-8-sig')
        count += 1
        print(f"저장 완료: {save_path} ({len(save_df)}개 종목)")

    print(f"🎉 총 {count}개월 치의 S&P 500 데이터 분할 및 저장 완료!")
    print(f"이제 터미널에서 'git add .', 'git commit', 'git push'를 순서대로 진행해주세요!")

if __name__ == "__main__":
    split_sp500_data()
