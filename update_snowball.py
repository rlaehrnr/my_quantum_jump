"""
update_snowball.py — 스노우볼 포트 데이터 자동 업데이트
========================================================

매월 말 실행되어 다음을 갱신:
1. ETF 11종 월봉 → data/snowball/monthly/{TICKER}_과거_데이터.csv
   - fdr 우선, 실패 시 yfinance 폴백
2. S&P 500 배당수익률 → data/snowball/monthly/SP500_DIV.csv
   - 여러 소스 폴백 체인. 전부 실패하면 기존 파일 보존.

설계 원칙:
- 안전 우선: 새 데이터를 못 받으면 기존 파일을 절대 덮어쓰지 않음.
- 기존 형식 유지: investing.com KR 형식("날짜","종가",...)과 호환.
- 멱등성: 같은 달 여러 번 실행해도 결과 동일 (해당 월 행 갱신/추가).
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

MONTHLY_DIR = 'data/snowball/monthly'

# 스노우볼 자산
#  · 기존(또 메리츠): TIP, VWO, VEA, VIXY, TQQQ, USD, GLD, TLT, SQQQ, SLV, SPY
#  · 신규(맘 삼성):   FAS, SOXL, TMF, IEF, TBT  (TQQQ, GLD, SPY, TIP은 위와 공유)
#  · 신규(쏘 삼성):   EWY, FDN, IBB, LIT, SMH, XLE, XLF  (SPY, QQQ, GLD, IEF는 공유)
CORE_TICKERS   = ['TIP', 'VWO', 'VEA', 'VIXY', 'TQQQ', 'USD', 'GLD', 'TLT', 'SQQQ', 'SLV', 'SPY']
SAMSUNG_TICKERS = ['FAS', 'SOXL', 'TMF', 'IEF', 'TBT']
# 쏘 삼성 공격 유니버스 (SPY는 CORE와 공유). QQQ는 벤치마크로 이미 저장소에 있으나
# 쏘 삼성 공격 후보이기도 하므로, 자동 갱신 대상에 포함해 최신 조정종가로 관리한다.
SO_TICKERS      = ['EWY', 'FDN', 'IBB', 'LIT', 'SMH', 'XLE', 'XLF', 'QQQ']

# 중복 제거하며 순서 유지한 전체 수집 대상
ALL_TICKERS = list(dict.fromkeys(CORE_TICKERS + SAMSUNG_TICKERS + SO_TICKERS))

# 💡 수정주가(배당·분할 반영 종가)로 받을 티커.
#    수정주가는 배당/분할 발생 시 과거 전체가 소급 재계산되므로 append가 아닌
#    "전체 재구성"이 맞다 (이 스크립트는 원래 매월 전 기간을 새로 받아 덮어씀).
#    자산배분 백테스트는 총수익(배당 재투자) 기준이 표준이고, 레버리지 ETF는
#    분할 미반영 시 가짜 급락이 생기므로 전 종목을 수정주가로 통일한다.
#    (배당·분할 없는 GLD/SLV는 수정가로 받아도 값이 사실상 동일 → 무해)
ADJUSTED_TICKERS = set(ALL_TICKERS)


# ==========================================
# ETF 월봉 수집
# ==========================================

def fetch_etf_fdr(ticker, start='2005-01-01', adjusted=False):
    """FinanceDataReader로 ETF 일봉 받아 월봉(월말 종가)으로 변환.

    adjusted=True면 'Adj Close'(수정종가)를 사용. FDR이 수정종가를 제공하지
    않으면 None을 반환해 상위 fetch_etf가 yfinance(auto_adjust) 폴백을 타게 한다.
    """
    import FinanceDataReader as fdr
    df = fdr.DataReader(ticker, start)
    if df is None or df.empty:
        return None
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    if adjusted:
        # 수정종가 컬럼이 있어야만 사용 (없으면 수정주가 보장 불가 → None 폴백)
        if 'Adj Close' in df.columns:
            col = 'Adj Close'
        else:
            return None
    else:
        if 'Close' not in df.columns:
            return None
        col = 'Close'
    # 월말 종가로 리샘플
    monthly = df[col].resample('ME').last().dropna()
    return monthly


def fetch_etf_yfinance(ticker, start='2005-01-01', adjusted=False):
    """yfinance 폴백. adjusted=True면 auto_adjust로 수정종가를 'Close'에 반영."""
    import yfinance as yf
    df = yf.download(ticker, start=start, progress=False, auto_adjust=adjusted)
    if df is None or df.empty:
        return None
    # auto_adjust=True → 'Close'가 이미 수정종가. False → 원시 종가.
    close = df['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    if getattr(close.index, 'tz', None) is not None:
        close.index = close.index.tz_localize(None)
    monthly = close.resample('ME').last().dropna()
    return monthly


def fetch_etf(ticker):
    """fdr 우선, 실패 시 yfinance. 둘 다 실패하면 None.

    수정주가 티커(ADJUSTED_TICKERS)는 수정 여부가 확실한 yfinance(auto_adjust)를
    우선 시도하고, FDR('Adj Close')을 폴백으로 둔다.
    """
    adjusted = ticker in ADJUSTED_TICKERS
    kind = '수정주가' if adjusted else '원시주가'
    if adjusted:
        order = [('yfinance', fetch_etf_yfinance), ('fdr', fetch_etf_fdr)]
    else:
        order = [('fdr', fetch_etf_fdr), ('yfinance', fetch_etf_yfinance)]
    for name, fn in order:
        try:
            s = fn(ticker, adjusted=adjusted)
            s = _drop_incomplete_month(s)   # 진행 중인 현재 달 제거 (완성월까지만)
            if s is not None and len(s) > 12:
                print(f"  ✅ {ticker}: {name}({kind})로 {len(s)}개월 수집 (최근 {s.index[-1].date()})")
                return s
            else:
                print(f"  ⚠️ {ticker}: {name} 결과 부족")
        except Exception as e:
            print(f"  ⚠️ {ticker}: {name} 실패 ({type(e).__name__}: {e})")
    return None


def _drop_incomplete_month(monthly_series, today=None):
    """진행 중(미완성)인 현재 달 행을 제거한다.

    resample('ME')는 각 달의 마지막 거래일 값을 '그 달 말일' 날짜로 라벨링한다.
    예: 7월 2일에 실행하면 7/1~7/2 부분 데이터가 '2026-07-31' 행으로 저장됨 →
    아직 끝나지 않은 달이 '완성월'인 것처럼 들어가 신호·백테스트를 왜곡할 수 있다.

    규칙: '완전히 종료된 달'(월말 라벨이 이번 달 1일보다 이전)만 유지.
          → 실행 시점이 속한 현재 달은 항상 버린다. 매월 1일에 실행하면
            직전 달이 자동으로 최신 완성월이 된다.
    """
    if monthly_series is None or len(monthly_series) == 0:
        return monthly_series
    if today is None:
        today = pd.Timestamp.today()
    current_month_start = today.normalize().replace(day=1)
    return monthly_series[monthly_series.index < current_month_start]


def save_etf_csv(ticker, monthly_series):
    """
    월봉 Series를 CSV로 저장. 형식: "날짜","종가"

    snowball.py는 종가만 사용하므로 시가/고가/저가/거래량/변동% 더미 컬럼은
    저장하지 않는다(파일 경량화, 혼동 방지).
    """
    df = pd.DataFrame({
        '날짜': monthly_series.index.strftime('%Y-%m-%d'),
        '종가': monthly_series.values.round(2),
    })
    # 최신이 위로 (investing.com 관행 유지)
    df = df.iloc[::-1].reset_index(drop=True)
    path = os.path.join(MONTHLY_DIR, f"{ticker}_과거_데이터.csv")
    df.to_csv(path, index=False, encoding='utf-8-sig')
    return path


def update_all_etfs():
    """모든 ETF 갱신. 실패한 ticker는 기존 파일 유지."""
    print("📈 ETF 월봉 데이터 수집 시작...")
    ok, fail = [], []
    for ticker in ALL_TICKERS:
        s = fetch_etf(ticker)
        if s is not None:
            save_etf_csv(ticker, s)
            ok.append(ticker)
        else:
            fail.append(ticker)
            print(f"  ❌ {ticker}: 수집 실패 → 기존 파일 유지")
    print(f"📈 ETF 완료: 성공 {len(ok)}개, 실패 {len(fail)}개")
    if fail:
        print(f"   실패 목록: {fail}")
    return ok, fail


# ==========================================
# S&P 500 배당수익률 수집 (폴백 체인)
# ==========================================

def _http_get(url, timeout=20):
    import requests
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.google.com/',
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def fetch_div_multpl():
    """
    multpl.com에서 월별 배당수익률 테이블 파싱.
    Returns: Series(index=Timestamp(월말), values=배당%) 또는 None
    """
    from bs4 import BeautifulSoup
    html = _http_get("https://www.multpl.com/s-p-500-dividend-yield/table/by-month")
    soup = BeautifulSoup(html, 'lxml')
    table = soup.find('table', id='datatable')
    if not table:
        return None
    records = []
    for tr in table.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all('td')]
        if len(cells) >= 2:
            date_str, val_str = cells[0], cells[1]
            try:
                date = pd.to_datetime(date_str)
                val = float(val_str.replace('%', '').replace('†', '').replace('estimate', '').strip())
                records.append((date, val))
            except (ValueError, TypeError):
                continue
    if not records:
        return None
    s = pd.Series({d: v for d, v in records}).sort_index()
    return s


def fetch_div_dqydj():
    """
    dqydj.com에서 배당수익률 파싱 (테이블 또는 임베디드 데이터).
    Returns: Series 또는 None
    """
    from bs4 import BeautifulSoup
    html = _http_get("https://dqydj.com/sp-500-dividend-yield/")
    soup = BeautifulSoup(html, 'lxml')
    # dqydj는 테이블 형태로 제공
    for table in soup.find_all('table'):
        records = []
        for tr in table.find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all('td')]
            if len(cells) >= 2:
                try:
                    date = pd.to_datetime(cells[0])
                    val = float(cells[1].replace('%', '').strip())
                    records.append((date, val))
                except (ValueError, TypeError):
                    continue
        if len(records) > 12:  # 충분한 데이터가 있는 테이블
            return pd.Series({d: v for d, v in records}).sort_index()
    return None


def update_dividend():
    """
    배당수익률 갱신. 폴백 체인으로 시도.
    전부 실패하면 기존 파일 보존 (False 반환).
    성공하면 기존 데이터와 병합 후 저장 (True 반환).
    """
    print("💰 S&P 500 배당수익률 수집 시작...")
    
    new_series = None
    for name, fn in [('multpl', fetch_div_multpl), ('dqydj', fetch_div_dqydj)]:
        try:
            s = fn()
            if s is not None and len(s) > 0:
                print(f"  ✅ {name}로 {len(s)}개 데이터 수집 (최근 {s.index[-1].date()}={s.iloc[-1]}%)")
                new_series = s
                break
            else:
                print(f"  ⚠️ {name}: 데이터 없음")
        except Exception as e:
            print(f"  ⚠️ {name} 실패 ({type(e).__name__}: {e})")
    
    if new_series is None:
        print("  ❌ 모든 배당 소스 실패 → 기존 SP500_DIV.csv 보존")
        return False
    
    # 기존 파일과 병합 (기존 과거 데이터 보존 + 새 데이터로 갱신)
    path_csv = os.path.join(MONTHLY_DIR, 'SP500_DIV.csv')
    path_xlsx = os.path.join(MONTHLY_DIR, 'SP500_DIV.xlsx')
    
    existing = None
    try:
        if os.path.isfile(path_xlsx):
            edf = pd.read_excel(path_xlsx)
            existing = _parse_existing_div(edf)
        elif os.path.isfile(path_csv):
            edf = pd.read_csv(path_csv, encoding='utf-8-sig')
            existing = _parse_existing_div(edf)
    except Exception as e:
        print(f"  ⚠️ 기존 배당 파일 읽기 실패 ({e}) — 새 데이터만 사용")
    
    # 월 단위로 병합 (새 데이터 우선)
    new_monthly = new_series.copy()
    new_monthly.index = pd.to_datetime(new_monthly.index).to_period('M')
    new_monthly = new_monthly[~new_monthly.index.duplicated(keep='last')]
    
    if existing is not None and len(existing) > 0:
        existing.index = pd.to_datetime(existing.index).to_period('M')
        existing = existing[~existing.index.duplicated(keep='last')]
        # 기존을 베이스로, 새 데이터로 덮어쓰기 (combine_first 반대 방향)
        merged = new_monthly.combine_first(existing).sort_index()
    else:
        merged = new_monthly.sort_index()
    
    # 저장 (CSV, 간단 형식: 날짜, 종가)
    out = pd.DataFrame({
        '날짜': merged.index.to_timestamp('M').strftime('%Y-%m-%d'),
        '종가': merged.values.round(2),
    })
    out = out.iloc[::-1].reset_index(drop=True)  # 최신이 위로
    out.to_csv(path_csv, index=False, encoding='utf-8-sig')
    print(f"  ✅ SP500_DIV.csv 저장 ({len(out)}개월, 최신 {out['날짜'].iloc[0]}={out['종가'].iloc[0]}%)")
    return True


def _parse_existing_div(df):
    """기존 배당 파일(xlsx/csv)에서 (월말 날짜, 값) Series 추출."""
    import re
    # 날짜 컬럼
    date_col = '날짜' if '날짜' in df.columns else ('Date' if 'Date' in df.columns else df.columns[0])
    # 값 컬럼: Unnamed:2(깨끗한 숫자) 우선
    val_col = None
    for c in ['Unnamed: 2', '종가', 'Value', 'value', 'DividendYield']:
        if c in df.columns:
            val_col = c
            break
    if val_col is None and len(df.columns) >= 2:
        val_col = df.columns[1]
    
    def parse_pct(x):
        if pd.isna(x):
            return np.nan
        if isinstance(x, (int, float)):
            return float(x)
        m = re.search(r'([\d.]+)', str(x))
        return float(m.group(1)) if m else np.nan
    
    dates = pd.to_datetime(df[date_col], errors='coerce')
    vals = df[val_col].apply(parse_pct)
    s = pd.Series(vals.values, index=dates).dropna()
    return s


# ==========================================
# 메인
# ==========================================

def main():
    print("=" * 60)
    print(f"🚀 스노우볼 데이터 자동 업데이트 시작 — {datetime.now()}")
    print("=" * 60)
    
    os.makedirs(MONTHLY_DIR, exist_ok=True)
    
    etf_ok, etf_fail = update_all_etfs()
    print()
    div_ok = update_dividend()
    
    print()
    print("=" * 60)
    print(f"📊 요약: ETF {len(etf_ok)}/{len(ALL_TICKERS)} 성공, 배당 {'성공' if div_ok else '실패(기존 유지)'}")
    print("=" * 60)
    
    # ETF가 절반 이상 실패하면 비정상 종료 (Actions에서 알림)
    if len(etf_fail) > len(ALL_TICKERS) // 2:
        print("❌ ETF 수집 실패가 과반 — 비정상 상황")
        sys.exit(1)


if __name__ == "__main__":
    main()
