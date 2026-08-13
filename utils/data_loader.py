import streamlit as st
import pandas as pd
import os
import glob

from utils import archive_store

def get_folder_hash(folder_path):
    """폴더 내 'only_'로 시작하는 정상 월간 파일들만 검사."""
    files = glob.glob(os.path.join(folder_path, "only_*.csv"))
    if not files:
        return 0
    return sum(os.path.getmtime(f) for f in files)


@st.cache_data(max_entries=4)
def load_archive_data(folder_path, folder_hash=None):
    """
    'only_*.csv' 파일들을 모두 읽어서 통합 DataFrame 반환.

    💡 [수정 사항]
    - 시총 단위 통일: 원 단위(매우 큰 수)면 자동으로 '억 원' 단위로 변환
    - 무결성 체크: 로드 후 1회 검증 (성능 영향 미미)

    ⚠️ ttl을 두지 않는다. 무효화는 folder_hash가 이미 담당한다 —
       인자로 받은 폴더 mtime 합이 바뀌면 캐시 키가 바뀌어 자동으로 다시 읽는다.
       ttl="1h"는 그 위에 얹힌 중복이었다 (archive_usa 기준 CSV 332개 · 약 1.4초).
       max_entries는 해시가 바뀔 때 옛 항목이 쌓이지 않도록 하는 상한이다
       (라이브가 쓰는 폴더는 archive_kospi · archive_usa 2개).

    💡 실제 파일 읽기는 utils/archive_store.py 가 한다. 거기서 '확정된 지난 달'
       합본(parquet)이 있으면 그걸 쓰고 최신월 CSV만 따로 읽는다. 합본이 없거나
       어긋나면 예전처럼 CSV를 전부 읽는다 — 어느 쪽이든 결과는 같다.
    """
    frame = archive_store.load_frames(folder_path)

    if frame.empty:
        return pd.DataFrame()

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
# Streamlit Cloud 재배포(reboot) 여부와 무관하게 항상 최신본을 가져온다.
# GitHub Actions가 커밋하면 raw URL에는 최대 5분 내 반영됨.
# ==========================================
DAILY_RAW_BASE = "https://raw.githubusercontent.com/<USER>/<REPO>/<BRANCH>/data/"


@st.cache_data(ttl=600, show_spinner=False)  # 파일명별로 캐시 분리됨
def load_daily_data(filename="momentum_data_daily.csv"):
    """
    데일리 모멘텀 CSV 로드.
    1순위: GitHub raw URL에서 직접 (재배포 의존 X → 자동 갱신)
    2순위: 실패 시 로컬 파일 폴백
    """
    # GitHub raw 시도 (URL이 실제 값으로 채워진 경우에만)
    if "<USER>" not in DAILY_RAW_BASE:
        try:
            df = pd.read_csv(DAILY_RAW_BASE + filename, dtype={'종목코드': str})
            if not df.empty:
                return df
        except Exception as e:
            print(f"⚠️ GitHub raw 로드 실패({filename}), 로컬 폴백: {e}")

    # 로컬 폴백
    local_path = "data/" + filename
    if os.path.exists(local_path):
        try:
            df = pd.read_csv(local_path, dtype={'종목코드': str})
            if not df.empty:
                return df
        except pd.errors.EmptyDataError:
            print(f"⚠️ {local_path} 비어있음(EmptyDataError)")

    return pd.DataFrame()
