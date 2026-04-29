import streamlit as st
import pandas as pd
import os
import glob

def get_folder_hash(folder_path):
    """폴더 내 'only_'로 시작하는 정상 월간 파일들만 검사합니다."""
    files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    if not files:
        return 0
    return sum(os.path.getmtime(f) for f in files)

@st.cache_data(ttl="1h")
def load_archive_data(folder_path, folder_hash=None):
    # 💡 데일리 파일 등 엉뚱한 파일이 섞이는 것을 방지하기 위해 'only_*.csv'만 불러옵니다.
    all_files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    li = []
    
    for filename in all_files:
        try:
            df = pd.read_csv(filename, index_col=None, header=0, dtype={'종목코드': str})
            
            # 💡 치명적 에러 방지: 필수 컬럼인 '투자연도'가 존재하는 정상 파일만 합칩니다.
            if '투자연도' in df.columns:
                li.append(df)
            else:
                print(f"⚠️ 경고: {filename} 파일에 '투자연도' 컬럼이 없어 제외했습니다.")
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            
    if not li:
        return pd.DataFrame()
        
    frame = pd.concat(li, axis=0, ignore_index=True)
    return frame
