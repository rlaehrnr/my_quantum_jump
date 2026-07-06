"""
스노우볼 동적 자산배분 전략 — 계산 모듈
============================================

명세서 기반 구현. CSV 데이터를 읽어 신호 판정·백테스트를 수행한다.

데이터 구조:
  data/snowball/monthly/{TICKER}_과거_데이터.csv  — 월봉 (신호·백테스트용)
  data/snowball/monthly/SP500_DIV.csv             — 배당수익률 (월별)
  data/snowball/daily_snapshot.csv                — 일봉 (이번달 진행률만)

CSV 형식 (investing.com KR 다운로드 형식):
  컬럼: "날짜","종가","시가","고가","저가","거래량","변동 %"
  날짜: "2026- 05- 01" (공백 포함 가능)
  정렬: 최신이 위 (내림차순)
  인코딩: UTF-8 with BOM
"""

import os
import re
import pandas as pd
import numpy as np
import streamlit as st

# ==========================================
# 자산 정의 (명세서 §1)
# ==========================================

# 조건1 모멘텀 신호용 (보유 안 함)
SIGNAL_ASSETS = ['TIP', 'VWO', 'VEA', 'VIXY']
# 조건1 위험회피 판정 세부
C1_RISK_ASSETS = ['TIP', 'VWO', 'VEA']   # 6M 수익률 음수 유지 대상
VIXY_SPIKE = 0.40                         # VIXY 6M 수익률 급등 임계(변동성 스파이크)

# 공격 자산 (12개월 모멘텀 비교)
OFFENSE_ASSETS = ['TQQQ', 'USD']

# 방어 자산 (12개월 이동평균 이격도 비교)
DEFENSE_ASSETS = ['GLD', 'TLT', 'SQQQ', 'SLV']

# 벤치마크
BENCHMARK = 'SPY'                      # (레거시, 현재 미사용)
BENCHMARKS = ['QQQ', 'SOXX']           # 전략 비교용 벤치마크 (차트/로그/카드)

# 모든 ETF 티커
ALL_TICKERS = SIGNAL_ASSETS + OFFENSE_ASSETS + DEFENSE_ASSETS + BENCHMARKS

# ==========================================
# 맘 삼성 전략 자산군 (탭 2)  — 백테스트로 확정한 최종안
# ==========================================
# 필터: TIP·SPY가 N개월 이동평균 이격도 > 0 (둘 다 위)일 때만 공격 국면 (기본 9개월)
SS_FILTER_ASSETS  = ['TIP', 'SPY']
SS_FILTER_WIN     = 9      # 필터 이동평균 개월 (백테스트 최적: 낙폭↓ 유지, 짧아 반응 빠름)
# 공격: 12개월 이동평균 이격도 > 0인 것 모두 동일가중
SS_OFFENSE_ASSETS = ['FAS', 'SOXL', 'TQQQ', 'TMF']
SS_OFFENSE_WIN    = 12
# 방어: IEF50 / GLD50 고정 (국채+금 반반 → 위기 성격 보완, TBT 제외).
#   백테스트상 모멘텀 선택·현금 안전장치보다 이 고정 반반이 위험조정 성과가 가장 좋았음.
SS_DEFENSE_ASSETS = ['IEF', 'GLD']
# 벤치마크는 또 메리츠와 동일 (BENCHMARKS = QQQ/SOXX)

# ==========================================
# 쏘 삼성 전략 자산군 (탭 3)
# ==========================================
# 모멘텀 점수 = 1+3+6+12개월 수익률의 단순 합
SO_MOM_WINDOWS   = [1, 3, 6, 12]
# 회피 필터: SPY의 모멘텀 점수 > 0 → 공격 국면, < 0 → 방어 국면
SO_FILTER_ASSET  = 'SPY'
# 공격: 아래 9종 중 모멘텀 점수 상위 2등을 50:50 동일가중
SO_OFFENSE_ASSETS = ['EWY', 'FDN', 'IBB', 'LIT', 'SMH', 'XLE', 'XLF', 'SPY', 'QQQ']
SO_TOPK          = 2
# 절대모멘텀 필터: 상위 2등이라도 자기 4개월 MA 이격도 ≤ 0 이면 제외.
#   남는 게 없으면(둘 다 4M MA 아래) 방어로 전환. (백테스트상 전 지표 개선)
SO_ABSMOM_WIN    = 4
# 방어: GLD50 / IEF50 고정
SO_DEFENSE_ASSETS = ['GLD', 'IEF']
# 추가 방어 트리거: 또 메리츠 리스크오프(cond1)가 발동하면 동반 방어.
#   백테스트상 쏘삼성의 CAGR·MDD·샤프·Sortino가 모두 개선(놓친 급락을 매크로 신호가 포착).
SO_USE_RISKOFF = True

# 로더가 로드할 전체 유니버스 (세 탭 합집합, 순서 유지·중복 제거)
LOAD_TICKERS = list(dict.fromkeys(
    ALL_TICKERS + SS_FILTER_ASSETS + SS_OFFENSE_ASSETS + SS_DEFENSE_ASSETS
    + [SO_FILTER_ASSET] + SO_OFFENSE_ASSETS + SO_DEFENSE_ASSETS
))

# CSH (현금 식별자)
CASH = 'CASH'


# ==========================================
# 데이터 로딩
# ==========================================

# 💡 GitHub raw 직접 로드 (data_loader.load_daily_data와 동일 패턴)
# Streamlit Cloud 컨테이너는 재배포(reboot) 전까지 로컬 체크아웃 파일이 갱신되지
# 않으므로, GitHub Actions가 커밋한 최신 CSV를 raw URL에서 우선 가져온다.
# → 매월 1일 자동 업데이트 후 리부트 없이 최대 1시간(ttl) 내 자동 반영.
# 네트워크 실패 시 로컬 파일로 폴백하므로 로컬 개발/장애 상황에도 안전.
SNOWBALL_RAW_BASE = "https://raw.githubusercontent.com/rlaehrnr/my_quantum_jump/main/data/snowball/monthly/"


def _read_csv_any_encoding(path_or_url):
    """utf-8-sig 우선, 실패 시 cp949로 CSV 읽기 (로컬 경로/URL 공용)."""
    try:
        return pd.read_csv(path_or_url, encoding='utf-8-sig')
    except UnicodeDecodeError:
        return pd.read_csv(path_or_url, encoding='cp949')


def _fetch_raw_csv(filename):
    """GitHub raw에서 CSV 로드 시도. 실패하면 None (조용히 폴백)."""
    from urllib.parse import quote
    url = SNOWBALL_RAW_BASE + quote(filename)
    try:
        df = _read_csv_any_encoding(url)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None


# 파일명 변형 후보: 자동 업데이트 스크립트 형식 / investing.com 원본(공백) / 단순형
_RAW_NAME_VARIANTS = ("{t}_과거_데이터.csv", "{t} 과거 데이터.csv", "{t}.csv")

def _parse_investing_date(date_str):
    """
    investing.com KR 다운로드 날짜 형식 파싱.
    "2026- 05- 01" 같은 공백 포함 형식도 처리.
    """
    if pd.isna(date_str):
        return pd.NaT
    # 공백 제거 후 표준 형식으로
    cleaned = re.sub(r'\s+', '', str(date_str))
    try:
        return pd.to_datetime(cleaned)
    except Exception:
        return pd.NaT


@st.cache_data(ttl="1h", show_spinner=False)
def load_monthly_prices(monthly_dir='data/snowball/monthly'):
    """
    모든 ETF의 월봉 데이터를 로드해 통합 DataFrame 반환.
    
    Returns:
        DataFrame: index=YearMonth(Period), columns=tickers, values=종가
        에러나 누락 티커가 있으면 빈 DataFrame
    """
    # 폴더의 모든 CSV 파일 스캔 (로컬 폴백용 — 폴더가 없어도 raw 로드는 진행)
    all_files = []
    if os.path.isdir(monthly_dir):
        all_files = [f for f in os.listdir(monthly_dir) if f.lower().endswith('.csv')]
    
    def _normalize(s):
        """공백/특수공백/언더스코어 제거 + 소문자 — 파일명 매칭 관대화.
        'TIP 과거 데이터.csv', 'TIP_과거_데이터.csv', 'TIP  과거  데이터.csv'
        모두 'tip과거데이터.csv'로 정규화되어 같다고 판정."""
        # 공백류 + 언더스코어 모두 제거
        s = re.sub(r'[\s_]+', '', s)
        return s.lower()
    
    # 각 ticker에 대해 "ticker"가 정규화된 파일명에 포함되어 있고
    # 정규화된 파일명이 "ticker과거데이터.csv" 또는 "ticker.csv"로 끝나는지 체크
    def _find_file(ticker):
        norm_target_a = _normalize(f"{ticker}_과거_데이터.csv")  # "tip과거데이터.csv"
        norm_target_b = _normalize(f"{ticker}.csv")              # "tip.csv"
        for fname in all_files:
            n = _normalize(fname)
            if n == norm_target_a or n == norm_target_b:
                return os.path.join(monthly_dir, fname)
        return None
    
    def _load_ticker_df(ticker):
        """1순위: GitHub raw (파일명 변형 순회), 2순위: 로컬 파일. 실패 시 None."""
        for pattern in _RAW_NAME_VARIANTS:
            df = _fetch_raw_csv(pattern.format(t=ticker))
            if df is not None:
                return df
        found = _find_file(ticker)
        if found is not None:
            try:
                return _read_csv_any_encoding(found)
            except Exception as e:
                print(f"⚠️ {ticker} 로컬 파일 읽기 오류: {e}")
        return None
    
    frames = []
    missing = []
    
    for ticker in LOAD_TICKERS:
        df = _load_ticker_df(ticker)
        
        if df is None:
            missing.append(ticker)
            continue
        
        try:
            # 필수 컬럼: 날짜, 종가
            if '날짜' not in df.columns or '종가' not in df.columns:
                print(f"⚠️ {ticker}: 필수 컬럼(날짜/종가) 누락. 실제 컬럼: {list(df.columns)}")
                missing.append(ticker)
                continue
            
            df['_date'] = df['날짜'].apply(_parse_investing_date)
            df['_close'] = pd.to_numeric(df['종가'].astype(str).str.replace(',', ''), errors='coerce')
            df = df.dropna(subset=['_date', '_close'])
            
            # YearMonth 인덱스로 변환 (월봉이므로 month period로 정규화)
            df['ym'] = df['_date'].dt.to_period('M')
            # 같은 달 여러 행이면 마지막 거래일(가장 최근 _date) 값 사용
            df = df.sort_values('_date').drop_duplicates('ym', keep='last')
            
            s = df.set_index('ym')['_close'].rename(ticker)
            frames.append(s)
        except Exception as e:
            print(f"⚠️ {ticker} 로드 오류: {e}")
            missing.append(ticker)
    
    if missing:
        print(f"⚠️ 누락된 티커: {missing}")
        print(f"   폴더({monthly_dir})에 있는 파일들: {all_files}")
    
    if not frames:
        return pd.DataFrame()
    
    prices = pd.concat(frames, axis=1).sort_index()
    return prices


