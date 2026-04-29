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
    all_files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    li = []
    
    for filename in all_files:
        try:
            # 💡 [핵심 수정] encoding='utf-8-sig' 추가하여 눈에 안보이는 특수문자 제거
            df = pd.read_csv(filename, index_col=None, header=0, dtype={'종목코드': str}, encoding='utf-8-sig')
            
            if '투자연도' in df.columns:
                li.append(df)
            else:
                print(f"⚠️ 경고: {filename} 파일에 '투자연도' 컬럼이 없습니다. (현재 컬럼: {df.columns})")
        except Exception as e:
            # 💡 간혹 cp949(한국어 윈도우 기본)로 저장된 파일이 섞여있을 경우를 대비한 2차 안전장치
            try:
                df = pd.read_csv(filename, index_col=None, header=0, dtype={'종목코드': str}, encoding='cp949')
                if '투자연도' in df.columns:
                    li.append(df)
            except Exception as e2:
                print(f"Error loading {filename}: {e2}")
            
    if not li:
        return pd.DataFrame()
        
    frame = pd.concat(li, axis=0, ignore_index=True)
    return frame
