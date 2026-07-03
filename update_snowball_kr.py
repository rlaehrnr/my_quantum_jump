"""
update_snowball_kr.py — 스노우볼 '코 삼성'(국내 ETF) 데이터 자동 업데이트
========================================================================

매월 말 실행되어 국내 상장 ETF 월봉을 갱신:
  data/snowball_kr/monthly/{종목코드}_과거_데이터.csv   (형식: "날짜","종가")

미국판(update_snowball.py)과 완전 분리:
  - 저장 폴더가 다름 (snowball_kr)
  - 수집 소스가 다름 (국내 ETF는 야후에 없음 → FinanceDataReader 우선)
  - 미국 파이프라인/데이터는 전혀 건드리지 않음

설계 원칙 (미국판과 동일):
  - 안전 우선: 새 데이터를 못 받으면 기존 파일을 절대 덮어쓰지 않음.
  - 형식 유지: "날짜","종가" 2컬럼, 최신이 위로 (investing.com 관행).
  - 멱등성: 같은 달 여러 번 실행해도 결과 동일.
  - 미완성월 제거: 진행 중인 현재 달은 버리고 '완성월'까지만 저장.

⚠️ 분배금(배당) 조정:
  FDR의 국내 ETF 종가가 분배금 재투자(총수익) 기준인지는 종목마다 다를 수 있다.
  자산배분 백테스트는 총수익 기준이 표준이나, 국내 ETF는 분배가 크지 않아 영향이
  제한적이다. 우선 FDR 기본 종가로 수집하고, 필요 시 추후 보정한다.

필터용 TIP(미국 물가연동채)은 미국판이 이미 data/snowball/monthly/ 에 자동 갱신하므로
여기서 수집하지 않는다(페이지 로더가 그 폴더에서 읽음).
"""

import os
import sys
import pandas as pd
import numpy as np

MONTHLY_DIR = 'data/snowball_kr/monthly'

# ==========================================
# 코 삼성 국내 ETF 유니버스 (종목코드 → 이름은 주석/로그용)
# ==========================================
# 공격 10종 (1+3+6+12개월 수익률 합 상위 3위 동일가중)
OFFENSE_TICKERS = [
    '379810',  # KODEX 미국나스닥100
    '309230',  # ACE 미국WideMoat가치주
    '360750',  # TIGER 미국S&P500
    '102110',  # TIGER 200 (코스피200)
    '130730',  # KOSEF 단기자금 (현금성)
    '152380',  # KODEX 국채선물10년
    '332620',  # ARIRANG 미국장기우량회사채
    '411060',  # ACE KRX금현물
    '137610',  # TIGER 농산물선물Enhanced(H)
    '182480',  # TIGER 미국MSCI리츠(합성 H)
]
# 방어 3종 (1개월 수익률 상위 1·2위 매수, 50:50)
DEFENSE_TICKERS = [
    '217770',  # TIGER WTI원유선물인버스(H)
    '225130',  # ACE 골드선물 레버리지(합성 H)
    '455030',  # KODEX 미국달러SOFR금리액티브(합성)
]

# ── 2번 전략(듀얼모멘텀: 나스닥/코스피 + 방어바스켓)용 추가 종목 ──
#    나스닥100은 133690(TIGER, 2010 상장)으로 대체 — 역사가 길어 백테스트 유리
#    (102110·411060은 위에서 이미 수집)
STRATEGY2_TICKERS = [
    '133690',  # TIGER 미국나스닥100 (환노출, 2010~) ← 379810 대체
    '305080',  # TIGER 미국채10년선물
    '261220',  # KODEX WTI원유선물(H)
    '329200',  # TIGER 리츠부동산인프라 (한국 리츠)
]

# ── 3번 전략(쏘 연금: 나스닥 + 채권/금 방어 + cond1 위험회피)용 추가 종목 ──
#    공격 133690·방어 305080·411060은 위에서 이미 수집. 위험회피(TIP/VWO/VEA/VIXY)는 미국 폴더.
STRATEGY3_TICKERS = [
    '148070',  # KIWOOM 국고채10년 (2011~)
    '469830',  # SOL 초단기채권액티브 (2023~, 현금성)
]