@st.cache_data(ttl="1h", show_spinner=False)
def load_dividend_yield(monthly_dir='data/snowball/monthly'):
    """
    S&P 500 배당수익률 월별 시계열 로드.
    
    지원 형식:
    - .csv (utf-8 또는 cp949)
    - .xlsx (Excel)
    
    파일명 자동 탐색 (대소문자/공백/언더스코어 무시):
    - SP500_DIV.csv / SP500_DIV.xlsx
    - SP500_DIV_과거_데이터.csv 등
    
    데이터 형식: 'Date' 또는 '날짜' 컬럼 + 값 컬럼.
    값 컬럼은 자동 감지 ('종가', 'Value', 'Unnamed: 2' 등).
    † 같은 특수문자 자동 제거.
    
    Returns:
        Series: index=YearMonth(Period), values=배당수익률(%)
    """
    df = None
    
    # 1순위: GitHub raw (자동 업데이트 스크립트가 커밋하는 표준 파일명)
    df = _fetch_raw_csv('SP500_DIV.csv')
    
    # 2순위: 로컬 파일 자동 탐색 (.csv 또는 .xlsx)
    if df is None:
        if not os.path.isdir(monthly_dir):
            return pd.Series(dtype=float)
        
        all_files = [f for f in os.listdir(monthly_dir) 
                     if f.lower().endswith(('.csv', '.xlsx', '.xls'))]
        
        def _normalize(s):
            s = re.sub(r'[\s_]+', '', s)
            return s.lower()
        
        # 확장자 제외한 정규화 타겟 (.csv/.xlsx 어느 쪽이든 매칭)
        candidates_norm_stems = {
            _normalize('SP500_DIV'),
            _normalize('SP500_DIV_과거_데이터'),
            _normalize('SP500DIV'),
        }
        
        path = None
        for fname in all_files:
            # 확장자 떼고 정규화
            stem = os.path.splitext(fname)[0]
            if _normalize(stem) in candidates_norm_stems:
                path = os.path.join(monthly_dir, fname)
                break
        
        if path is None:
            return pd.Series(dtype=float)
        
        try:
            if path.lower().endswith(('.xlsx', '.xls')):
                df = pd.read_excel(path)
            else:
                df = _read_csv_any_encoding(path)
        except Exception as e:
            print(f"⚠️ 배당수익률 파일 로드 오류: {e}")
            return pd.Series(dtype=float)
    
    # 날짜 컬럼 자동 감지
    date_col = None
    for cand in ['날짜', 'Date', 'date', 'DATE']:
        if cand in df.columns:
            date_col = cand
            break
    if date_col is None:
        date_col = df.columns[0]
    
    # 값 컬럼 자동 감지 — Unnamed:2 (깨끗한 숫자) 우선
    val_col = None
    # 1순위: 이미 숫자만 있는 컬럼 (Unnamed:2 패턴)
    for cand in ['Unnamed: 2']:
        if cand in df.columns:
            val_col = cand
            break
    # 2순위: 일반적인 컬럼명
    if val_col is None:
        for cand in ['종가', 'DividendYield', 'Dividend Yield', '배당수익률', 'Value', 'value']:
            if cand in df.columns:
                val_col = cand
                break
    # 3순위: 두 번째 컬럼
    if val_col is None and len(df.columns) >= 2:
        val_col = df.columns[1]
    
    if val_col is None:
        return pd.Series(dtype=float)
    
    # 날짜 파싱 (ISO, "May 31, 1871" 등 다양한 형식 자동 처리)
    df['_date'] = pd.to_datetime(df[date_col], errors='coerce')
    # 만약 위에서 NaT가 많이 나오면 investing.com 형식("2026- 05- 01") 시도
    if df['_date'].isna().sum() > len(df) * 0.5:
        df['_date'] = df[date_col].apply(_parse_investing_date)
    
    # 값에서 †, %, 특수공백 제거 후 숫자 추출 (명세서 §2-2)
    def _parse_pct(x):
        if pd.isna(x):
            return np.nan
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x)
        m = re.search(r'([\d.]+)', s)
        return float(m.group(1)) if m else np.nan
    
    df['_val'] = df[val_col].apply(_parse_pct)
    df = df.dropna(subset=['_date', '_val'])
    
    if df.empty:
        return pd.Series(dtype=float)
    
    df['ym'] = df['_date'].dt.to_period('M')
    df = df.sort_values('_date').drop_duplicates('ym', keep='last')
    
    return df.set_index('ym')['_val'].sort_index()


# ==========================================
# 신호 계산
# ==========================================

def compute_returns(prices, periods):
    """
    각 ticker의 N개월 수익률 계산.
    
    Args:
        prices: DataFrame, monthly close
        periods: int (개월)
    
    Returns:
        DataFrame: 같은 shape, 값 = close/close.shift(periods) - 1
    """
    return prices / prices.shift(periods) - 1.0


def compute_ma_disparity(prices, window=12):
    """
    각 ticker의 N개월 이동평균 대비 이격도(disparity) 계산.

    이격도 = 현재가 / N개월_이동평균 - 1

    이동평균은 당월 종가를 포함한 최근 N개월 종가의 단순평균이다
    (기존 11M 수익률과 동일하게 신호월 m의 종가를 사용 → 별도 shift 없음).
    rolling(window)는 기본 min_periods=window라서 데이터가 N개월 미만이면 NaN.
    (window=12면 12개월 모두 있어야 유효 → 11M 수익률과 워밍업 동일.)

    Args:
        prices: DataFrame, monthly close
        window: int (개월), 기본 12

    Returns:
        DataFrame: 같은 shape, 값 = close / rolling_mean(window) - 1
    """
    ma = prices.rolling(window).mean()
    return prices / ma - 1.0


def compute_div_percentile(div_yield, window=60, min_pct=0.8):
    """
    명세서 §3-2 — 배당수익률의 5년 롤링 하위 백분위 신호.
    
    각 월 m에서, 직전 60개월(자신 포함, NaN 제외) 분포에서
    현재값 이하인 비율(%)을 계산. 그 값이 10% 이하이면 cond2=True.
    
    Args:
        div_yield: Series, index=YearMonth, values=배당수익률
        window: 60 (5년)
        min_pct: 0.8 (60×0.8=48개 유효 데이터 필요)
    
    Returns:
        (pct_series, threshold_series, rank_series, total_series)
        - pct_series: 백분위(%). 워밍업 부족하면 NaN.
        - threshold_series: 그 시점의 "하위 10% 경계 배당수익률" (quantile 0.1). 워밍업 부족 시 NaN.
          현재 배당수익률이 이 값보다 낮거나 같으면 cond2 발동.
        - rank_series: 표본 내 "비쌈 순위". 현재 배당수익률 이하(=동일하거나 더 비쌈)인
          개월 수 = (valid <= cur).sum(). 1등이면 표본 중 가장 비쌈. 워밍업 부족 시 NaN.
        - total_series: 백분위 계산에 쓴 유효 표본 개월 수 (보통 60). 워밍업 부족 시 NaN.
    """
    out = pd.Series(index=div_yield.index, dtype=float)
    thr = pd.Series(index=div_yield.index, dtype=float)
    rank = pd.Series(index=div_yield.index, dtype=float)
    total = pd.Series(index=div_yield.index, dtype=float)
    values = div_yield.values
    min_n = int(window * min_pct)
    
    for i in range(len(values)):
        start = max(0, i - window + 1)
        window_vals = values[start:i+1]
        # NaN 제외
        valid = window_vals[~pd.isna(window_vals)]
        cur = values[i]
        if pd.isna(cur) or len(valid) < min_n:
            out.iloc[i] = np.nan
            thr.iloc[i] = np.nan
            rank.iloc[i] = np.nan
            total.iloc[i] = np.nan
            continue
        # 현재값 이하(동일·더 비쌈)인 표본 수 = 비쌈 순위 (1=가장 비쌈)
        n_le = int((valid <= cur).sum())
        out.iloc[i] = n_le / len(valid) * 100
        # 하위 10% 경계값 — 실제 발동 규칙(n_le/len*100 <= 10)과 정확히 일치하도록 계산.
        #   "이 값 이하이면 발동"이 성립하는 가장 높은 배당수익률.
        #   np.quantile은 선형 보간이라 동점 경계에서 발동 규칙과 어긋날 수 있어 사용하지 않는다.
        #   = count(valid <= v)/len*100 <= 10 을 만족하는 가장 큰 v.
        limit = len(valid) * 0.10  # 발동 허용 최대 개수 (예: 60개월 → 6)
        boundary = np.nan
        for v in np.unique(valid):  # 오름차순
            if int((valid <= v).sum()) <= limit:
                boundary = v
            else:
                break
        thr.iloc[i] = boundary
        rank.iloc[i] = n_le
        total.iloc[i] = len(valid)
    
    return out, thr, rank, total


def compute_signals(prices, div_yield):
    """
    매월 m에서의 신호와 보유 종목을 계산.
    
    Returns:
        DataFrame, index=YearMonth, columns=[
            'cond1', 'cond2', 'defensive',
            'div_pct',
            'ret6_TIP','ret6_VWO','ret6_VEA','ret6_VIXY',
            'disp12_GLD','disp12_TLT','disp12_SQQQ','disp12_SLV',
            'ret12_TQQQ','ret12_USD',
            'hold',  # 보유 종목 티커 (또는 'CASH')
            'reason',  # 판정 사유 텍스트
        ]
    """
    ret6 = compute_returns(prices, 6)
    disp12 = compute_ma_disparity(prices, 12)   # 방어자산 선정용 (12M MA 이격도)
    ret12 = compute_returns(prices, 12)
    
    # 💡 [명세서 §5 시작 조건] 각 월이 백테스트 가능한지 판정.
    # 다음이 모두 계산 가능(NaN 아님)해야 그 달의 신호가 유효:
    #   - 신호 4종(TIP/VWO/VEA/VIXY) 6M 수익률
    #   - 방어 4종(GLD/TLT/SQQQ/SLV) 12M MA 이격도 (12개월 종가 필요)
    #   - 공격 2종(TQQQ/USD) 12M 수익률
    # (배당 60개월 백분위는 워밍업 전이면 cond2=False로 처리하고 진행 — 명세서 §5)
    ready_cols_6 = [t for t in SIGNAL_ASSETS if t in ret6.columns]
    ready_cols_def = [t for t in DEFENSE_ASSETS if t in disp12.columns]
    ready_cols_12 = [t for t in OFFENSE_ASSETS if t in ret12.columns]
    
    data_ready = pd.Series(True, index=prices.index)
    if ready_cols_6:
        data_ready &= ret6[ready_cols_6].notna().all(axis=1)
    if ready_cols_def:
        data_ready &= disp12[ready_cols_def].notna().all(axis=1)
    if ready_cols_12:
        data_ready &= ret12[ready_cols_12].notna().all(axis=1)
    # 필수 자산 컬럼 자체가 누락이면 전부 False
    if len(ready_cols_6) < len(SIGNAL_ASSETS) or len(ready_cols_def) < len(DEFENSE_ASSETS) or len(ready_cols_12) < len(OFFENSE_ASSETS):
        data_ready &= False
    
    # cond1: TIP/VWO/VEA 6M<0  &  (VIXY 6M<0  또는  VIXY 6M ≥ 40%)
    #   = 4종 모두 음수  또는  (TIP/VWO/VEA 음수 & VIXY 변동성 급등 ≥40%)
    cond1 = pd.Series(False, index=prices.index)
    if all(t in ret6.columns for t in SIGNAL_ASSETS):
        base_neg = (ret6[C1_RISK_ASSETS] < 0).all(axis=1)
        vixy = ret6['VIXY']
        vixy_trig = (vixy < 0) | (vixy >= VIXY_SPIKE)
        cond1 = (base_neg & vixy_trig).fillna(False)
    
    # cond2: 배당 5년(60개월) 롤링 하위 백분위 ≤ 10%
    #   ★ 전체 배당 이력으로 백분위를 먼저 계산한 뒤 가격 구간으로 reindex.
    #     가격 데이터 시작(워밍업) 이전의 배당 이력까지 60개월 윈도에 활용되므로,
    #     배당 파일이 충분히 길면 백테스트 시작 첫 달부터 cond2가 발동할 수 있다.
    #     (기존엔 div를 prices.index로 먼저 자른 탓에 시작 후 ~5년간 cond2가 항상 False였음.)
    if not div_yield.empty:
        # 전체 배당 이력을 연속 월 인덱스로 정렬(결측월=NaN, 윈도 내 NaN은 자동 제외)
        full_idx = pd.period_range(div_yield.index.min(), div_yield.index.max(), freq='M')
        div_full = div_yield.reindex(full_idx)
        pct_f, thr_f, rank_f, total_f = compute_div_percentile(div_full, window=60, min_pct=0.8)
        # 가격 구간으로 정렬
        div_pct   = pct_f.reindex(prices.index)
        div_thr   = thr_f.reindex(prices.index)
        div_rank  = rank_f.reindex(prices.index)
        div_total = total_f.reindex(prices.index)
        # ★ 전략 변경: 하위 10%(고평가)면 방어 — 단 '1등(=배당 최저=가장 비쌈)'인 달만
        #   방어에서 제외해 공격으로 돌린다. (rank!=1 조건 추가)
        cond2 = ((div_pct <= 10) & (div_rank != 1)).fillna(False)
    else:
        div_pct = pd.Series(np.nan, index=prices.index)
        div_thr = pd.Series(np.nan, index=prices.index)
        div_rank = pd.Series(np.nan, index=prices.index)
        div_total = pd.Series(np.nan, index=prices.index)
        cond2 = pd.Series(False, index=prices.index)
    
    defensive = cond1 | cond2
    
    # 보유 종목 결정
    holds = []
    reasons = []
    
    for m in prices.index:
        # 💡 데이터 미충족 달은 신호 무효 (백테스트에서 제외됨)
        if not bool(data_ready.loc[m]):
            holds.append(None)
            reasons.append("데이터 부족 (워밍업 구간)")
            continue
        
        cond1_m = bool(cond1.loc[m]) if m in cond1.index else False
        cond2_m = bool(cond2.loc[m]) if m in cond2.index else False
        defensive_m = cond1_m or cond2_m
        
        if defensive_m:
            # 방어 모드: 4종 12M MA 이격도(현재가/12M MA - 1) 비교 → 항상 최고값 선택
            disp_vals = {t: disp12[t].loc[m] for t in DEFENSE_ASSETS if t in disp12.columns}
            if not disp_vals or any(pd.isna(v) for v in disp_vals.values()):
                holds.append(None)
                reasons.append("데이터 부족")
                continue
            # 4종 모두 음수(전부 MA 아래)여도 현금 대신 그중 가장 높은 자산 선택
            best = max(disp_vals, key=disp_vals.get)
            holds.append(best)
            reason = f"방어모드 → {best} (12M MA 이격도={disp_vals[best]*100:.1f}%)"
            
            cause = []
            if cond1_m: cause.append("cond1(TIP/VWO/VEA 6M<0 & VIXY<0|≥40%)")
            if cond2_m: cause.append(f"cond2(배당 {div_pct.loc[m]:.1f}%ile)")
            reasons.append(f"{' & '.join(cause)} | {reason}")
        else:
            # 공격 모드: TQQQ vs USD ret12
            ret12_vals = {t: ret12[t].loc[m] for t in OFFENSE_ASSETS if t in ret12.columns}
            if not ret12_vals or any(pd.isna(v) for v in ret12_vals.values()):
                holds.append(None)
                reasons.append("데이터 부족")
                continue
            tqqq_v = ret12_vals.get('TQQQ', -np.inf)
            usd_v = ret12_vals.get('USD', -np.inf)
            if tqqq_v >= usd_v:
                holds.append('TQQQ')
                reasons.append(f"공격모드 → TQQQ (12M={tqqq_v*100:.1f}% ≥ USD {usd_v*100:.1f}%)")
            else:
                holds.append('USD')
                reasons.append(f"공격모드 → USD (12M={usd_v*100:.1f}% > TQQQ {tqqq_v*100:.1f}%)")
    
    # 배당수익률 원본값 (UI 표시용)
    if not div_yield.empty:
        div_value_series = div_yield.reindex(prices.index)
    else:
        div_value_series = pd.Series(np.nan, index=prices.index)
    
    sig = pd.DataFrame({
        'cond1': cond1,
        'cond2': cond2,
        'defensive': defensive,
        'div_pct': div_pct,
        'div_value': div_value_series,
        'div_threshold': div_thr,
        'div_rank': div_rank,
        'div_total': div_total,
        'hold': holds,
        'reason': reasons,
    }, index=prices.index)
    
    # 보조 컬럼 (UI 표시용)
    for t in SIGNAL_ASSETS:
        if t in ret6.columns:
            sig[f'ret6_{t}'] = ret6[t]
    for t in DEFENSE_ASSETS:
        if t in disp12.columns:
            sig[f'disp12_{t}'] = disp12[t]
    for t in OFFENSE_ASSETS:
        if t in ret12.columns:
            sig[f'ret12_{t}'] = ret12[t]
    
    return sig


