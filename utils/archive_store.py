"""archive_* 폴더의 월별 CSV를 읽고, '확정분 합본(parquet)'을 만들고 쓰는 곳.

왜 있나
------
archive_usa 는 월별 CSV가 332개다. 전부 읽는 데 약 1.4초가 걸리는데, 파일마다
열기·헤더 파싱·자료형 추론·인코딩 재시도가 붙기 때문이다. 앱이 재시작될 때마다
이 비용을 낸다.

합본을 '전부'가 아니라 '지난 달까지'만 담는 이유
-----------------------------------------------
아카이브는 월 1회만 바뀌지 않는다. 데일리 로봇이 **최신월 파일 하나**의
'이번달수익률'을 매일 다시 쓴다 (update_daily_us.py · update_daily_kr.py).
그래서 전체 합본을 커밋하면 매일 통째로 다시 커밋되어 레포가 급격히 불어난다.

지난 달들은 확정돼 다시 바뀌지 않는다. 그래서
    합본(parquet) = 지난 달 전부  +  최신월 CSV 1개
로 나눠 읽는다. 합본은 '새 달이 시작될 때'만 바뀌므로 git 증가가 월 단위로 묶인다.
(실측: 한 달 추가 시 .git 증가 — parquet 28KB / 단일 CSV 1,320KB)

안전장치
--------
합본이 없거나, 깨졌거나, 지난 달 파일 목록과 어긋나면 **조용히 예전 방식으로**
CSV를 전부 읽는다. 최악의 경우가 '지금과 동일'이라 새로 생기는 위험이 없다.

streamlit을 임포트하지 않는다 — 갱신 로봇의 워크플로는 pandas·finance-datareader·
requests·pyarrow만 설치하기 때문이다. 캐시는 이 모듈을 쓰는 data_loader 쪽에 있다.
"""

import os
import re
import glob
import json

import pandas as pd

HISTORY_PARQUET = "_history.parquet"
HISTORY_MANIFEST = "_history.json"

_MONTH_RE = re.compile(r'_(\d{4})_(\d{2})\.csv$')


def archive_csvs(folder_path):
    """폴더의 월별 CSV를 시간순으로. 파일명이 YYYY_MM 으로 끝나 정렬=시간순이다."""
    return sorted(glob.glob(os.path.join(folder_path, "only_*.csv")))


def _month_key(path):
    m = _MONTH_RE.search(os.path.basename(path))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _manifest_of(files):
    """합본이 어떤 파일들로 만들어졌는지 기록. 파일명 + 바이트 크기.

    mtime은 쓰지 않는다 — git clone 할 때마다 바뀌어서 배포 직후 항상 어긋난다.
    크기까지 보면 지난 달 파일이 뒤늦게 수정된 경우도 잡힌다.
    """
    return {os.path.basename(f): os.path.getsize(f) for f in files}


def _read_one(filename):
    """CSV 1개를 읽고 투자연도·투자월을 보정. 규칙에 안 맞으면 None."""
    try:
        df = pd.read_csv(filename, index_col=None, header=0,
                         dtype={'종목코드': str}, encoding='utf-8-sig')
    except UnicodeDecodeError:
        df = pd.read_csv(filename, index_col=None, header=0,
                         dtype={'종목코드': str}, encoding='cp949')

    # 과거 파일에 '투자연도'/'투자월'이 없으면 파일명에서 추출
    if '투자연도' not in df.columns or '투자월' not in df.columns:
        match = _MONTH_RE.search(os.path.basename(filename))
        if not match:
            print(f"⚠️ 파일명 규칙 불일치, 건너뜀: {filename}")
            return None
        year, month = match.group(1), match.group(2)
        df['투자연도'] = int(year)
        df['투자월'] = f"{year}-{month}"
    return df


def read_csv_frames(files):
    """주어진 CSV들을 읽어 순서대로 이어붙인다. 실패한 파일은 건너뛴다."""
    li = []
    for filename in files:
        try:
            df = _read_one(filename)
            if df is not None:
                li.append(df)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
    if not li:
        return pd.DataFrame()
    return pd.concat(li, axis=0, ignore_index=True)


def build_history(folder_path, verbose=True):
    """'지난 달까지'의 합본 parquet + manifest를 만든다. 월간 갱신 로봇이 부른다.

    새 달 CSV가 만들어진 '뒤에' 호출해야 한다 — 그래야 직전 달이 확정분에 들어간다.
    반환: 합본에 담긴 행 수 (만들지 않았으면 0)
    """
    files = archive_csvs(folder_path)
    if len(files) < 2:
        if verbose:
            print(f"ℹ️ {folder_path}: 파일이 {len(files)}개뿐이라 합본을 만들지 않는다")
        return 0

    past = files[:-1]                      # 최신월 제외 = 확정분
    frame = read_csv_frames(past)
    if frame.empty:
        if verbose:
            print(f"⚠️ {folder_path}: 확정분을 읽지 못해 합본을 만들지 않는다")
        return 0

    pq = os.path.join(folder_path, HISTORY_PARQUET)
    frame.to_parquet(pq, compression='snappy', index=False)
    with open(os.path.join(folder_path, HISTORY_MANIFEST), 'w', encoding='utf-8') as f:
        json.dump({'files': _manifest_of(past), 'rows': int(len(frame))}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)

    if verbose:
        mb = os.path.getsize(pq) / 1e6
        print(f"✅ {folder_path}: 합본 생성 — 확정분 {len(past)}개월 "
              f"{len(frame):,}행 · {mb:.1f}MB (최신월 {os.path.basename(files[-1])}은 제외)")
    return len(frame)


def _history_usable(folder_path, past):
    """합본이 지금의 '지난 달 파일들'과 일치하는지. 조금이라도 어긋나면 False."""
    pq = os.path.join(folder_path, HISTORY_PARQUET)
    mf = os.path.join(folder_path, HISTORY_MANIFEST)
    if not (os.path.exists(pq) and os.path.exists(mf)):
        return False
    try:
        with open(mf, encoding='utf-8') as f:
            saved = json.load(f)
        return saved.get('files') == _manifest_of(past)
    except Exception:
        return False


def load_frames(folder_path):
    """폴더 전체를 하나의 DataFrame으로. 합본이 쓸 수 있으면 쓰고, 아니면 전부 CSV.

    어느 경로로 읽든 결과는 같아야 한다 — 파일 순서(시간순)와 이어붙이는 순서를
    양쪽 모두 동일하게 유지한다.
    """
    files = archive_csvs(folder_path)
    if not files:
        return pd.DataFrame()

    past, latest = files[:-1], files[-1]
    if past and _history_usable(folder_path, past):
        try:
            hist = pd.read_parquet(os.path.join(folder_path, HISTORY_PARQUET))
            tail = read_csv_frames([latest])
            if not hist.empty:
                if tail.empty:
                    return hist
                return pd.concat([hist, tail], axis=0, ignore_index=True)
        except Exception as e:
            # 합본이 깨졌어도 앱은 떠야 한다 — 예전 경로로 돌아간다
            print(f"⚠️ {folder_path} 합본 읽기 실패, CSV 전체로 폴백: {e}")

    return read_csv_frames(files)
