import pandas as pd
import os
from datetime import timedelta

def split_kospi_data(file_path):
    print(f"데이터를 읽는 중입니다: {file_path}")
    
    # 1. 파일 읽기 (인코딩 처리)
    try:
        df = pd.read_csv(file_path, encoding='cp949')
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding='utf-8-sig')

    # (선택) 쓸데없는 빈 컬럼(Unnamed)이 섞여있다면 제거
    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

    # 2. 종목코드 6자리 맞추기 (예: 5930.0 -> '005930')
    # 소수점이 섞여 있을 수 있으므로 문자로 바꾸고 '.' 앞부분만 쓴 뒤 앞을 0으로 채움
    df['종목코드'] = df['종목코드'].apply(lambda x: str(x).split('.')[0] if pd.notnull(x) else '').str.zfill(6)

    # 3. 컬럼명 변경 (Golden Rule 적용)
    rename_dict = {
        '기준일': '종목선정일',
        '다음달수익률(%)': '이번달수익률'
    }
    df.rename(columns=rename_dict, inplace=True)

    # 4. 날짜 그룹핑을 위해 datetime 변환
    df['종목선정일_dt'] = pd.to_datetime(df['종목선정일'])

    # 5. 저장할 폴더 만들기
    output_folder = 'archive_kospi'
    os.makedirs(output_folder, exist_ok=True)

    # 6. 날짜(종목선정일)별로 쪼개서 저장
    generated_count = 0
    for date, group in df.groupby('종목선정일_dt'):
        # 파일명은 '다음 달' 기준 (예: 2014-01-29 -> 2014년 2월)
        next_month = date + pd.DateOffset(months=1)
        year_str = next_month.strftime('%Y')
        month_str = next_month.strftime('%m')
        
        # 저장할 때는 연산용 날짜 컬럼(dt) 삭제
        group_to_save = group.drop(columns=['종목선정일_dt'])
        
        # 파일 이름 규칙 적용 (only_kospi_YYYY_MM.csv)
        filename = f"{output_folder}/only_kospi_{year_str}_{month_str}.csv"
        
        # 엑셀에서 한글이 깨지지 않도록 utf-8-sig로 저장
        group_to_save.to_csv(filename, index=False, encoding='utf-8-sig')
        generated_count += 1

    print(f"🎉 작업 완료! 총 {generated_count}개의 파일이 '{output_folder}' 폴더에 생성되었습니다.")

# 실행
if __name__ == "__main__":
    # 다운로드하신 파일 이름과 정확히 일치하게 적어주세요.
    split_kospi_data("한국 코스피 2014년부터 200위까지 자료.csv")
