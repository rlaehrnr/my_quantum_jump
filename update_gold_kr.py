"""
🥇 KRX 금(환노출) 최신 시세 수집기 — GitHub Actions 일별 갱신용.

목적:
  data/krx_gold_price.csv (KRX 금현물 스팟, 과거 히스토리)는 수동 파일이라 특정일에서 멈춰 있음.
  그 이후 구간을 '실제 KRX 금값'으로 계속 잇기 위해, KRX 금시장에 연동된 실물 ETF
  411060(ACE KRX금현물, 환노출)의 일별 종가를 받아 data/krx_gold_recent.csv로 저장한다.
  → utils/calculator.py:get_gold_krw_daily() 가 이 파일을 raw URL로 읽어 스팟 CSV 뒤에 이어붙임
    (접합점 레벨 비율보정). 전략은 '수익률'만 쓰므로 스팟 vs ETF 단위 차이는 무영향.

소스 우선순위 (둘 다 Actions에서 동작):
  1) FDR  fdr.DataReader('411060')   ← 기존 KR 파이프라인과 동일 백엔드(KS11 등 검증됨)
  2) yfinance  '411060.KS'           ← FDR 실패 시 폴백

안전장치:
  - 데이터 수신 실패 시 기존 파일을 '덮어쓰지 않고' 종료(0행으로 밀지 않음).
  - 새 데이터 행수가 기존의 90% 미만이면(소스 이상 의심) 보존.
출력 컬럼: 날짜(YYYY-MM-DD), 종가   (utf-8-sig)
"""
import os
import pandas as pd

GOLD_ETF = '411060'                     # ACE KRX금현물 (환노출, KRX 금현물 실물)
OUT_PATH = 'data/krx_gold_recent.csv'
START = '2019-01-01'                     # 411060 상장(2021) 이전은 자동으로 빈 구간 → 무관


def _from_fdr():
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(GOLD_ETF, START)
        if df is not None and not df.empty and 'Close' in df.columns:
            s = pd.to_numeric(df['Close'], errors='coerce').dropna()
            s = s[s > 0]
            if not s.empty:
                s.index = pd.to_datetime(s.index)
                print(f"  · FDR('{GOLD_ETF}') 수신: {len(s)}행")
                return s
    except Exception as e:
        print(f"  · FDR 실패: {e}")
    return None


def _from_yfinance():
    try:
        import yfinance as yf
        h = yf.Ticker(f"{GOLD_ETF}.KS").history(start=START, auto_adjust=False)
        if h is not None and not h.empty and 'Close' in h.columns:
            s = pd.to_numeric(h['Close'], errors='coerce').dropna()
            if s.index.tz is not None:
                s.index = s.index.tz_localize(None)
            s = s[s > 0]
            if not s.empty:
                s.index = pd.to_datetime(s.index)
                print(f"  · yfinance('{GOLD_ETF}.KS') 수신: {len(s)}행")
                return s
    except Exception as e:
        print(f"  · yfinance 실패: {e}")
    return None


def main():
    print(f"🥇 KRX 금 ETF({GOLD_ETF}) 수집 시작")
    s = _from_fdr()
    if s is None or s.empty:
        s = _from_yfinance()

    if s is None or s.empty:
        print("❌ 두 소스 모두 실패 — 기존 파일 보존(덮어쓰기 안 함).")
        return

    s = s.sort_index()
    out = pd.DataFrame({
        '날짜': s.index.strftime('%Y-%m-%d'),
        '종가': s.values.astype(float),
    }).drop_duplicates('날짜', keep='last').sort_values('날짜').reset_index(drop=True)

    # 급감 방어: 기존 대비 행수가 크게 줄면 보존
    if os.path.exists(OUT_PATH):
        try:
            old = pd.read_csv(OUT_PATH, encoding='utf-8-sig')
            if len(out) < len(old) * 0.9:
                print(f"⚠️ 새 데이터({len(out)}행)가 기존({len(old)}행)보다 급감 → 보존.")
                return
        except Exception:
            pass

    os.makedirs('data', exist_ok=True)
    out.to_csv(OUT_PATH, index=False, encoding='utf-8-sig')
    print(f"✅ {OUT_PATH} 갱신: {len(out)}행, 최신 {out['날짜'].iloc[-1]} "
          f"종가 {out['종가'].iloc[-1]:,.1f}")


if __name__ == '__main__':
    main()
