import streamlit as st
import pandas as pd
import os
import glob
import re

def get_folder_hash(folder_path):
    """폴더 내 'only_'로 시작하는 정상 월간 파일들만 검사합니다."""
    files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    if not files:
        return 0
    return sum(os.path.getmtime(f) for f in files)

@st.cache_data(ttl="1h")
def load_archive_data(folder_path, folder_hash=None):
    all_files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    li = []
    
    for filename in all_files:
        try:
            try:
                df = pd.read_csv(filename, index_col=None, header=0, dtype={'종목코드': str}, encoding='utf-8-sig')
            except:
                df = pd.read_csv(filename, index_col=None, header=0, dtype={'종목코드': str}, encoding='cp949')
            
            # 💡 [핵심 패치] 과거 파일에 '투자연도'가 없으면 파일명에서 빼옵니다!
            if '투자연도' not in df.columns or '투자월' not in df.columns:
                basename = os.path.basename(filename) # 예: only_kospi_2023_11.csv
                match = re.search(r'_(\d{4})_(\d{2})\.csv', basename)
                
                if match:
                    year = match.group(1)
                    month = match.group(2)
                    df['투자연도'] = int(year)
                    df['투자월'] = f"{year}-{month}"
                else:
                    print(f"⚠️ 파일명 규칙이 맞지 않아 건너뜁니다: {filename}")
                    continue
            
            li.append(df)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            
    if not li:
        return pd.DataFrame()
        
    frame = pd.concat(li, axis=0, ignore_index=True)
    return frame