# ==========================================
# 백테스트
# ==========================================

def run_backtest(prices, signals, cost=0.0025):
    """
    명세서 §5 — 월별 백테스트 루프.
    
    신호월 m의 신호로 m+1(보유월) 한 달 보유.
    수익률 = price[hold][m+1] / price[hold][m] - 1
    
    거래비용(턴오버 기반):
        직전 보유월 대비 보유 종목이 바뀌는 달(= 매매 발생)에만 cost를 차감한다.
        첫 진입(직전 보유 없음)도 1회 차감. 같은 종목을 이어서 보유하면 비용 0.
        cost는 1회 교체(로테이션)당 비율 (기본 0.0025 = 0.25%).
        벤치마크(QQQ/SOXX)는 매수 후 보유로 보아 비용 미반영(총수익).
    
    Args:
        prices: DataFrame, monthly close
        signals: DataFrame from compute_signals
        cost: float, 1회 종목 교체당 거래비용 비율 (기본 0.25%)
    
    Returns:
        DataFrame, index=보유월(nm), columns=[
            'signal_month', 'hold_month', 'defensive', 'hold', 'reason',
            'ret_gross', 'cost', 'switched', 'ret_strategy',
            'ret_<benchmark>'..., 'cum_strategy', 'cum_<benchmark>'..., 'dd_strategy'
        ]
        ('ret_strategy'는 비용 차감 후 순수익)
    """
    months = list(prices.index)
    records = []
    prev_hold = None  # 직전 보유월의 보유 종목 (턴오버 판정용)
    
    for i, m in enumerate(months[:-1]):
        nm = months[i+1]
        hold = signals.loc[m, 'hold']
        defensive = bool(signals.loc[m, 'defensive'])
        reason = signals.loc[m, 'reason']
        
        if hold is None:
            # 데이터 부족 → skip (prev_hold는 갱신하지 않음)
            continue
        
        # 보유 종목 총수익 (방어자산 음수선택 반영으로 CASH는 더 이상 없음)
        p0 = prices.loc[m, hold] if hold in prices.columns else np.nan
        p1 = prices.loc[nm, hold] if hold in prices.columns else np.nan
        if pd.isna(p0) or pd.isna(p1) or p0 == 0:
            continue
        ret_gross = p1 / p0 - 1.0
        
        # 거래비용: 직전 보유월과 종목이 바뀌었거나(교체) 첫 진입이면 cost 차감
        switched = (prev_hold is None) or (hold != prev_hold)
        tc = cost if switched else 0.0
        ret_strat = ret_gross - tc
        
        rec = {
            'signal_month': str(m),
            'hold_month': str(nm),
            'defensive': defensive,
            'hold': hold,
            'reason': reason,
            'ret_gross': ret_gross,
            'cost': tc,
            'switched': switched,
            'ret_strategy': ret_strat,
        }
        # 벤치마크 월수익률 (QQQ/SOXX, 매수 후 보유 → 비용 미반영)
        for b in BENCHMARKS:
            if b in prices.columns:
                p0b = prices.loc[m, b]
                p1b = prices.loc[nm, b]
                rec[f'ret_{b}'] = (p1b / p0b - 1.0) if (pd.notna(p0b) and pd.notna(p1b) and p0b != 0) else np.nan
            else:
                rec[f'ret_{b}'] = np.nan
        records.append(rec)
        prev_hold = hold
    
    if not records:
        return pd.DataFrame()
    
    bt = pd.DataFrame(records)
    bt['cum_strategy'] = (1 + bt['ret_strategy']).cumprod()
    for b in BENCHMARKS:
        bt[f'cum_{b}'] = (1 + bt[f'ret_{b}'].fillna(0)).cumprod()
    # 낙폭(drawdown): 원금 1.0(시작 시점)을 최고점에 포함시켜야 시작 직후 하락도 낙폭에 반영된다.
    #   (cum_strategy 첫 값은 1.0이 아니라 첫 달 수익률이 반영된 값이므로 clip(lower=1.0) 필요)
    peak = bt['cum_strategy'].cummax().clip(lower=1.0)
    bt['dd_strategy'] = bt['cum_strategy'] / peak - 1.0
    
    return bt


def compute_performance(bt):
    """
    명세서 §6 — 성과지표 계산.
    
    Returns:
        dict: CAGR, cum_return, MDD, sharpe, vol, win_rate, offense_pct, n_months
    """
    if bt.empty:
        return {}
    
    n = len(bt)
    cum = bt['cum_strategy'].iloc[-1]
    cagr = cum ** (12.0/n) - 1.0 if cum > 0 else -1.0
    
    rets = bt['ret_strategy']
    # 정답지와 동일하게 모표준편차(ddof=0) 사용
    std_strat = rets.std(ddof=0)
    vol = std_strat * np.sqrt(12)
    sharpe = (rets.mean() / std_strat * np.sqrt(12)) if std_strat > 0 else 0.0
    # Sortino: 하락 편차(음수 수익만)로 위험 측정 (상승 변동성은 벌주지 않음)
    downside = np.sqrt((np.minimum(rets, 0.0) ** 2).mean())
    sortino = (rets.mean() / downside * np.sqrt(12)) if downside > 0 else 0.0
    mdd = bt['dd_strategy'].min()
    win_rate = (rets > 0).mean()
    offense_pct = (~bt['defensive']).mean()
    offense_months = int((~bt['defensive']).sum())
    
    # 거래비용 요약 (turnover)
    n_switches = int(bt['switched'].sum()) if 'switched' in bt.columns else 0
    total_cost = float(bt['cost'].sum()) if 'cost' in bt.columns else 0.0
    # 비용 미반영(gross) 누적수익 — 비용 영향 비교용
    if 'ret_gross' in bt.columns:
        cum_gross = float((1 + bt['ret_gross']).cumprod().iloc[-1])
    else:
        cum_gross = cum
    
    # 벤치마크 비교 (QQQ, SOXX 등) — 매수 후 보유
    benchmarks = {}
    for b in BENCHMARKS:
        cum_col, ret_col = f'cum_{b}', f'ret_{b}'
        if cum_col not in bt.columns or ret_col not in bt.columns or bt[ret_col].notna().sum() == 0:
            continue  # 데이터(파일) 없는 벤치마크는 제외
        b_cum = bt[cum_col].iloc[-1]
        b_cagr = b_cum ** (12.0/n) - 1.0 if b_cum > 0 else -1.0
        b_peak = bt[cum_col].cummax().clip(lower=1.0)
        b_dd = (bt[cum_col] / b_peak - 1.0).min()
        b_std = bt[ret_col].std(ddof=0)
        b_sharpe = (bt[ret_col].mean() / b_std * np.sqrt(12)) if b_std > 0 else 0.0
        b_down = np.sqrt((np.minimum(bt[ret_col].fillna(0.0), 0.0) ** 2).mean())
        b_sortino = (bt[ret_col].mean() / b_down * np.sqrt(12)) if b_down > 0 else 0.0
        benchmarks[b] = {
            'cum_return': b_cum - 1.0,
            'cagr': b_cagr,
            'mdd': b_dd,
            'vol': b_std * np.sqrt(12),
            'sharpe': b_sharpe,
            'sortino': b_sortino,
        }
    
    return {
        'n_months': n,
        'cum_return': cum - 1.0,
        'cagr': cagr,
        'vol': vol,
        'sharpe': sharpe,
        'sortino': sortino,
        'mdd': mdd,
        'win_rate': win_rate,
        'offense_pct': offense_pct,
        'offense_months': offense_months,
        'n_switches': n_switches,
        'total_cost': total_cost,
        'cum_gross_return': cum_gross - 1.0,
        'benchmarks': benchmarks,
    }


# ==========================================
# 맘 삼성 전략 엔진 (탭 2)
# ==========================================
#
# 규칙 요약:
#   · 필터(진입 관문): TIP·SPY 둘 다 11M 이동평균 이격도 > 0 → 공격 국면
#   · 공격: FAS·SOXL·TQQQ·TMF 중 12M 이동평균 이격도 > 0인 것 모두 동일가중.
#           필터는 통과했는데 통과 자산이 0개면 → 방어로 전환.
#   · 방어: IEF·GLD·TBT 중 5M 이동평균 이격도 1위 1개.
#           단 1위가 절대모멘텀 미달(5M MA 아래, 이격도 ≤ 0)이면 → 현금(CASH).
#   · 벤치마크: QQQ·SOXX (또 메리츠와 동일).
#
# 반환 포맷은 또 메리츠 엔진과 동일하게 맞춰(백테스트 bt 컬럼 동일) compute_performance를
# 그대로 재사용한다. hold는 표시용 문자열(공격이면 "SOXL·TQQQ"), holds는 실제 티커 리스트.

