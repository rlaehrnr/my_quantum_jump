import streamlit as st
import pandas as pd
import os
import glob

def get_folder_hash(folder_path):
    """폴더 내 모든 CSV 파일의 수정 시간을 합산하여 변경 여부를 확인하는 함수"""
    files = glob.glob(os.path.join(folder_path, "*.csv"))
    if not files:
        return 0
    # 모든 파일의 수정 시간(mtime)을 더해서 반환
    return sum(os.path.getmtime(f) for f in files)

@st.cache_data(ttl="1h") # 💡 1시간마다 혹은 파일 변경 시 자동으로 갱신
def load_archive_data(folder_path, folder_hash):
    """
    folder_hash가 인자로 들어가기 때문에, 
    파일 내용이 바뀌어 hash가 변하면 자동으로 캐시를 버리고 새로 로드합니다.
    """
    all_files = glob.glob(os.path.join(folder_path, "*.csv"))
    li = []
    for filename in all_files:
        try:
            df = pd.read_csv(filename, index_col=None, header=0, dtype={'종목코드': str})
            li.append(df)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            
    if not li:
        return pd.DataFrame()
        
    frame = pd.concat(li, axis=0, ignore_index=True)
    return frame
