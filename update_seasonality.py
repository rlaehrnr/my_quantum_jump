#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
data/seasonality_monthly.csv 를 매월 1일에 갱신한다.

지수 4개(코스피·코스닥·S&P500·나스닥)의 월간 수익률을 FinanceDataReader에서 받아
'끝난 달'만 채운다. 진행 중인 달은 건드리지 않는다.

건드리는 범위는 작년 1월부터다. 그 이전 과거는 엑셀에서 손으로 정리한 원본이라
이 스크립트가 절대 손대지 않는다. 최근 구간은 시세 쪽을 정답으로 보고,
값이 어긋나 있으면 덮어쓴다(손입력 실수를 자동으로 바로잡기 위함).

⚠️ 사이클8 주의
  8년 주기는 미국 대통령의 재선 여부에 달려 있어 산식으로 확정할 수 없다.
  이 스크립트는 새 연도를 만들 때 직전 연도에서 1을 더할 뿐이다.
  선거 다음 해(사이클8이 5가 되는 해)에는 현직이 실제로 재선됐는지 확인해야 한다.
  재선이 아니라면 그 해를 1년차로 직접 고쳐야 한다. 그 상황이면 로그에 찍는다.
"""
import csv
import os
import sys
from datetime import date

import FinanceDataReader as fdr

CSV_PATH = os.path.join("data", "seasonality_monthly.csv")
SRC = {"SP500": "US500", "NASDAQ": "IXIC", "KOSPI": "KS11", "KOSDAQ": "KQ11"}
ORDER = ["SP500", "NASDAQ", "KOSPI", "KOSDAQ"]
MONTHS = [f"{m}월" for m in range(1, 13)]
HEADER = ["지수", "연도", "사이클4", "사이클8"] + MONTHS

TOL = 0.0005          # 0.05%p 넘게 어긋나면 정정
DIGITS = 4


def load():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return {
        (r["지수"], int(r["연도"])): {
            "사이클4": int(r["사이클4"]),
            "사이클8": int(r["사이클8"]),
            **{m: (None if r[m] == "" else float(r[m])) for m in MONTHS},
        }
        for r in rows
    }


def fetch(ticker, from_year, to_year):
    """월말 종가 기준 월간 수익률 {(연,월): 수익률}.

    FDR은 end 를 배타적으로 다루는 듯해 넉넉히 뒤로 잡아야
    대상 월의 마지막 거래일이 들어온다. 직전 12월 종가가 필요하므로
    시작도 한 해 앞에서 끊는다.
    """
    px = fdr.DataReader(ticker, f"{from_year - 1}-01-01", f"{to_year + 1}-12-31")
    px = px["Close"].dropna()
    if px.empty:
        raise RuntimeError("데이터가 비어 있습니다")
    ret = px.groupby([px.index.year, px.index.month]).last().pct_change().dropna()
    return {(int(y), int(m)): float(v) for (y, m), v in ret.items()}


def main():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"🚨 {CSV_PATH} 가 없습니다")

    today = date.today()
    open_ym = (today.year, today.month)       # 진행 중인 달 → 쓰지 않는다
    from_year = today.year - 1                # 여기부터만 손댄다
    table = load()
    filled, fixed, newrows, notes = [], [], [], []

    for code in ORDER:
        years = [y for (c, y) in table if c == code]
        if not years:
            notes.append(f"⚠️ {code}: 기존 행이 없어 건너뜁니다")
            continue

        try:
            truth = fetch(SRC[code], from_year, today.year)
        except Exception as e:                # 한 지수가 실패해도 나머지는 진행
            notes.append(f"⚠️ {code} 조회 실패, 건너뜁니다: {e}")
            continue

        for (y, m), val in sorted(truth.items()):
            if y < from_year or (y, m) >= open_ym:
                continue

            if (code, y) not in table:        # 새 연도 → 행 생성
                prev = table.get((code, y - 1))
                if prev is None:
                    notes.append(f"⚠️ {code} {y}: 직전 연도가 없어 행을 못 만듭니다")
                    continue
                c4 = prev["사이클4"] % 4 + 1
                c8 = prev["사이클8"] % 8 + 1
                table[(code, y)] = {"사이클4": c4, "사이클8": c8,
                                    **{mm: None for mm in MONTHS}}
                newrows.append(f"{code} {y} (사이클4={c4}, 사이클8={c8})")
                if c8 == 5:
                    notes.append(
                        f"❗ {code} {y}: 사이클8을 5년차로 넣었습니다. "
                        f"{y - 1}년 대선에서 현직이 재선됐는지 확인하세요. "
                        f"재선이 아니면 {y}년을 1년차로 직접 고쳐야 합니다."
                    )

            row = table[(code, y)]
            key, new, old = f"{m}월", round(val, DIGITS), table[(code, y)][f"{m}월"]
            if old is None:
                row[key] = new
                filled.append(f"{code} {y}-{m:02d} = {new:+.2%}")
            elif abs(old - new) > TOL:
                row[key] = new
                fixed.append(f"{code} {y}-{m:02d}: {old:+.2%} → {new:+.2%}")

    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for code in ORDER:
            for y in sorted(y for (c, y) in table if c == code):
                r = table[(code, y)]
                w.writerow([code, y, r["사이클4"], r["사이클8"]]
                           + ["" if r[m] is None else r[m] for m in MONTHS])

    print(f"기준일 {today} · {from_year}년 1월부터 검사 · "
          f"진행 중인 {open_ym[0]}-{open_ym[1]:02d}월은 채우지 않았습니다")
    for title, items in (("새 연도 행", newrows), ("새로 채움", filled), ("값 정정", fixed)):
        print(f"\n[{title}] {len(items)}건")
        for x in items:
            print("  -", x)
    if notes:
        print(f"\n[확인 필요] {len(notes)}건")
        for x in notes:
            print("  ", x)
    if not (newrows or filled or fixed):
        print("\n변경 사항 없음")


if __name__ == "__main__":
    main()