SS_CASH = 'CASH'


def compute_signals_samsung(prices, use_filter=True, filter_win=SS_FILTER_WIN):
    """맘 삼성 전략의 월별 신호·보유 계산 (최종안).

    규칙:
      · 필터: TIP·SPY 둘 다 filter_win개월 MA 이격도 > 0 → 공격 게이트 통과 (기본 9개월)
      · 공격: FAS·SOXL·TQQQ·TMF 중 12M MA 이격도 > 0인 것 모두 동일가중
      · 방어: IEF50 / GLD50 고정 (게이트 미통과 또는 공격 후보 0개일 때)

    Args:
        prices: 월봉 종가 DataFrame
        use_filter: False면 필터를 무시하고 공격 후보가 있으면 항상 공격(A/B 비교용).
            'filter_pass'에는 실제 필터 상태를 그대로 기록하되 보유 결정만 무시.
        filter_win: 필터 이동평균 개월 (기본 SS_FILTER_WIN=9)

    Returns:
        DataFrame, index=YearMonth, columns=[
            'defensive', 'filter_pass', 'n_offense',
            'holds', 'hold', 'reason',
            'dispF_TIP','dispF_SPY',                       # 필터 이격도 (filter_win 기준)
            'disp12_FAS','disp12_SOXL','disp12_TQQQ','disp12_TMF',
            'disp_IEF','disp_GLD',                          # 방어 참고용 이격도(5M)
        ]
    """
    dF  = compute_ma_disparity(prices, filter_win)   # 필터
    d12 = compute_ma_disparity(prices, SS_OFFENSE_WIN)   # 공격
    d5  = compute_ma_disparity(prices, 5)                # 방어(참고 표시용)

    filt = [t for t in SS_FILTER_ASSETS if t in prices.columns]
    off  = [t for t in SS_OFFENSE_ASSETS if t in prices.columns]
    dfn  = [t for t in SS_DEFENSE_ASSETS if t in prices.columns]

    # 준비도: 필터·공격·방어 자산 이격도가 모두 계산 가능해야 그 달 신호 유효.
    ready = pd.Series(True, index=prices.index)
    if filt:
        ready &= dF[filt].notna().all(axis=1)
    if off:
        ready &= d12[off].notna().all(axis=1)
    if dfn:
        ready &= d5[dfn].notna().all(axis=1)
    if (len(filt) < len(SS_FILTER_ASSETS)
            or len(off) < len(SS_OFFENSE_ASSETS)
            or len(dfn) < len(SS_DEFENSE_ASSETS)):
        ready &= False

    records = []
    for m in prices.index:
        rec = {
            'dispF_TIP':   dF.loc[m, 'TIP']   if 'TIP'  in dF.columns else np.nan,
            'dispF_SPY':   dF.loc[m, 'SPY']   if 'SPY'  in dF.columns else np.nan,
            'disp12_FAS':  d12.loc[m, 'FAS']  if 'FAS'  in d12.columns else np.nan,
            'disp12_SOXL': d12.loc[m, 'SOXL'] if 'SOXL' in d12.columns else np.nan,
            'disp12_TQQQ': d12.loc[m, 'TQQQ'] if 'TQQQ' in d12.columns else np.nan,
            'disp12_TMF':  d12.loc[m, 'TMF']  if 'TMF'  in d12.columns else np.nan,
            'disp_IEF':    d5.loc[m, 'IEF']   if 'IEF'  in d5.columns else np.nan,
            'disp_GLD':    d5.loc[m, 'GLD']   if 'GLD'  in d5.columns else np.nan,
        }

        if not bool(ready.loc[m]):
            rec.update({'defensive': True, 'filter_pass': False, 'n_offense': 0,
                        'holds': None, 'hold': None, 'reason': '데이터 워밍업'})
            records.append(rec)
            continue

        # 필터: TIP·SPY 둘 다 filter_win개월 MA 이격도 > 0
        filter_pass = bool((dF.loc[m, filt] > 0).all())
        off_pass = [t for t in off if d12.loc[m, t] > 0]
        rec['n_offense'] = len(off_pass)
        rec['filter_pass'] = filter_pass

        gate = filter_pass or (not use_filter)

        if gate and len(off_pass) > 0:
            holds = off_pass
            defensive = False
            reason = f"공격 · {len(off_pass)}종 동일가중"
        else:
            # 방어: IEF50 / GLD50 고정
            holds = list(SS_DEFENSE_ASSETS)   # ['IEF','GLD']
            defensive = True
            reason = ("방어 · IEF50·GLD50 (필터 이탈)" if not gate
                      else "방어 · IEF50·GLD50 (공격 후보 없음)")

        rec['defensive'] = defensive
        rec['holds'] = holds
        rec['hold'] = SS_CASH if holds == [SS_CASH] else '·'.join(holds)
        rec['reason'] = reason
        records.append(rec)

    return pd.DataFrame(records, index=prices.index)


def run_backtest_samsung(prices, signals, cost=0.0025):
    """맘 삼성 백테스트. 공격은 동일가중 바스켓, 방어는 단일/현금.

    거래비용(턴오버): 이번 달 '새로 매수하는 비중' 합계 × cost.
      - 단일 종목 전환(100% 교체)이면 매수분 = 1.0 → cost×1.0 (또 메리츠와 동일 스케일).
      - 바스켓 일부만 교체되면 매수분에 비례해 차감.
      - 현금(CASH)은 매수 없음 → 비용 0.
    벤치마크(QQQ/SOXX)는 매수 후 보유 → 비용 미반영.

    반환 bt는 또 메리츠 run_backtest와 동일한 컬럼 구조라 compute_performance 재사용 가능.
    """
    months = list(prices.index)
    records = []
    prev_w = {}   # 직전 보유월의 목표 비중 (턴오버 판정)

    for i, m in enumerate(months[:-1]):
        nm = months[i + 1]
        holds = signals.loc[m, 'holds']
        if holds is None:
            continue  # 미준비 월 skip (prev_w 유지)

        defensive = bool(signals.loc[m, 'defensive'])
        reason = signals.loc[m, 'reason']

        if holds == [SS_CASH]:
            ret_gross = 0.0
            w_new = {}
        else:
            w = 1.0 / len(holds)
            rets, w_new = [], {}
            for t in holds:
                p0 = prices.loc[m, t] if t in prices.columns else np.nan
                p1 = prices.loc[nm, t] if t in prices.columns else np.nan
                if pd.isna(p0) or pd.isna(p1) or p0 == 0:
                    continue
                rets.append(p1 / p0 - 1.0)
                w_new[t] = w
            if not rets:
                continue
            ret_gross = float(np.mean(rets))

        # 매수분(양의 비중 증가) 합계 기반 거래비용
        bought = sum(max(w_new.get(t, 0.0) - prev_w.get(t, 0.0), 0.0)
                     for t in set(w_new) | set(prev_w))
        tc = cost * bought
        switched = bought > 1e-9

        rec = {
            'signal_month': str(m),
            'hold_month': str(nm),
            'defensive': defensive,
            'hold': signals.loc[m, 'hold'],
            'reason': reason,
            'ret_gross': ret_gross,
            'cost': tc,
            'switched': switched,
            'ret_strategy': ret_gross - tc,
        }
        for b in BENCHMARKS:
            if b in prices.columns:
                p0b, p1b = prices.loc[m, b], prices.loc[nm, b]
                rec[f'ret_{b}'] = (p1b / p0b - 1.0) if (pd.notna(p0b) and pd.notna(p1b) and p0b != 0) else np.nan
            else:
                rec[f'ret_{b}'] = np.nan
        records.append(rec)
        prev_w = w_new

    if not records:
        return pd.DataFrame()

    bt = pd.DataFrame(records)
    bt['cum_strategy'] = (1 + bt['ret_strategy']).cumprod()
    for b in BENCHMARKS:
        bt[f'cum_{b}'] = (1 + bt[f'ret_{b}'].fillna(0)).cumprod()
    peak = bt['cum_strategy'].cummax().clip(lower=1.0)
    bt['dd_strategy'] = bt['cum_strategy'] / peak - 1.0
    return bt


# ==========================================
# 쏘 삼성 (탭 3) 엔진
# ==========================================
def compute_mom_score(prices, windows=SO_MOM_WINDOWS):
    """모멘텀 점수 = 각 기간 수익률(price/price.shift(k)-1)의 단순 합.

    Returns: DataFrame(index=YearMonth, columns=자산) 점수. 워밍업 구간은 NaN.
    """
    total = None
    for k in windows:
        r = prices / prices.shift(k) - 1.0
        total = r if total is None else (total + r)
    return total


def compute_riskoff_cond1(prices):
    """또 메리츠의 리스크오프 신호(cond1)를 월별 bool 시리즈로 반환.

    cond1 = (TIP·VWO·VEA 6M 수익률 모두 < 0) AND (VIXY 6M < 0 OR VIXY 6M ≥ VIXY_SPIKE)
    필요한 신호자산(TIP/VWO/VEA/VIXY)이 없으면 전 구간 False.
    다른 전략(쏘 삼성 등)에서 추가 방어 트리거로 재사용한다.
    """
    ret6 = compute_returns(prices, 6)
    cond1 = pd.Series(False, index=prices.index)
    if all(t in ret6.columns for t in SIGNAL_ASSETS):
        base_neg = (ret6[C1_RISK_ASSETS] < 0).all(axis=1)
        vixy = ret6['VIXY']
        vixy_trig = (vixy < 0) | (vixy >= VIXY_SPIKE)
        cond1 = (base_neg & vixy_trig).fillna(False)
    return cond1.astype(bool)


