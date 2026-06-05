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
SIGNAL_ASSETS = ['TIP', 'VWO', 'EFA', 'VIXY']

# 공격 자산 (12개월 모멘텀 비교)
OFFENSE_ASSETS = ['TQQQ', 'USD']

# 방어 자산 (11개월 모멘텀 비교)
DEFENSE_ASSETS = ['GLD', 'TLT', 'SQQQ', 'SLV']

# 벤치마크
BENCHMARK = 'SPY'

# 모든 ETF 티커
ALL_TICKERS = SIGNAL_ASSETS + OFFENSE_ASSETS + DEFENSE_ASSETS + [BENCHMARK]

# CSH (현금 식별자)
CASH = 'CASH'


# ==========================================
# 데이터 로딩
# ==========================================

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
    if not os.path.isdir(monthly_dir):
        return pd.DataFrame()
    
    # 폴더의 모든 CSV 파일 스캔
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
    
    frames = []
    missing = []
    
    for ticker in ALL_TICKERS:
        found = _find_file(ticker)
        
        if found is None:
            missing.append(ticker)
            continue
        
        try:
            # BOM 포함 utf-8 시도, 실패 시 cp949
            try:
                df = pd.read_csv(found, encoding='utf-8-sig')
            except UnicodeDecodeError:
                df = pd.read_csv(found, encoding='cp949')
            
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
    if not os.path.isdir(monthly_dir):
        return pd.Series(dtype=float)
    
    # 파일명 자동 탐색 (.csv 또는 .xlsx)
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
            try:
                df = pd.read_csv(path, encoding='utf-8-sig')
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding='cp949')
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
        # 하위 10% 경계값 (이 값 이하이면 백분위 10% 이내에 해당)
        thr.iloc[i] = np.quantile(valid, 0.10)
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
            'ret6_TIP','ret6_VWO','ret6_EFA','ret6_VIXY',
            'ret11_GLD','ret11_TLT','ret11_SQQQ','ret11_SLV',
            'ret12_TQQQ','ret12_USD',
            'hold',  # 보유 종목 티커 (또는 'CASH')
            'reason',  # 판정 사유 텍스트
        ]
    """
    ret6 = compute_returns(prices, 6)
    ret11 = compute_returns(prices, 11)
    ret12 = compute_returns(prices, 12)
    
    # 💡 [명세서 §5 시작 조건] 각 월이 백테스트 가능한지 판정.
    # 다음이 모두 계산 가능(NaN 아님)해야 그 달의 신호가 유효:
    #   - 신호 4종(TIP/VWO/EFA/VIXY) 6M 수익률
    #   - 방어 4종(GLD/TLT/SQQQ/SLV) 11M 수익률
    #   - 공격 2종(TQQQ/USD) 12M 수익률
    # (배당 60개월 백분위는 워밍업 전이면 cond2=False로 처리하고 진행 — 명세서 §5)
    ready_cols_6 = [t for t in SIGNAL_ASSETS if t in ret6.columns]
    ready_cols_11 = [t for t in DEFENSE_ASSETS if t in ret11.columns]
    ready_cols_12 = [t for t in OFFENSE_ASSETS if t in ret12.columns]
    
    data_ready = pd.Series(True, index=prices.index)
    if ready_cols_6:
        data_ready &= ret6[ready_cols_6].notna().all(axis=1)
    if ready_cols_11:
        data_ready &= ret11[ready_cols_11].notna().all(axis=1)
    if ready_cols_12:
        data_ready &= ret12[ready_cols_12].notna().all(axis=1)
    # 필수 자산 컬럼 자체가 누락이면 전부 False
    if len(ready_cols_6) < len(SIGNAL_ASSETS) or len(ready_cols_11) < len(DEFENSE_ASSETS) or len(ready_cols_12) < len(OFFENSE_ASSETS):
        data_ready &= False
    
    # cond1: 신호자산 4종 모두 6M < 0
    cond1 = pd.Series(False, index=prices.index)
    if all(t in ret6.columns for t in SIGNAL_ASSETS):
        cond1 = (ret6[SIGNAL_ASSETS] < 0).all(axis=1)
    
    # cond2: 배당 5년 롤링 백분위 ≤ 10%
    if not div_yield.empty:
        # 인덱스 정렬
        div_aligned = div_yield.reindex(prices.index)
        div_pct, div_thr, div_rank, div_total = compute_div_percentile(div_aligned, window=60, min_pct=0.8)
        cond2 = (div_pct <= 10).fillna(False)
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
            # 방어 모드: 4종 ret11 비교
            ret11_vals = {t: ret11[t].loc[m] for t in DEFENSE_ASSETS if t in ret11.columns}
            if not ret11_vals or any(pd.isna(v) for v in ret11_vals.values()):
                holds.append(None)
                reasons.append("데이터 부족")
                continue
            # 모두 ≤ 0이면 현금
            if all(v <= 0 for v in ret11_vals.values()):
                holds.append(CASH)
                reason = "방어모드 & 4종 11M ≤0 → 현금"
            else:
                best = max(ret11_vals, key=ret11_vals.get)
                holds.append(best)
                reason = f"방어모드 → {best} (11M={ret11_vals[best]*100:.1f}%)"
            
            cause = []
            if cond1_m: cause.append("cond1(4종 6M<0)")
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
        if t in ret11.columns:
            sig[f'ret11_{t}'] = ret11[t]
    for t in OFFENSE_ASSETS:
        if t in ret12.columns:
            sig[f'ret12_{t}'] = ret12[t]
    
    return sig


# ==========================================
# 백테스트
# ==========================================

def run_backtest(prices, signals):
    """
    명세서 §5 — 월별 백테스트 루프.
    
    신호월 m의 신호로 m+1(보유월) 한 달 보유.
    수익률 = price[hold][m+1] / price[hold][m] - 1
    
    Args:
        prices: DataFrame, monthly close
        signals: DataFrame from compute_signals
    
    Returns:
        DataFrame, index=보유월(nm), columns=[
            'signal_month', 'defensive', 'hold', 'reason',
            'ret_strategy', 'ret_spy', 'cum_strategy', 'cum_spy', 'dd_strategy'
        ]
    """
    months = list(prices.index)
    records = []
    
    for i, m in enumerate(months[:-1]):
        nm = months[i+1]
        hold = signals.loc[m, 'hold']
        defensive = bool(signals.loc[m, 'defensive'])
        reason = signals.loc[m, 'reason']
        
        if hold is None:
            # 데이터 부족 → skip
            continue
        
        if hold == CASH:
            ret_strat = 0.0
        else:
            p0 = prices.loc[m, hold] if hold in prices.columns else np.nan
            p1 = prices.loc[nm, hold] if hold in prices.columns else np.nan
            if pd.isna(p0) or pd.isna(p1) or p0 == 0:
                continue
            ret_strat = p1 / p0 - 1.0
        
        # SPY 벤치마크
        if BENCHMARK in prices.columns:
            p0s = prices.loc[m, BENCHMARK]
            p1s = prices.loc[nm, BENCHMARK]
            ret_spy = (p1s / p0s - 1.0) if (pd.notna(p0s) and pd.notna(p1s) and p0s != 0) else np.nan
        else:
            ret_spy = np.nan
        
        records.append({
            'signal_month': str(m),
            'hold_month': str(nm),
            'defensive': defensive,
            'hold': hold,
            'reason': reason,
            'ret_strategy': ret_strat,
            'ret_spy': ret_spy,
        })
    
    if not records:
        return pd.DataFrame()
    
    bt = pd.DataFrame(records)
    bt['cum_strategy'] = (1 + bt['ret_strategy']).cumprod()
    bt['cum_spy'] = (1 + bt['ret_spy'].fillna(0)).cumprod()
    bt['dd_strategy'] = bt['cum_strategy'] / bt['cum_strategy'].cummax() - 1.0
    
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
    mdd = bt['dd_strategy'].min()
    win_rate = (rets > 0).mean()
    offense_pct = (~bt['defensive']).mean()
    offense_months = int((~bt['defensive']).sum())
    
    # SPY 비교
    spy_cum = bt['cum_spy'].iloc[-1]
    spy_cagr = spy_cum ** (12.0/n) - 1.0 if spy_cum > 0 else -1.0
    spy_dd = (bt['cum_spy'] / bt['cum_spy'].cummax() - 1.0).min()
    spy_std = bt['ret_spy'].std(ddof=0)
    spy_vol = spy_std * np.sqrt(12)
    spy_sharpe = (bt['ret_spy'].mean() / spy_std * np.sqrt(12)) if spy_std > 0 else 0.0
    
    return {
        'n_months': n,
        'cum_return': cum - 1.0,
        'cagr': cagr,
        'vol': vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'win_rate': win_rate,
        'offense_pct': offense_pct,
        'offense_months': offense_months,
        'spy_cum_return': spy_cum - 1.0,
        'spy_cagr': spy_cagr,
        'spy_mdd': spy_dd,
        'spy_vol': spy_vol,
        'spy_sharpe': spy_sharpe,
    }
