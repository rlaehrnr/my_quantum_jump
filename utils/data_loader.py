import pandas as pd
import glob
import os
import streamlit as st

@st.cache_data(show_spinner=False)
def load_archive_data(folder_path="archive_kospi"):
    """
    지정된 폴더에서 과거 월별 모멘텀 CSV 파일들을 모두 읽어와 하나의 데이터프레임으로 합칩니다.
    """
    files = glob.glob(f"{folder_path}/*.csv")
    if not files: 
        return pd.DataFrame()
        
    dfs = []
    for f in files:
        # utf-8-sig로 읽어서 한글 깨짐 원천 방지
        df = pd.read_csv(f, encoding='utf-8-sig', dtype={'종목코드': str})
        df.columns = df.columns.str.replace(' ', '')
        
        # 💡 [핵심] 골든 룰 자동 변환 (과거 데이터 호환성 유지)
        rename_dict = {}
        if '기준일(월말)' in df.columns: rename_dict['기준일(월말)'] = '종목선정일'
        elif '기준일' in df.columns: rename_dict['기준일'] = '종목선정일'
        if '다음달수익률(%)' in df.columns: rename_dict['다음달수익률(%)'] = '이번달수익률'
        if rename_dict:
            df.rename(columns=rename_dict, inplace=True)
            
        if '종목코드' in df.columns:
            df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
            
        # 파일명에서 투자월, 투자연도 추출 (예: momentum_kospi_2026_03.csv)
        fname = os.path.basename(f)
        try:
            parts = fname.replace(".csv", "").split("_")
            year = parts[-2]
            month = parts[-1]
            df['투자월'] = f"{year}-{month}"
            df['투자연도'] = int(year)
        except Exception as e:
            pass # 파일명 규칙이 다를 경우 패스
            
        # 숫자형 변환 안전 처리
        for c in ['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
                
        dfs.append(df)
        
    if not dfs: return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)