def compute_signals_so(prices, use_riskoff=SO_USE_RISKOFF):
    """쏘 삼성 월별 신호·보유 계산.

    규칙:
      · 회피 필터: SPY 모멘텀 점수(1+3+6+12M 합) > 0 → 공격, ≤ 0 → 방어
      · 리스크오프(옵션): 또 메리츠 cond1 발동 시 동반 방어 (use_riskoff=True)
      · 공격: 9종 중 모멘텀 점수 상위 SO_TOPK(2) 중 4M MA 이격도>0 인 것만 동일가중
      · 방어: GLD50 / IEF50 고정

    run_backtest_samsung과 호환되도록 holds/defensive/hold/reason 컬럼을 포함한다.
    """
    off = [t for t in SO_OFFENSE_ASSETS if t in prices.columns]
    dfn = [t for t in SO_DEFENSE_ASSETS if t in prices.columns]
    score = compute_mom_score(prices)
    d_abs = compute_ma_disparity(prices, SO_ABSMOM_WIN)   # 절대모멘텀용 4M MA 이격도
    riskoff = compute_riskoff_cond1(prices) if use_riskoff else pd.Series(False, index=prices.index)
    # 리스크오프 구성요소(TIP·VWO·VEA·VIXY 6M 수익률) — UI 표시용
    ret6 = compute_returns(prices, 6)

    # 준비도: 공격 전 종목 + SPY 점수 계산 가능 + 방어 종목 가격 존재 + 4M 이격도 계산 가능
    ready = pd.Series(True, index=prices.index)
    if off:
        ready &= score[off].notna().all(axis=1)
        ready &= d_abs[off].notna().all(axis=1)
    if SO_FILTER_ASSET in score.columns:
        ready &= score[SO_FILTER_ASSET].notna()
    if dfn:
        ready &= prices[dfn].notna().all(axis=1)
    if (len(off) < len(SO_OFFENSE_ASSETS) or len(dfn) < len(SO_DEFENSE_ASSETS)
            or SO_FILTER_ASSET not in score.columns):
        ready &= False

    records = []
    for m in prices.index:
        rec = {f'score_{t}': (score.loc[m, t] if t in score.columns else np.nan)
               for t in SO_OFFENSE_ASSETS}
        rec.update({f'abs_{t}': (d_abs.loc[m, t] if t in d_abs.columns else np.nan)
                    for t in SO_OFFENSE_ASSETS})
        rec['score_SPY_filter'] = score.loc[m, SO_FILTER_ASSET] if SO_FILTER_ASSET in score.columns else np.nan
        for t in SIGNAL_ASSETS:   # TIP, VWO, VEA, VIXY (6M 수익률) — 리스크오프 판정 표시용
            rec[f'ro6_{t}'] = ret6.loc[m, t] if t in ret6.columns else np.nan

        if not bool(ready.loc[m]):
            rec.update({'defensive': True, 'filter_pass': False, 'holds': None,
                        'hold': None, 'reason': '데이터 워밍업', 'rank': None})
            records.append(rec)
            continue

        spy_s = score.loc[m, SO_FILTER_ASSET]
        filter_pass = bool(spy_s > 0)
        riskoff_m = bool(riskoff.loc[m]) if m in riskoff.index else False
        rec['riskoff'] = riskoff_m
        ranked = score.loc[m, off].sort_values(ascending=False)
        top = list(ranked.index[:SO_TOPK])
        rec['rank'] = ' > '.join(top)

        if riskoff_m:
            # 리스크오프(cond1): SPY 필터·모멘텀과 무관하게 동반 방어
            holds = list(SO_DEFENSE_ASSETS)
            defensive = True
            reason = "방어 · GLD50·IEF50 (리스크오프 cond1)"
        elif filter_pass:
            # 절대모멘텀: 상위 2등 중 자기 4M MA 이격도 > 0 인 것만 보유
            picks = [t for t in top if d_abs.loc[m, t] > 0]
            if picks:
                holds = picks
                defensive = False
                if len(picks) < len(top):
                    dropped = [t for t in top if t not in picks]
                    reason = f"공격 · {'·'.join(picks)} (4M↓ 제외: {'·'.join(dropped)})"
                else:
                    reason = f"공격 · 상위{SO_TOPK} ({'·'.join(picks)}) 동일가중"
            else:
                holds = list(SO_DEFENSE_ASSETS)
                defensive = True
                reason = "방어 · GLD50·IEF50 (상위2 모두 4M MA 아래)"
        else:
            holds = list(SO_DEFENSE_ASSETS)   # ['GLD','IEF']
            defensive = True
            reason = "방어 · GLD50·IEF50 (SPY 모멘텀 음수)"

        rec['defensive'] = defensive
        rec['filter_pass'] = filter_pass
        rec['holds'] = holds
        rec['hold'] = '·'.join(holds)
        rec['reason'] = reason
        records.append(rec)

    return pd.DataFrame(records, index=prices.index)


def run_backtest_so(prices, signals, cost=0.0025):
    """쏘 삼성 백테스트. 공격 top2·방어 반반 모두 동일가중 바스켓이라
    run_backtest_samsung 러너를 그대로 재사용한다."""
    return run_backtest_samsung(prices, signals, cost=cost)


# ==========================================================================
# 또 ISA (탭 4) — 국내 상장 ETF 모멘텀 로테이션 엔진
# ==========================================================================
#   · 공격 10종: (1+3+6+12개월 수익률 합) 상위 3종 동일가중
#   · 방어 3종:  2개월 MA 이격도 상위 2종 동일가중(50:50)
#   · 위험회피:  TIP 10개월 MA 이격도 > 0 → 공격, 아니면 방어
#   데이터는 data/snowball_kr/monthly/ (미국 파이프라인과 분리), TIP은 미국 폴더 공유.
# --------------------------------------------------------------------------
KO_RAW_BASE = ("https://raw.githubusercontent.com/rlaehrnr/my_quantum_jump/"
               "main/data/snowball_kr/monthly/")

KO_OFFENSE = ['379810', '309230', '360750', '102110', '130730',
              '152380', '332620', '411060', '137610', '182480']
KO_DEFENSE = ['217770', '225130', '455030']
KO_FILTER_ASSET = 'TIP'         # 위험회피 필터 (미국 물가연동채, 미국 폴더에서 로드)
KO_FILTER_WIN = 10              # TIP 10개월 이동평균 이격도
KO_MOM_WINDOWS = [1, 3, 6, 9, 12]  # 공격 모멘텀 점수 = 이 기간 수익률 합
KO_TOPK = 3                     # 공격 상위 K종
KO_ABSMOM_WIN = 3               # 절대모멘텀: 상위 K종 중 최근 N개월 MA 이격도 ≥ 0 인 것만 투자
KO_DEF_TOPK = 2                 # 방어 상위 K종
KO_DEF_WIN = 2                  # 방어 선택 기준: N개월 MA 이격도 순위 (스파이크에 덜 민감)
KO_BENCHMARKS = ['102110']      # 벤치마크: KOSPI200(TIGER200) 매수후보유

KO_TICKER_NAMES = {
    '379810': 'KODEX 미국나스닥100', '309230': 'ACE 미국WideMoat가치주',
    '360750': 'TIGER 미국S&P500', '102110': 'TIGER 200',
    '130730': 'KOSEF 단기자금', '152380': 'KODEX 국채선물10년',
    '332620': 'ARIRANG 미국장기우량회사채', '411060': 'ACE KRX금현물',
    '137610': 'TIGER 농산물선물Enhanced(H)', '182480': 'TIGER 미국MSCI리츠(합성H)',
    '217770': 'TIGER WTI원유선물인버스(H)', '225130': 'ACE 골드선물레버리지(합성H)',
    '455030': 'KODEX 미국달러SOFR금리액티브',
}
KO_ALL = list(dict.fromkeys(KO_OFFENSE + KO_DEFENSE))


def _ko_clean_name(name):
    """파일명 안전화: 공백·괄호·&·슬래시 제거 (update_snowball_kr.py와 동일 규칙)."""
    return (name.replace(' ', '').replace('(', '').replace(')', '')
                .replace('/', '').replace('\\', '').replace('&', ''))


def _ko_filename_variants(code):
    """해당 코드의 가능한 파일명 후보 (종목명 포함형 우선, 숫자만형 폴백)."""
    nm = _ko_clean_name(KO_TICKER_NAMES.get(code, code))
    return (f"{code}_{nm}_과거_데이터.csv", f"{code}_과거_데이터.csv", f"{code}.csv")


def _fetch_ko_raw_csv(filename):
    """snowball_kr 폴더의 GitHub raw CSV 로드 시도. 실패하면 None."""
    from urllib.parse import quote
    try:
        df = _read_csv_any_encoding(KO_RAW_BASE + quote(filename))
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None


def _series_from_csv(df):
    """CSV DataFrame → 월말 종가 Series (index=YearMonth Period). 실패 시 None."""
    if df is None or df.empty:
        return None
    df.columns = [c.strip() for c in df.columns]
    dcol = next((c for c in df.columns if '날짜' in c or 'ate' in c.lower()), None)
    pcol = next((c for c in df.columns if '종가' in c or 'lose' in c.lower()), None)
    if dcol is None or pcol is None:
        return None
    d = pd.to_datetime(df[dcol].apply(_parse_investing_date), errors='coerce')
    p = pd.to_numeric(df[pcol].astype(str).str.replace(',', '', regex=False), errors='coerce')
    s = pd.DataFrame({'d': d, 'p': p}).dropna().sort_values('d')
    if s.empty:
        return None
    s.index = s['d'].dt.to_period('M')
    return s['p'].groupby(level=0).last()


@st.cache_data(ttl="1h", show_spinner=False)
def load_ko_prices(kr_dir='data/snowball_kr/monthly', us_dir='data/snowball/monthly'):
    """또 ISA용 13종(국내) + TIP(미국) 월봉 통합 로드.

    1순위 GitHub raw, 2순위 로컬 파일. 종목별 상장 시점이 달라 컬럼마다 시작점이 다름.
    Returns: DataFrame(index=YearMonth, columns=[코드..., 'TIP'])  (빈 DF면 로드 실패)
    """
    series = {}

    def _load_one(code, raw_variants, local_dir):
        # raw 우선
        for fn in raw_variants:
            s = _series_from_csv(_fetch_ko_raw_csv(fn) if local_dir == kr_dir
                                 else _fetch_raw_csv(fn))
            if s is not None and len(s) > 3:
                return s
        # 로컬 폴백
        if os.path.isdir(local_dir):
            norm = lambda x: re.sub(r'[\s_]+', '', x).lower()
            targets = {norm(v) for v in raw_variants}
            for f in os.listdir(local_dir):
                if f.lower().endswith('.csv') and norm(f) in targets:
                    try:
                        return _series_from_csv(_read_csv_any_encoding(os.path.join(local_dir, f)))
                    except Exception:
                        pass
        return None

    for code in KO_ALL:
        s = _load_one(code, _ko_filename_variants(code), kr_dir)
        if s is not None:
            series[code] = s
    # 필터용 TIP (미국 폴더)
    tip = _load_one('TIP', _RAW_NAME_VARIANTS_TIP, us_dir)
    if tip is not None:
        series['TIP'] = tip

    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series).sort_index()
    return df[~df.index.duplicated(keep='last')]


# TIP은 미국 폴더 파일명 규칙을 따름
_RAW_NAME_VARIANTS_TIP = ("TIP_과거_데이터.csv", "TIP 과거 데이터.csv", "TIP.csv")


