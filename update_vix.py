"""
update_vix.py — VIX(공포지수) 일별 데이터 자동 업데이트
=====================================================

매 거래일 실행되어 ^VIX 일봉을 받아 data/vix data.csv 를 갱신한다.
  형식: 날짜,종가,시가,고가,저가,변동 %  (기존 파일과 동일)

설계 원칙:
  - 안전 우선: 새 데이터를 못 받으면 기존 CSV를 절대 덮어쓰지 않는다.
  - 멱등성: 같은 날 여러 번 실행해도 결과 동일(해당 날짜 행 갱신).
  - 수집 소스: yfinance(^VIX) 우선, 실패 시 stooq 폴백.
"""

import os
import sys
import pandas as pd
import numpy as np

VIX_FILE = 'data/vix data.csv'
COLS = ['날짜', '종가', '시가', '고가', '저가', '변동 %']


# ==========================================
# VIX 수집 (yfinance 우선, stooq 폴백)
# ==========================================
def _format(df, date_col, o, h, l, c):
    out = pd.DataFrame({
        '날짜': pd.to_datetime(df[date_col]).dt.strftime('%Y-%m-%d'),
        '종가': pd.to_numeric(df[c], errors='coerce'),
        '시가': pd.to_numeric(df[o], errors='coerce'),
        '고가': pd.to_numeric(df[h], errors='coerce'),
        '저가': pd.to_numeric(df[l], errors='coerce'),
    }).dropna(subset=['종가', '고가']).reset_index(drop=True)
    chg = out['종가'].pct_change() * 100
    out['변동 %'] = chg.apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")
    return out[COLS]


def fetch_vix_yf(start='2004-01-01'):
    import yfinance as yf
    df = yf.download('^VIX', start=start, progress=False, auto_adjust=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    return _format(df, 'Date', 'Open', 'High', 'Low', 'Close')


def fetch_vix_stooq():
    url = 'https://stooq.com/q/d/l/?s=^vix&i=d'
    df = pd.read_csv(url)
    if df is None or df.empty or 'Close' not in df.columns:
        return None
    return _format(df, 'Date', 'Open', 'High', 'Low', 'Close')


def fetch_vix():
    for name, fn in [('yfinance', fetch_vix_yf), ('stooq', fetch_vix_stooq)]:
        try:
            s = fn()
            if s is not None and len(s) > 20:
                print(f"  ✅ {name}로 VIX {len(s)}행 수집 (최근 {s['날짜'].iloc[-1]} 고가 {s['고가'].iloc[-1]:.2f})")
                return s
            print(f"  ⚠️ {name}: 결과 부족")
        except Exception as e:
            print(f"  ⚠️ {name} 실패 ({type(e).__name__}: {e})")
    return None


# ==========================================
# 병합 (기존 이력 보존 + 새 데이터로 갱신)
# ==========================================
def load_existing():
    if not os.path.exists(VIX_FILE):
        return pd.DataFrame(columns=COLS)
    try:
        df = pd.read_csv(VIX_FILE, encoding='utf-8-sig')
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception as e:
        print(f"  ⚠️ 기존 VIX 파일 읽기 오류({e}) — 새 데이터만 사용")
        return pd.DataFrame(columns=COLS)


def merge(existing, new):
    """날짜 키로 병합. 새 데이터가 우선(덮어쓰기), 과거 이력 보존."""
    if existing is None or existing.empty:
        merged = new.copy()
    else:
        e = existing.copy()
        e['날짜'] = pd.to_datetime(e['날짜']).dt.strftime('%Y-%m-%d')
        both = pd.concat([e, new], ignore_index=True)
        both = both.drop_duplicates(subset='날짜', keep='last')
        merged = both
    merged = merged.sort_values('날짜').reset_index(drop=True)
    return merged[COLS]


# ==========================================
# 메인
# ==========================================
def main():
    print("📈 VIX 일별 업데이트 시작...")
    os.makedirs('data', exist_ok=True)
    new = fetch_vix()
    if new is None or new.empty:
        print("  ❌ VIX 수집 실패 → 기존 파일 보존, 종료")
        sys.exit(1)
    existing = load_existing()
    merged = merge(existing, new)
    merged.to_csv(VIX_FILE, index=False, encoding='utf-8-sig')
    print(f"  ✅ {VIX_FILE} 저장 ({len(merged)}행, 최신 {merged['날짜'].iloc[-1]} 고가 {float(merged['고가'].iloc[-1]):.2f})")
    print("✅ VIX 업데이트 완료")


if __name__ == '__main__':
    main()