# ── 4번 전략(맘 비과세: 글로벌 모멘텀 공격 + 방어바스켓 + cond1)용 추가 종목 ──
#    360750(S&P500)·379810(나스닥100)·411060(금현물)·217770(원유인버스)·455030(SOFR)·
#    305080(미국채10년)·148070(국고채10년)은 위에서 이미 수집. 아래는 신규 8종.
#    ⚠️ 인도니프티50(2023~)·은행고배당 등 상장이 최근이라 히스토리 짧음 → 백테스트 시작 늦음.
MAMTAX_TICKERS = [
    '466940',  # 은행고배당
    '371160',  # TIGER 차이나항셍테크
    '192090',  # TIGER 차이나CSI300 (2014~, 283580 장수 대체)
    '453870',  # TIGER 인도니프티50
    '241180',  # TIGER 일본니케이225
    '229200',  # KODEX 코스닥150
    '144600',  # KODEX 은선물(H)
]
# 나스닥100은 133690(2014~), KOSPI200은 102110 TIGER200(2014~) — 둘 다 이미 수집돼
# 엔진에서 그대로 사용(각각 379810·278530의 장수 대체). 여기서 재수집 불필요.

# 종목명 (로그 출력용)
TICKER_NAMES = {
    '379810': 'KODEX 미국나스닥100', '309230': 'ACE 미국WideMoat가치주',
    '360750': 'TIGER 미국S&P500', '102110': 'TIGER 200',
    '130730': 'KOSEF 단기자금', '152380': 'KODEX 국채선물10년',
    '332620': 'ARIRANG 미국장기우량회사채', '411060': 'ACE KRX금현물',
    '137610': 'TIGER 농산물선물Enhanced(H)', '182480': 'TIGER 미국MSCI리츠(합성H)',
    '217770': 'TIGER WTI원유선물인버스(H)', '225130': 'ACE 골드선물레버리지(합성H)',
    '455030': 'KODEX 미국달러SOFR금리액티브',
    # 2번 전략용
    '133690': 'TIGER 미국나스닥100', '305080': 'TIGER 미국채10년선물',
    '261220': 'KODEX WTI원유선물(H)', '329200': 'TIGER 리츠부동산인프라',
    # 3번 전략용
    '148070': 'KIWOOM 국고채10년', '469830': 'SOL 초단기채권액티브',
    # 4번 전략용 (맘 비과세)
    '466940': '은행고배당', '371160': 'TIGER 차이나항셍테크',
    '192090': 'TIGER 차이나CSI300', '453870': 'TIGER 인도니프티50',
    '241180': 'TIGER 일본니케이225',
    '229200': 'KODEX 코스닥150', '144600': 'KODEX 은선물(H)',
}

# 중복 제거하며 순서 유지한 전체 수집 대상
ALL_TICKERS = list(dict.fromkeys(
    OFFENSE_TICKERS + DEFENSE_TICKERS + STRATEGY2_TICKERS + STRATEGY3_TICKERS + MAMTAX_TICKERS))

START_DATE = '2008-01-01'   # 각 종목은 상장일부터 반환됨 (여유있게 이른 날짜)


# ==========================================
# 국내 ETF 월봉 수집
# ==========================================
def _drop_incomplete_month(monthly_series, today=None):
    """진행 중(미완성)인 현재 달 행을 제거. (미국판과 동일 규칙)"""
    if monthly_series is None or len(monthly_series) == 0:
        return monthly_series
    if today is None:
        today = pd.Timestamp.today()
    current_month_start = today.normalize().replace(day=1)
    return monthly_series[monthly_series.index < current_month_start]


def fetch_kr_fdr(ticker, start=START_DATE):
    """FinanceDataReader로 국내 ETF 일봉 → 월말 종가 월봉."""
    import FinanceDataReader as fdr
    df = fdr.DataReader(ticker, start)
    if df is None or df.empty or 'Close' not in df.columns:
        return None
    if getattr(df.index, 'tz', None) is not None:
        df.index = df.index.tz_localize(None)
    monthly = df['Close'].resample('ME').last().dropna()
    return monthly