def compute_signals_ko(prices):
    """또 ISA 월별 신호·보유 계산.

    각 월 m에서:
      · 위험회피: TIP 10M MA 이격도 > 0 → 공격 허용, 아니면 방어
      · 공격: 그 시점 존재하는 공격 후보(1/3/6/12M 수익률 모두 계산가능) 중
              모멘텀 점수(1+3+6+9+12M 합, 최근1M≥0) 상위 3종 동일가중
      · 방어: 존재하는 방어 후보 중 2개월 MA 이격도 상위 2종 동일가중(50:50)
    종목별 상장 시점이 달라 '그 시점 가용 종목'만으로 순위를 매긴다(동적 유니버스).

    run_backtest_ko와 호환되는 holds/defensive/hold/reason + 표시용 컬럼을 담아 반환.
    """
    off = [t for t in KO_OFFENSE if t in prices.columns]
    dfn = [t for t in KO_DEFENSE if t in prices.columns]

    # 모멘텀 점수(공격) — 1+3+6+9+12M 수익률 합. 각 기간 모두 있어야 유효.
    score = None
    for k in KO_MOM_WINDOWS:
        r = prices[off] / prices[off].shift(k) - 1.0
        score = r if score is None else (score + r)
    off_absmom = compute_ma_disparity(prices[off], KO_ABSMOM_WIN)   # 공격 절대모멘텀(최근 N개월 MA 이격도)
    def_rank = compute_ma_disparity(prices[dfn], KO_DEF_WIN)         # 방어 선택(N개월 MA 이격도 순위)
    tip_disp = (prices[KO_FILTER_ASSET] / prices[KO_FILTER_ASSET].rolling(KO_FILTER_WIN).mean() - 1.0
                if KO_FILTER_ASSET in prices.columns else pd.Series(np.nan, index=prices.index))

    rows = []
    for m in prices.index:
        rec = {'signal_month': str(m)}
        td = tip_disp.loc[m] if m in tip_disp.index else np.nan
        rec['tip_disp'] = td
        # 공격 후보 점수 (해당 월 유효한 것만)
        ovalid = {t: score.loc[m, t] for t in off if pd.notna(score.loc[m, t])}
        oabs = {t: off_absmom.loc[m, t] for t in off if pd.notna(off_absmom.loc[m, t])}
        dvalid = {t: def_rank.loc[m, t] for t in dfn if pd.notna(def_rank.loc[m, t])}
        rec['n_offense_avail'] = len(ovalid)
        rec['offense_absmom'] = oabs   # 표시용: 각 후보 최근 1M 수익
        # 필터
        filter_pass = bool(pd.notna(td) and td > 0)
        rec['filter_pass'] = filter_pass

        if pd.isna(td) or (not ovalid and not dvalid):
            # 준비 안 됨 (TIP 워밍업 전 등) → skip 대상
            rec.update({'holds': None, 'defensive': None, 'hold': None, 'reason': '데이터 준비중'})
            rows.append(rec)
            continue

        if filter_pass and ovalid:
            top = sorted(ovalid, key=ovalid.get, reverse=True)[:KO_TOPK]
            # 절대모멘텀: 상위 K종 중 최근 KO_ABSMOM_WIN개월 수익 ≥ 0 인 것만 보유
            picks = [t for t in top if oabs.get(t, -1) >= 0]
            rec['offense_top'] = top          # 표시용: 점수 상위 K (필터 전)
            if picks:
                holds, defensive = picks, False
                names = ' · '.join(KO_TICKER_NAMES[t].split(' ', 1)[-1] for t in picks)
                dropped = [t for t in top if t not in picks]
                if dropped:
                    dn = ' · '.join(KO_TICKER_NAMES[t].split(' ', 1)[-1] for t in dropped)
                    reason = f"⚔️ 공격 · 상위{KO_TOPK} 중 {len(picks)}종 ({names}) [{KO_ABSMOM_WIN}M이격도<0 제외: {dn}]"
                else:
                    reason = f"⚔️ 공격 · 모멘텀 상위{len(picks)} ({names})"
            else:
                # 상위 K종이 전부 최근 N개월 하락 → 방어
                picks = sorted(dvalid, key=dvalid.get, reverse=True)[:KO_DEF_TOPK]
                holds, defensive = picks, True
                names = ' · '.join(KO_TICKER_NAMES[t].split(' ', 1)[-1] for t in picks)
                reason = f"🛡️ 방어 · {KO_DEF_WIN}M이격도 상위{len(picks)} ({names}) [공격 상위{KO_TOPK} 모두 {KO_ABSMOM_WIN}M이격도<0]"
        elif dvalid:
            picks = sorted(dvalid, key=dvalid.get, reverse=True)[:KO_DEF_TOPK]
            holds, defensive = picks, True
            names = ' · '.join(KO_TICKER_NAMES[t].split(' ', 1)[-1] for t in picks)
            trig = "TIP 필터 이탈" if not filter_pass else "공격 후보 없음"
            reason = f"🛡️ 방어 · {KO_DEF_WIN}M이격도 상위{len(picks)} ({names}) [{trig}]"
        else:
            rec.update({'holds': None, 'defensive': None, 'hold': None, 'reason': '보유 후보 없음'})
            rows.append(rec)
            continue

        rec['holds'] = holds
        rec['defensive'] = defensive
        rec['hold'] = ' · '.join(KO_TICKER_NAMES[t] for t in holds)
        rec['reason'] = reason
        # 표시용: 점수/순위 스냅샷
        rec['offense_rank'] = sorted(ovalid, key=ovalid.get, reverse=True)
        rec['offense_scores'] = ovalid
        rec['defense_scores'] = dvalid
        rows.append(rec)

    return pd.DataFrame(rows).set_index('signal_month', drop=False)


def run_backtest_ko(prices, signals, cost=0.0025):
    """또 ISA 백테스트. 공격 top3 / 방어 top2 모두 동일가중 바스켓.

    반환 bt는 compute_performance와 호환(cum_strategy/dd_strategy/ret_strategy 등).
    벤치마크는 KO_BENCHMARKS(KOSPI200=102110) 매수후보유.
    """
    months = list(prices.index)
    m_to_i = {m: i for i, m in enumerate(months)}
    records = []
    prev_w = {}

    for m in prices.index:
        i = m_to_i[m]
        if i + 1 >= len(months):
            break
        nm = months[i + 1]
        srow = signals.loc[str(m)] if str(m) in signals.index else None
        if srow is None:
            continue
        holds = srow['holds']
        if holds is None or (isinstance(holds, float) and pd.isna(holds)):
            continue

        w = 1.0 / len(holds)
        rets, w_new = [], {}
        for t in holds:
            p0 = prices.loc[m, t] if t in prices.columns else np.nan
            p1 = prices.loc[nm, t] if t in prices.columns else np.nan
            if pd.isna(p0) or pd.isna(p1) or p0 == 0:
                continue
            rets.append(p1 / p0 - 1.0)
            w_new[t] = w
        if not rets:
            continue
        ret_gross = float(np.mean(rets))
        bought = sum(max(w_new.get(t, 0.0) - prev_w.get(t, 0.0), 0.0)
                     for t in set(w_new) | set(prev_w))
        tc = cost * bought

        rec = {
            'signal_month': str(m), 'hold_month': str(nm),
            'defensive': bool(srow['defensive']),
            'hold': srow['hold'], 'reason': srow['reason'],
            'ret_gross': ret_gross, 'cost': tc, 'switched': bought > 1e-9,
            'ret_strategy': ret_gross - tc,
        }
        for b in KO_BENCHMARKS:
            if b in prices.columns:
                p0b, p1b = prices.loc[m, b], prices.loc[nm, b]
                rec[f'ret_{b}'] = (p1b / p0b - 1.0) if (pd.notna(p0b) and pd.notna(p1b) and p0b != 0) else np.nan
            else:
                rec[f'ret_{b}'] = np.nan
        records.append(rec)
        prev_w = w_new

    if not records:
        return pd.DataFrame()
    bt = pd.DataFrame(records)
    bt['cum_strategy'] = (1 + bt['ret_strategy']).cumprod()
    for b in KO_BENCHMARKS:
        bt[f'cum_{b}'] = (1 + bt[f'ret_{b}'].fillna(0)).cumprod()
    peak = bt['cum_strategy'].cummax().clip(lower=1.0)
    bt['dd_strategy'] = bt['cum_strategy'] / peak - 1.0
    return bt


# ==========================================================================
# 또 연금 (탭 5) — 듀얼모멘텀(나스닥/코스피) + 방어 바스켓
# ==========================================================================
#   · 공격: 나스닥100(133690) vs KOSPI200(102110) 중 6M 수익률 높은 1종
#   · 방어: 미국채10년·KRX금현물·WTI원유·리츠부동산 중 3M MA 이격도 1위 1종
#   · 위험회피: 나스닥100·KOSPI200 6M MA 이격도가 하나라도 음수면 방어
#   데이터는 data/snowball_kr/monthly/ (또 ISA와 공유 폴더).
# --------------------------------------------------------------------------
PEN_NASDAQ = '133690'    # TIGER 미국나스닥100 (환노출, 2010~ / FDR 2014~)
PEN_KOSPI = '102110'     # TIGER 200
PEN_OFFENSE = [PEN_NASDAQ, PEN_KOSPI]
PEN_DEFENSE = ['305080', '411060', '261220', '329200']
PEN_OFF_WIN = 6          # 공격: 6M 수익률
PEN_DEF_WIN = 3          # 방어: 3M MA 이격도
PEN_FILTER_WIN = 6       # 위험회피: 6M MA 이격도
PEN_BENCHMARKS = ['133690', '102110']

PEN_TICKER_NAMES = {
    '133690': 'TIGER 미국나스닥100', '102110': 'TIGER 200',
    '305080': 'TIGER 미국채10년선물', '411060': 'ACE KRX금현물',
    '261220': 'KODEX WTI원유선물(H)', '329200': 'TIGER 리츠부동산인프라',
}
PEN_ALL = list(dict.fromkeys(PEN_OFFENSE + PEN_DEFENSE))


@st.cache_data(ttl="1h", show_spinner=False)
def load_pen_prices(kr_dir='data/snowball_kr/monthly'):
    """또 연금용 6종 월봉 로드 (snowball_kr 폴더, 또 ISA 로더 인프라 재사용)."""
    def _pen_variants(code):
        nm = _ko_clean_name(PEN_TICKER_NAMES.get(code, code))
        return (f"{code}_{nm}_과거_데이터.csv", f"{code}_과거_데이터.csv", f"{code}.csv")

    series = {}
    for code in PEN_ALL:
        variants = _pen_variants(code)  # {code}_{name}_과거_데이터.csv 등
        s = None
        for fn in variants:
            s = _series_from_csv(_fetch_ko_raw_csv(fn))
            if s is not None and len(s) > 3:
                break
        if (s is None or len(s) <= 3) and os.path.isdir(kr_dir):
            norm = lambda x: re.sub(r'[\s_]+', '', x).lower()
            targets = {norm(v) for v in variants}
            for f in os.listdir(kr_dir):
                if f.lower().endswith('.csv') and norm(f) in targets:
                    try:
                        s = _series_from_csv(_read_csv_any_encoding(os.path.join(kr_dir, f)))
                        break
                    except Exception:
                        pass
        if s is not None:
            series[code] = s
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series).sort_index()
    return df[~df.index.duplicated(keep='last')]


def compute_signals_pension(prices):
    """또 연금 월별 신호·보유 계산.

    각 월 m에서:
      · 위험회피: 나스닥·코스피 6M MA 이격도가 하나라도 < 0 → 방어
      · 공격: 나스닥 vs 코스피 6M 수익률 높은 1종
      · 방어: 방어 4종(가용분) 중 3M MA 이격도 1위 1종
    종목별 상장 시점이 달라 방어는 '그 시점 가용 종목'만으로 선택(동적).
    """
    off = [t for t in PEN_OFFENSE if t in prices.columns]
    dfn = [t for t in PEN_DEFENSE if t in prices.columns]

    off_ret = prices[off] / prices[off].shift(PEN_OFF_WIN) - 1.0        # 공격 6M 수익률
    filt_disp = compute_ma_disparity(prices[off], PEN_FILTER_WIN)        # 위험회피 6M 이격도
    def_disp = compute_ma_disparity(prices[dfn], PEN_DEF_WIN) if dfn else None  # 방어 3M 이격도

    rows = []
    for m in prices.index:
        rec = {'signal_month': str(m)}
        fn = filt_disp.loc[m, PEN_NASDAQ] if PEN_NASDAQ in filt_disp.columns else np.nan
        fk = filt_disp.loc[m, PEN_KOSPI] if PEN_KOSPI in filt_disp.columns else np.nan
        rec['filt_nasdaq'] = fn
        rec['filt_kospi'] = fk
        if pd.isna(fn) or pd.isna(fk):
            rec.update({'holds': None, 'defensive': None, 'hold': None, 'reason': '데이터 준비중'})
            rows.append(rec)
            continue
        risk_off = (fn < 0) or (fk < 0)
        rec['risk_off'] = risk_off
        rec['filter_pass'] = not risk_off

        ovalid = {t: off_ret.loc[m, t] for t in off if pd.notna(off_ret.loc[m, t])}
        dvalid = ({t: def_disp.loc[m, t] for t in dfn if pd.notna(def_disp.loc[m, t])}
                  if def_disp is not None else {})
        rec['offense_scores'] = ovalid
        rec['defense_scores'] = dvalid

        if not risk_off and ovalid:
            pick = max(ovalid, key=ovalid.get)
            holds, defensive = [pick], False
            other = [t for t in ovalid if t != pick]
            reason = f"⚔️ 공격 · {PEN_TICKER_NAMES[pick]} (6M 수익률 우위)"
        elif dvalid:
            pick = max(dvalid, key=dvalid.get)
            holds, defensive = [pick], True
            trig = ("나스닥 6M 이격도<0" if fn < 0 else "") + (" · KOSPI 6M 이격도<0" if fk < 0 else "")
            trig = trig.strip(" ·") or "위험회피 발동"
            reason = f"🛡️ 방어 · {PEN_TICKER_NAMES[pick]} (3M 이격도 1위) [{trig}]"
        else:
            rec.update({'holds': None, 'defensive': None, 'hold': None, 'reason': '방어자산 없음(초기구간)'})
            rows.append(rec)
            continue

        rec['holds'] = holds
        rec['defensive'] = defensive
        rec['hold'] = PEN_TICKER_NAMES[pick]
        rec['reason'] = reason
        rows.append(rec)

    return pd.DataFrame(rows).set_index('signal_month', drop=False)


