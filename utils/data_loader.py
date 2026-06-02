import streamlit as st
import pandas as pd
import os
import glob
import re

def get_folder_hash(folder_path):
    """폴더 내 'only_'로 시작하는 정상 월간 파일들만 검사."""
    files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    if not files:
        return 0
    return sum(os.path.getmtime(f) for f in files)


@st.cache_data(ttl="1h")
def load_archive_data(folder_path, folder_hash=None):
    """
    'only_*.csv' 파일들을 모두 읽어서 통합 DataFrame 반환.
    
    💡 [수정 사항]
    - 시총 단위 통일: 원 단위(매우 큰 수)면 자동으로 '억 원' 단위로 변환
    - 무결성 체크: 로드 후 1회 검증 (성능 영향 미미)
    """
    all_files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    li = []
    
    for filename in all_files:
        try:
            try:
                df = pd.read_csv(filename, index_col=None, header=0, 
                                dtype={'종목코드': str}, encoding='utf-8-sig')
            except UnicodeDecodeError:
                df = pd.read_csv(filename, index_col=None, header=0, 
                                dtype={'종목코드': str}, encoding='cp949')
            
            # 과거 파일에 '투자연도'/'투자월'이 없으면 파일명에서 추출
            if '투자연도' not in df.columns or '투자월' not in df.columns:
                basename = os.path.basename(filename)
                match = re.search(r'_(\d{4})_(\d{2})\.csv', basename)
                if match:
                    year, month = match.group(1), match.group(2)
                    df['투자연도'] = int(year)
                    df['투자월'] = f"{year}-{month}"
                else:
                    print(f"⚠️ 파일명 규칙 불일치, 건너뜀: {filename}")
                    continue
            
            li.append(df)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            
    if not li:
        return pd.DataFrame()
        
    frame = pd.concat(li, axis=0, ignore_index=True)
    
    # 💡 [11번 수정] 시총 단위 통일: 원 → 억 원
    # '시가총액' 컬럼이 원 단위(평균 1조 이상)면 1억으로 나눠서 '시가총액(억)'으로 변환
    if '시가총액' in frame.columns and '시가총액(억)' not in frame.columns:
        # 평균값이 1억(=100,000,000) 넘으면 원 단위로 판단
        mean_val = frame['시가총액'].dropna().mean()
        if pd.notna(mean_val) and mean_val > 100_000_000:
            frame['시가총액(억)'] = (frame['시가총액'] / 100_000_000).round(0)
        else:
            # 이미 억 단위인 경우 그대로 복사
            frame['시가총액(억)'] = frame['시가총액']
    
    # 💡 [10번] 무결성 체크 (로드 시 1회만, 결과는 print로)
    _validate_archive(frame)
    
    return frame


def _validate_archive(df):
    """
    데이터 무결성 검증. 비정상 상황을 콘솔에 경고로 출력.
    Streamlit 화면에는 영향 X. 성능 영향도 미미 (그룹별 size만 카운트).
    """
    if df.empty:
        return
    
    issues = []
    
    # 1. 각 투자월의 종목 수 체크
    for ym, group in df.groupby('투자월'):
        n = len(group)
        if n < 100:
            issues.append(f"  - {ym}: {n}개 (정상 약 200개)")
    
    # 2. 종목코드 NaN 체크
    null_code = df['종목코드'].isna().sum() if '종목코드' in df.columns else 0
    if null_code > 0:
        issues.append(f"  - 종목코드 NaN: {null_code}건")
    
    # 3. 수익률 NaN 비율 (전체 중)
    for col in ['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)']:
        if col in df.columns:
            nan_pct = df[col].isna().mean() * 100
            if nan_pct > 50:  # 절반 이상 NaN
                issues.append(f"  - {col} NaN 비율 {nan_pct:.1f}% (정상 약 25%)")
    
    if issues:
        print("⚠️ 데이터 무결성 경고:")
        for issue in issues:
            print(issue)
    else:
        print(f"✅ 데이터 검증 완료: {df['투자월'].nunique()}개월, {len(df)}행")



    # ==========================================
    # 💡 데일리 데이터: GitHub raw에서 직접 로드 (파일명 인자로 받음)
    # ==========================================
    DAILY_RAW_BASE = "https://raw.githubusercontent.com/<USER>/<REPO>/<BRANCH>/data/"
    
    @st.cache_data(ttl=600, show_spinner=False)  # 파일명별로 캐시 분리됨
    def load_daily_data(filename="momentum_data_daily.csv"):
        """1순위: GitHub raw(재배포 의존 X), 2순위: 로컬 폴백."""
        if "<USER>" not in DAILY_RAW_BASE:
            try:
                df = pd.read_csv(DAILY_RAW_BASE + filename, dtype={'종목코드': str})
                if not df.empty:
                    return df
            except Exception as e:
                print(f"⚠️ GitHub raw 로드 실패({filename}), 로컬 폴백: {e}")
        local_path = "data/" + filename
        if os.path.exists(local_path):
            return pd.read_csv(local_path, dtype={'종목코드': str})
        return pd.DataFrame()
