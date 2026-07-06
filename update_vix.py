"""
update_vix.py — VIX(공포지수) 일별 데이터 자동 업데이트 + 35 돌파 메일 알림
=======================================================================

매 거래일 실행:
  1) ^VIX 일봉을 받아 data/vix data.csv 갱신
     (형식: 날짜,종가,시가,고가,저가,변동 %  — 기존 파일과 동일)
  2) 최신 '고가'가 35 이상으로 새로 돌파하면 이메일 알림 (SMTP)

설계 원칙:
  - 안전 우선: 새 데이터를 못 받으면 기존 CSV를 절대 덮어쓰지 않는다.
  - 멱등성: 같은 날 여러 번 실행해도 결과 동일(해당 날짜 행 갱신).
  - 메일 스팸 방지: '전일 <35 & 당일 ≥35' 신규 돌파에만 발송.
    (장기 고VIX 구간에 매일 메일 오는 것 방지)

이메일 설정 (GitHub Secrets → 워크플로우 env 로 주입):
  VIX_SMTP_USER : 보내는 Gmail 주소
  VIX_SMTP_PASS : Gmail '앱 비밀번호'(2단계 인증 후 발급, 실제 비번 아님)
  VIX_ALERT_TO  : 받는 주소(없으면 SMTP_USER로 자기 자신에게)
  VIX_SMTP_HOST : (선택) 기본 smtp.gmail.com
  VIX_SMTP_PORT : (선택) 기본 587
  시크릿이 없으면 메일은 조용히 생략하고 데이터 갱신만 수행한다.
"""

import os
import sys
import pandas as pd
import numpy as np

VIX_FILE = 'data/vix data.csv'
VIX_THRESHOLD = 35.0
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
# 35 돌파 메일 알림
# ==========================================
def send_email(subject, body):
    import smtplib
    from email.mime.text import MIMEText
    host = os.environ.get('VIX_SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('VIX_SMTP_PORT', '587'))
    user = os.environ.get('VIX_SMTP_USER')
    pw = os.environ.get('VIX_SMTP_PASS')
    to = os.environ.get('VIX_ALERT_TO') or user
    if not (user and pw):
        print("  ℹ️ SMTP 시크릿(VIX_SMTP_USER/PASS) 없음 → 메일 생략(데이터 갱신만 완료)")
        return
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = user
    msg['To'] = to
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        print(f"  ✅ VIX 알림 메일 발송 → {to}")
    except Exception as e:
        print(f"  ⚠️ 메일 발송 실패 ({type(e).__name__}: {e})")


def maybe_alert(merged):
    """전일 고가 <35 & 당일 고가 ≥35 인 '신규 돌파'에만 알림."""
    d = merged.sort_values('날짜').reset_index(drop=True)
    if len(d) < 1:
        return
    cur_high = float(d['고가'].iloc[-1])
    cur_date = d['날짜'].iloc[-1]
    prev_high = float(d['고가'].iloc[-2]) if len(d) >= 2 else 0.0
    crossed = (cur_high >= VIX_THRESHOLD) and (prev_high < VIX_THRESHOLD)
    print(f"  🔎 최신 {cur_date} 고가 {cur_high:.2f} (전일 {prev_high:.2f}) → "
          f"{'🚨 35 신규 돌파' if crossed else '알림 조건 아님'}")
    if crossed:
        cur_close = float(d['종가'].iloc[-1])
        subject = f"🚨 VIX 35 돌파 경보 — {cur_date} 고가 {cur_high:.2f}"
        body = (
            f"VIX가 35를 새로 돌파했습니다.\n\n"
            f"날짜   : {cur_date}\n"
            f"고가   : {cur_high:.2f}\n"
            f"종가   : {cur_close:.2f}\n"
            f"전일고가: {prev_high:.2f}\n\n"
            f"KOSPI200 모멘텀 터미널의 시장 상태를 확인하세요.\n"
        )
        send_email(subject, body)


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
    # 고가/종가 소수 그대로 저장(기존 형식과 동일한 float 표기)
    merged.to_csv(VIX_FILE, index=False, encoding='utf-8-sig')
    print(f"  ✅ {VIX_FILE} 저장 ({len(merged)}행, 최신 {merged['날짜'].iloc[-1]})")
    maybe_alert(merged)
    print("✅ VIX 업데이트 완료")


if __name__ == '__main__':
    main()