def run_backtest_pension(prices, signals, cost=0.0025):
    """또 연금 백테스트 (단일 종목 보유). compute_performance 호환 bt 반환."""
    months = list(prices.index)
    m_to_i = {m: i for i, m in enumerate(months)}
    records = []
    prev_w = {}
    for m in prices.index:
        i = m_to_i[m]
        if i + 1 >= len(months):
            break
        nm = months[i + 1]
        srow = signals.loc[str(m)] if str(m) in signals.index else None
        if srow is None:
            continue
        holds = srow['holds']
        if holds is None or (isinstance(holds, float) and pd.isna(holds)):
            continue
        pick = holds[0]
        p0 = prices.loc[m, pick] if pick in prices.columns else np.nan
        p1 = prices.loc[nm, pick] if pick in prices.columns else np.nan
        if pd.isna(p0) or pd.isna(p1) or p0 == 0:
            continue
        ret_gross = p1 / p0 - 1.0
        w_new = {pick: 1.0}
        bought = sum(max(w_new.get(t, 0.0) - prev_w.get(t, 0.0), 0.0)
                     for t in set(w_new) | set(prev_w))
        tc = cost * bought
        rec = {
            'signal_month': str(m), 'hold_month': str(nm),
            'defensive': bool(srow['defensive']),
            'hold': srow['hold'], 'reason': srow['reason'],
            'ret_gross': ret_gross, 'cost': tc, 'switched': bought > 1e-9,
            'ret_strategy': ret_gross - tc,
        }
        for b in PEN_BENCHMARKS:
            if b in prices.columns:
                p0b, p1b = prices.loc[m, b], prices.loc[nm, b]
                rec[f'ret_{b}'] = (p1b / p0b - 1.0) if (pd.notna(p0b) and pd.notna(p1b) and p0b != 0) else np.nan
            else:
                rec[f'ret_{b}'] = np.nan
        records.append(rec)
        prev_w = w_new

    if not records:
        return pd.DataFrame()
    bt = pd.DataFrame(records)
    bt['cum_strategy'] = (1 + bt['ret_strategy']).cumprod()
    for b in PEN_BENCHMARKS:
        bt[f'cum_{b}'] = (1 + bt[f'ret_{b}'].fillna(0)).cumprod()
    peak = bt['cum_strategy'].cummax().clip(lower=1.0)
    bt['dd_strategy'] = bt['cum_strategy'] / peak - 1.0
    return bt


# ==========================================================================
# 쏘 연금 (탭 6) — 나스닥 단일 공격 + 방어 바스켓 + cond1 위험회피
# ==========================================================================
#   · 공격: 미국나스닥100(133690) 100% (위험회피 미발동 시)
#   · 방어: 미국채10년(305080)·국고채10년(148070)·금현물(411060)·SOL초단기채(469830)
#           중 1+3+6+12M 수익률 합 1위 1종 100%
#   · 위험회피(cond1, 또 메리츠와 동일 신호): TIP·VWO·VEA·VIXY 6M 모두 음수
#           OR (TIP·VWO·VEA 6M 음수 & VIXY 6M ≥ +40%) → 방어로 전환
#   국내 ETF는 snowball_kr 폴더, cond1 신호자산(TIP/VWO/VEA/VIXY)은 미국 폴더에서 로드.
#   검증: CAGR 30.5% · MDD -13.7% · Sortino 3.62 · 공격비중 88% (2014-04~2026-05)
# --------------------------------------------------------------------------
SSOPEN_NASDAQ = '133690'          # TIGER 미국나스닥100 (환노출, FDR 2014~)
SSOPEN_DEFENSE = ['305080', '148070', '411060', '469830']
SSOPEN_DEF_WINDOWS = [1, 3, 6, 12]   # 방어 선택: 1+3+6+12M 수익률 합
SSOPEN_BENCHMARKS = ['133690']       # 나스닥100 매수후보유
SSOPEN_ALL = list(dict.fromkeys([SSOPEN_NASDAQ] + SSOPEN_DEFENSE))

SSOPEN_TICKER_NAMES = {
    '133690': 'TIGER 미국나스닥100', '305080': 'TIGER 미국채10년선물',
    '148070': 'KIWOOM 국고채10년', '411060': 'ACE KRX금현물',
    '469830': 'SOL 초단기채권액티브',
}


@st.cache_data(ttl="1h", show_spinner=False)
def load_ssopen_prices(kr_dir='data/snowball_kr/monthly'):
    """쏘 연금용 국내 ETF 5종 월봉 로드 (load_pen_prices와 동일 인프라 재사용).

    반환: DataFrame(index=YearMonth Period, columns=종목코드, values=월말 종가)
    cond1 신호자산(TIP/VWO/VEA/VIXY)은 별도로 load_monthly_prices()에서 받는다.
    """
    def _variants(code):
        nm = _ko_clean_name(SSOPEN_TICKER_NAMES.get(code, code))
        return (f"{code}_{nm}_과거_데이터.csv", f"{code}_과거_데이터.csv", f"{code}.csv")

    series = {}
    for code in SSOPEN_ALL:
        variants = _variants(code)
        s = None
        for fn in variants:
            s = _series_from_csv(_fetch_ko_raw_csv(fn))
            if s is not None and len(s) > 3:
                break
        if (s is None or len(s) <= 3) and os.path.isdir(kr_dir):
            norm = lambda x: re.sub(r'[\s_]+', '', x).lower()
            targets = {norm(v) for v in variants}
            for f in os.listdir(kr_dir):
                if f.lower().endswith('.csv') and norm(f) in targets:
                    try:
                        s = _series_from_csv(_read_csv_any_encoding(os.path.join(kr_dir, f)))
                        break
                    except Exception:
                        pass
        if s is not None:
            series[code] = s
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series).sort_index()
    return df[~df.index.duplicated(keep='last')]


def compute_signals_ssopen(prices, us_prices):
    """쏘 연금 월별 신호·보유 계산.

    Args:
        prices: 국내 ETF 월봉 (133690 + 방어 4종)
        us_prices: cond1 신호자산(TIP/VWO/VEA/VIXY) 포함 미국 ETF 월봉
                   (load_monthly_prices() 결과)

    각 월 m에서 (모두 m월 말 데이터 기준 — 미래참조 없음):
      · 위험회피(cond1): TIP·VWO·VEA 6M 모두 음수 AND (VIXY 6M 음수 OR VIXY 6M≥+40%)
      · 미발동 → 공격: 나스닥100(133690) 100%
      · 발동   → 방어: 방어 4종(가용분) 중 1+3+6+12M 수익률 합 1위 1종 100%
    cond1 신호자산 4종의 6M 수익률이 모두 확정된 달부터 신호를 낸다(readiness gate).
    방어자산은 상장시점이 달라 '그 시점 가용 종목'만으로 선택(동적).
    """
    # cond1 위험회피 (월별 bool) — 미국 신호자산 기준. 6M 수익률 원본도 표시용으로 보관.
    us_ret6 = compute_returns(us_prices, 6) if not us_prices.empty else pd.DataFrame()
    cond1 = compute_riskoff_cond1(us_prices) if not us_prices.empty else pd.Series(dtype=bool)

    # 방어 선택 점수: 1+3+6+12M 수익률 합 (한 창이라도 NaN이면 그 종목은 NaN → 12M 워밍업 필요)
    dfn = [t for t in SSOPEN_DEFENSE if t in prices.columns]
    def_sum = None
    if dfn:
        for w in SSOPEN_DEF_WINDOWS:
            r = compute_returns(prices[dfn], w)
            def_sum = r if def_sum is None else (def_sum + r)

    def _cond1_valid(m):
        """cond1 4종 6M 수익률이 그 달에 모두 확정됐는지."""
        if us_ret6.empty or m not in us_ret6.index:
            return False
        for t in SIGNAL_ASSETS:
            if t not in us_ret6.columns or pd.isna(us_ret6.loc[m, t]):
                return False
        return True

    rows = []
    for m in prices.index:
        rec = {'signal_month': str(m)}
        # cond1 6M 수익률 표시값
        for t in SIGNAL_ASSETS:
            rec[f'{t}_6m'] = (us_ret6.loc[m, t] if (not us_ret6.empty and m in us_ret6.index
                                                    and t in us_ret6.columns) else np.nan)
        # 나스닥 가격 없으면 신호 없음
        if SSOPEN_NASDAQ not in prices.columns or pd.isna(prices.loc[m, SSOPEN_NASDAQ]):
            rec.update({'holds': None, 'defensive': None, 'hold': None,
                        'risk_off': None, 'filter_pass': None, 'reason': '데이터 준비중'})
            rows.append(rec)
            continue
        # cond1 신호 미확정(초기 구간)이면 신호 없음
        if not _cond1_valid(m):
            rec.update({'holds': None, 'defensive': None, 'hold': None,
                        'risk_off': None, 'filter_pass': None, 'reason': 'cond1 데이터 준비중'})
            rows.append(rec)
            continue

        risk_off = bool(cond1.loc[m]) if m in cond1.index else False
        rec['risk_off'] = risk_off
        rec['filter_pass'] = not risk_off

        dvalid = ({t: def_sum.loc[m, t] for t in dfn if pd.notna(def_sum.loc[m, t])}
                  if def_sum is not None else {})
        rec['defense_scores'] = dvalid

        if not risk_off:
            pick, defensive = SSOPEN_NASDAQ, False
            reason = f"⚔️ 공격 · {SSOPEN_TICKER_NAMES[pick]} (cond1 미발동)"
        elif dvalid:
            pick, defensive = max(dvalid, key=dvalid.get), True
            reason = f"🛡️ 방어 · {SSOPEN_TICKER_NAMES[pick]} (1+3+6+12M 합 1위) [cond1 발동]"
        else:
            rec.update({'holds': None, 'defensive': None, 'hold': None,
                        'reason': '방어자산 없음(초기구간)'})
            rows.append(rec)
            continue

        rec['holds'] = [pick]
        rec['defensive'] = defensive
        rec['hold'] = SSOPEN_TICKER_NAMES[pick]
        rec['reason'] = reason
        rows.append(rec)

    return pd.DataFrame(rows).set_index('signal_month', drop=False)


def run_backtest_ssopen(prices, signals, cost=0.0025):
    """쏘 연금 백테스트 (단일 종목 보유). compute_performance 호환 bt 반환.

    신호월 m 말 결정 → 다음 달(m+1) 보유 → m→m+1 수익률 기록 (run_backtest_pension과 동일).
    벤치마크: 나스닥100(133690) 매수후보유.
    """
    months = list(prices.index)
    m_to_i = {m: i for i, m in enumerate(months)}
    records = []
    prev_w = {}
    for m in prices.index:
        i = m_to_i[m]
        if i + 1 >= len(months):
            break
        nm = months[i + 1]
        srow = signals.loc[str(m)] if str(m) in signals.index else None
        if srow is None:
            continue
        holds = srow['holds']
        if holds is None or (isinstance(holds, float) and pd.isna(holds)):
            continue
        pick = holds[0]
        p0 = prices.loc[m, pick] if pick in prices.columns else np.nan
        p1 = prices.loc[nm, pick] if pick in prices.columns else np.nan
        if pd.isna(p0) or pd.isna(p1) or p0 == 0:
            continue
        ret_gross = p1 / p0 - 1.0
        w_new = {pick: 1.0}
        bought = sum(max(w_new.get(t, 0.0) - prev_w.get(t, 0.0), 0.0)
                     for t in set(w_new) | set(prev_w))
        tc = cost * bought
        rec = {
            'signal_month': str(m), 'hold_month': str(nm),
            'defensive': bool(srow['defensive']),
            'hold': srow['hold'], 'reason': srow['reason'],
            'ret_gross': ret_gross, 'cost': tc, 'switched': bought > 1e-9,
            'ret_strategy': ret_gross - tc,
        }
        for b in SSOPEN_BENCHMARKS:
            if b in prices.columns:
                p0b, p1b = prices.loc[m, b], prices.loc[nm, b]
                rec[f'ret_{b}'] = (p1b / p0b - 1.0) if (pd.notna(p0b) and pd.notna(p1b) and p0b != 0) else np.nan
            else:
                rec[f'ret_{b}'] = np.nan
        records.append(rec)
        prev_w = w_new

    if not records:
        return pd.DataFrame()
    bt = pd.DataFrame(records)
    bt['cum_strategy'] = (1 + bt['ret_strategy']).cumprod()
    for b in SSOPEN_BENCHMARKS:
        bt[f'cum_{b}'] = (1 + bt[f'ret_{b}'].fillna(0)).cumprod()
    peak = bt['cum_strategy'].cummax().clip(lower=1.0)
    bt['dd_strategy'] = bt['cum_strategy'] / peak - 1.0
    return bt