def fetch_kr_yfinance(ticker, start=START_DATE):
    """야후 폴백. 국내 ETF는 '{코드}.KS' 심볼 (일부만 지원)."""
    import yfinance as yf
    df = yf.download(f"{ticker}.KS", start=start, progress=False, auto_adjust=False)
    if df is None or df.empty:
        return None
    close = df['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    if getattr(close.index, 'tz', None) is not None:
        close.index = close.index.tz_localize(None)
    return close.resample('ME').last().dropna()


def fetch_kr(ticker):
    """FDR 우선, 실패 시 yfinance(.KS). 둘 다 실패하면 None."""
    name = TICKER_NAMES.get(ticker, ticker)
    for src, fn in [('fdr', fetch_kr_fdr), ('yfinance', fetch_kr_yfinance)]:
        try:
            s = fn(ticker)
            s = _drop_incomplete_month(s)
            if s is not None and len(s) > 12:
                print(f"  ✅ {ticker} {name}: {src}로 {len(s)}개월 (최근 {s.index[-1].date()})")
                return s
            else:
                print(f"  ⚠️ {ticker} {name}: {src} 결과 부족")
        except Exception as e:
            print(f"  ⚠️ {ticker} {name}: {src} 실패 ({type(e).__name__}: {e})")
    return None


def _clean_name(name):
    """파일명 안전화: 공백·괄호 제거 (한글·영숫자는 유지)."""
    return (name.replace(' ', '').replace('(', '').replace(')', '')
                .replace('/', '').replace('\\', '').replace('&', ''))


def csv_filename(ticker):
    """저장 파일명: '{코드}_{종목명}_과거_데이터.csv'  (숫자만으론 못 알아보므로 이름 병기)."""
    name = _clean_name(TICKER_NAMES.get(ticker, ticker))
    return f"{ticker}_{name}_과거_데이터.csv"


def save_etf_csv(ticker, monthly_series):
    """월봉 Series → CSV ("날짜","종가", 최신이 위로)."""
    df = pd.DataFrame({
        '날짜': monthly_series.index.strftime('%Y-%m-%d'),
        '종가': monthly_series.values.round(2),
    })
    df = df.iloc[::-1].reset_index(drop=True)
    path = os.path.join(MONTHLY_DIR, csv_filename(ticker))
    df.to_csv(path, index=False, encoding='utf-8-sig')
    return path


def update_all():
    """모든 국내 ETF 갱신. 실패한 종목은 기존 파일 유지."""
    os.makedirs(MONTHLY_DIR, exist_ok=True)
    print(f"📈 코 삼성(국내 ETF) 월봉 수집 시작... 대상 {len(ALL_TICKERS)}종")
    ok, fail = [], []
    for ticker in ALL_TICKERS:
        s = fetch_kr(ticker)
        if s is not None:
            save_etf_csv(ticker, s)
            ok.append(ticker)
        else:
            fail.append(ticker)
            print(f"  ❌ {ticker} {TICKER_NAMES.get(ticker, '')}: 수집 실패 → 기존 파일 유지")
    print(f"📊 완료: 성공 {len(ok)}/{len(ALL_TICKERS)}종, 실패 {len(fail)}종")
    if fail:
        fail_desc = [f"{t}({TICKER_NAMES.get(t, '')})" for t in fail]
        print(f"   실패 목록: {fail_desc}")
    return ok, fail


def main():
    ok, fail = update_all()
    # 절반 이상 실패하면 비정상 종료(워크플로우에서 감지)
    if len(fail) > len(ALL_TICKERS) // 2:
        print("❌ 절반 이상 수집 실패 — 데이터 소스 점검 필요")
        sys.exit(1)
    print("✅ 코 삼성 데이터 업데이트 완료")


if __name__ == '__main__':
    main()