# ==========================================================================
# 맘 비과세 (탭 7) — 글로벌 듀얼모멘텀 공격 + 방어 바스켓 + cond1 위험회피
# ==========================================================================
#   · 공격: 10종 중 12M 수익률 상위 4위 → 그중 12M 음수 종목은 제외하고
#           남은 '양수 모멘텀 승자'에 균등 재분배(듀얼모멘텀). 평소 4종 각 25%,
#           약세 브레스 땐 자동 집중.
#   · 방어: 6종 중 3M MA 이격도 상위 2위, 각 50% (cond1 발동 시).
#   · 위험회피(cond1, 쏘 연금과 동일): TIP·VWO·VEA·VIXY 6M.
#   · 티커: 신호·백테스트는 장수 종목(133690·102110·192090),
#           화면·실운용 표시는 별칭(379810·278530·192090).
#   검증: CAGR ~31% · MDD -12.8% · Sortino ~4.1 (2016-10~2026-05).
# --------------------------------------------------------------------------
MAMTAX_OFFENSE = ['466940', '371160', '192090', '453870', '241180',
                  '102110', '229200', '133690', '360750', '411060']
MAMTAX_DEFENSE = ['217770', '411060', '144600', '455030', '305080', '148070']
MAMTAX_OFF_WIN = 12   # 공격 선정·게이트: 12M 수익률 (상대+절대 모멘텀)
MAMTAX_DEF_WIN = 3    # 방어 선정: 3M MA 이격도
MAMTAX_TOP_OFF = 4
MAMTAX_TOP_DEF = 2
MAMTAX_BENCHMARKS = ['133690', '102110']   # 나스닥100·KOSPI200 매수후보유
# 백테스트(장수)↔실운용 티커 별칭: 신호·백테스트는 왼쪽(장수), 표시·매매는 오른쪽.
MAMTAX_LIVE_ALIAS = {'133690': '379810', '102110': '278530'}
MAMTAX_ALL = list(dict.fromkeys(MAMTAX_OFFENSE + MAMTAX_DEFENSE))

MAMTAX_TICKER_NAMES = {
    '466940': '은행고배당', '371160': 'TIGER 차이나항셍테크', '192090': 'TIGER 차이나CSI300',
    '453870': 'TIGER 인도니프티50', '241180': 'TIGER 일본니케이225',
    '102110': 'TIGER 200', '229200': 'KODEX 코스닥150', '133690': 'TIGER 미국나스닥100',
    '360750': 'TIGER 미국S&P500', '411060': 'ACE KRX금현물',
    '217770': 'TIGER WTI원유선물인버스(H)', '144600': 'KODEX 은선물(H)',
    '455030': 'KODEX 미국달러SOFR금리액티브', '305080': 'TIGER 미국채10년선물',
    '148070': 'KIWOOM 국고채10년',
    # 실운용 별칭 표시명
    '379810': 'KODEX 미국나스닥100', '278530': 'KODEX 200TR',
}


def mamtax_live_ticker(code):
    """백테스트 티커 → 실운용 티커 (별칭 없으면 그대로)."""
    return MAMTAX_LIVE_ALIAS.get(code, code)


def mamtax_live_name(code):
    """실운용 종목명 (별칭 반영)."""
    return MAMTAX_TICKER_NAMES.get(mamtax_live_ticker(code), code)


@st.cache_data(ttl="1h", show_spinner=False)
def load_mamtax_prices(kr_dir='data/snowball_kr/monthly'):
    """맘 비과세용 국내 ETF 월봉 로드 (공격 10 + 방어 6, 백테스트 티커).

    실운용 티커(379810·278530)는 신호 계산에 불필요하므로 여기서 안 받는다
    (엔진은 장수 티커로 계산하고 표시만 별칭으로 매핑).
    cond1 신호자산(TIP/VWO/VEA/VIXY)은 load_monthly_prices()에서 별도로 받는다.
    """
    def _variants(code):
        nm = _ko_clean_name(MAMTAX_TICKER_NAMES.get(code, code))
        return (f"{code}_{nm}_과거_데이터.csv", f"{code}_과거_데이터.csv", f"{code}.csv")

    series = {}
    for code in MAMTAX_ALL:
        variants = _variants(code)
        s = None
        for fn in variants:
            s = _series_from_csv(_fetch_ko_raw_csv(fn))
            if s is not None and len(s) > 3:
                break
        if (s is None or len(s) <= 3) and os.path.isdir(kr_dir):
            norm = lambda x: re.sub(r'[\s_]+', '', x).lower()
            targets = {norm(v) for v in variants}
            for f in os.listdir(kr_dir):
                if f.lower().endswith('.csv') and norm(f) in targets:
                    try:
                        s = _series_from_csv(_read_csv_any_encoding(os.path.join(kr_dir, f)))
                        break
                    except Exception:
                        pass
        if s is not None:
            series[code] = s
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series).sort_index()
    return df[~df.index.duplicated(keep='last')]


def compute_signals_mamtax(prices, us_prices):
    """맘 비과세 월별 신호·보유(가중) 계산.

    각 월 m에서 (모두 m월 말 데이터 기준 — 미래참조 없음):
      · 위험회피(cond1): TIP·VWO·VEA·VIXY 6M (쏘 연금과 동일).
      · 발동   → 방어: 6종 중 3M MA 이격도 상위 2위, 각 50%.
      · 미발동 → 공격: 10종 중 12M 수익률 상위 4위 → 12M 음수 제외 →
                 남은 승자에 균등 재분배(듀얼모멘텀).
    readiness: cond1 4종 6M 확정 AND 공격 12M 유효 4종 이상인 달부터 신호.
    holds는 {백테스트_티커: 비중} dict.
    """
    us_ret6 = compute_returns(us_prices, 6) if not us_prices.empty else pd.DataFrame()
    cond1 = compute_riskoff_cond1(us_prices) if not us_prices.empty else pd.Series(dtype=bool)

    offn = [t for t in MAMTAX_OFFENSE if t in prices.columns]
    defn = [t for t in MAMTAX_DEFENSE if t in prices.columns]
    off12 = compute_returns(prices[offn], MAMTAX_OFF_WIN) if offn else pd.DataFrame()
    def3 = compute_ma_disparity(prices[defn], MAMTAX_DEF_WIN) if defn else pd.DataFrame()

    def _cond1_valid(m):
        if us_ret6.empty or m not in us_ret6.index:
            return False
        for t in SIGNAL_ASSETS:
            if t not in us_ret6.columns or pd.isna(us_ret6.loc[m, t]):
                return False
        return True

    rows = []
    for m in prices.index:
        rec = {'signal_month': str(m)}
        for t in SIGNAL_ASSETS:
            rec[f'{t}_6m'] = (us_ret6.loc[m, t] if (not us_ret6.empty and m in us_ret6.index
                                                    and t in us_ret6.columns) else np.nan)
        offv = ({t: off12.loc[m, t] for t in offn if (m in off12.index and pd.notna(off12.loc[m, t]))}
                if not off12.empty else {})
        if not _cond1_valid(m) or len(offv) < MAMTAX_TOP_OFF:
            rec.update({'holds': None, 'defensive': None, 'risk_off': None,
                        'reason': '데이터 준비중', 'off_scores': offv, 'def_scores': {}})
            rows.append(rec)
            continue

        risk_off = bool(cond1.loc[m]) if m in cond1.index else False
        rec['risk_off'] = risk_off
        rec['off_scores'] = offv
        defv = ({t: def3.loc[m, t] for t in defn if (m in def3.index and pd.notna(def3.loc[m, t]))}
                if not def3.empty else {})
        rec['def_scores'] = defv

        if risk_off:
            if len(defv) < MAMTAX_TOP_DEF:
                rec.update({'holds': None, 'defensive': None, 'reason': '방어자산 부족(초기)'})
                rows.append(rec)
                continue
            picks = sorted(defv, key=defv.get, reverse=True)[:MAMTAX_TOP_DEF]
            holds = {t: 1.0 / len(picks) for t in picks}
            defensive = True
            reason = ("🛡️ 방어 · "
                      + ', '.join(MAMTAX_TICKER_NAMES.get(t, t) for t in picks)
                      + " (3M MA이격도 상위 2, cond1 발동)")
        else:
            ranked = sorted(offv, key=offv.get, reverse=True)[:MAMTAX_TOP_OFF]
            keep = [t for t in ranked if offv[t] >= 0]
            if keep:
                holds = {t: 1.0 / len(keep) for t in keep}   # 승자 재분배(듀얼모멘텀)
                defensive = False
                reason = ("⚔️ 공격 · "
                          + ', '.join(mamtax_live_name(t) for t in keep)
                          + f" (12M 수익률 상위·양수 {len(keep)}종 균등)")
            else:
                rec.update({'holds': None, 'defensive': None,
                            'reason': '공격 양수모멘텀 없음(관망)'})
                rows.append(rec)
                continue

        rec['holds'] = holds
        rec['defensive'] = defensive
        rec['reason'] = reason
        rows.append(rec)

    return pd.DataFrame(rows).set_index('signal_month', drop=False)


def run_backtest_mamtax(prices, signals, cost=0.0025):
    """맘 비과세 백테스트 (다종목 가중). compute_performance 호환 bt 반환.

    신호월 m 말 결정 → 다음 달(m+1) 보유 → m→m+1 수익률. 벤치마크: 나스닥100·KOSPI200.
    거래비용은 새로 매수하는 비중(턴오버)에만 부과.
    """
    months = list(prices.index)
    m_to_i = {m: i for i, m in enumerate(months)}
    records = []
    prev_w = {}
    for m in prices.index:
        i = m_to_i[m]
        if i + 1 >= len(months):
            break
        nm = months[i + 1]
        srow = signals.loc[str(m)] if str(m) in signals.index else None
        if srow is None:
            continue
        holds = srow['holds']
        if holds is None or (isinstance(holds, float) and pd.isna(holds)):
            continue
        ret_gross = 0.0
        ok = True
        for t, wt in holds.items():
            p0 = prices.loc[m, t] if t in prices.columns else np.nan
            p1 = prices.loc[nm, t] if t in prices.columns else np.nan
            if pd.isna(p0) or pd.isna(p1) or p0 == 0:
                ok = False
                break
            ret_gross += wt * (p1 / p0 - 1.0)
        if not ok:
            continue
        bought = sum(max(holds.get(t, 0.0) - prev_w.get(t, 0.0), 0.0)
                     for t in set(holds) | set(prev_w))
        tc = cost * bought
        hold_disp = ', '.join(f"{mamtax_live_name(t)} {holds[t] * 100:.0f}%" for t in holds)
        rec = {
            'signal_month': str(m), 'hold_month': str(nm),
            'defensive': bool(srow['defensive']),
            'hold': hold_disp, 'reason': srow['reason'],
            'ret_gross': ret_gross, 'cost': tc, 'switched': bought > 1e-9,
            'ret_strategy': ret_gross - tc,
        }
        for b in MAMTAX_BENCHMARKS:
            if b in prices.columns:
                p0b, p1b = prices.loc[m, b], prices.loc[nm, b]
                rec[f'ret_{b}'] = ((p1b / p0b - 1.0)
                                   if (pd.notna(p0b) and pd.notna(p1b) and p0b != 0) else np.nan)
            else:
                rec[f'ret_{b}'] = np.nan
        records.append(rec)
        prev_w = holds

    if not records:
        return pd.DataFrame()
    bt = pd.DataFrame(records)
    bt['cum_strategy'] = (1 + bt['ret_strategy']).cumprod()
    for b in MAMTAX_BENCHMARKS:
        bt[f'cum_{b}'] = (1 + bt[f'ret_{b}'].fillna(0)).cumprod()
    peak = bt['cum_strategy'].cummax().clip(lower=1.0)
    bt['dd_strategy'] = bt['cum_strategy'] / peak - 1.0
    return bt
