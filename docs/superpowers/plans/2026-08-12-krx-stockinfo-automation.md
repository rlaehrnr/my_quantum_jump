# StockInfo 자동 갱신 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 손으로 하던 KRX 액면가·상장주식수 갱신을 매월 1일 도는 GitHub Actions 로봇으로 옮긴다.

**Architecture:** 로봇(`update_stock_info.py`)이 pykrx로 KRX 전종목 기본정보를 받아 `data/krx_stock_info.csv`에 덮어쓰고 커밋한다. 앱은 구글 시트 `StockInfo` 탭 대신 이 CSV를 읽는다. 읽기 로직은 `utils/stock_info.py`에 두어 streamlit 없이 import·테스트할 수 있게 한다.

**Tech Stack:** Python 3.10, pykrx 1.2.8, pandas, GitHub Actions, Streamlit

## Global Constraints

- **한국어로 쓴다.** 주석·커밋 메시지·문서 전부 (`CLAUDE.md` 절대 규칙 6)
- **라이브 서비스다.** `main`에 push하면 즉시 재배포된다. push 전에 사용자 확인을 받는다 (`CLAUDE.md` 절대 규칙 1)
- **CSV 인코딩은 `utf-8-sig`.** 레포의 기존 CSV 9종이 전부 BOM을 갖고 있고 `update_*.py`가 전부 `encoding='utf-8-sig'`로 쓴다. 읽을 때도 `utf-8-sig`를 명시해 BOM을 벗긴다
- **종목코드는 6자리 문자열.** 앞자리 0을 보존한다. 숫자로 해석되면 `098120`이 `98120`이 된다
- **`requirements.txt`를 건드리지 않는다.** 이 파일은 Streamlit Cloud 배포 매니페스트다. pytest를 넣으면 배포 환경에 설치된다. 테스트는 표준 라이브러리만으로 돌리는 스크립트로 쓴다
- **비밀정보를 로그에 흘리지 않는다.** 워크플로우에 `echo`나 디버그 출력을 추가하지 않는다
- pykrx는 `main()` 안에서 import한다. 순수 변환 함수를 pykrx 없이 테스트하기 위해서다

## 실행 순서 제약 (중요)

**로봇을 먼저 돌려 CSV를 만든 다음에 앱을 전환한다.**

앱을 먼저 전환하면 CSV가 없는 상태가 되고, 그동안 액면가 경고와 시총 백업이 사라진다.
그래서 Task 3(워크플로우 수동 실행)이 Task 4(앱 전환)보다 앞선다. Task 1~3은 라이브 앱에
아무 영향이 없다 — 파일을 추가할 뿐이다.

## File Structure

| 파일 | 책임 |
|---|---|
| `utils/stock_info.py` (신규) | CSV → `{종목코드: {액면가, 상장주식수}}`. 앱이 읽는 쪽. streamlit 비의존 |
| `update_stock_info.py` (신규) | KRX 수집 → CSV 저장. 로봇이 쓰는 쪽 |
| `tests/test_stock_info.py` (신규) | 위 두 모듈의 순수 함수 테스트. `python tests/test_stock_info.py`로 실행 |
| `.github/workflows/krx_stock_info_monthly.yml` (신규) | 매월 1일 09:00 KST 실행 |
| `pages/5_내 소형주 퀀트 포트.py` (수정) | 시트 대신 CSV를 읽도록 교체 |
| `현황.md` · `CLAUDE.md` (수정) | 결과 반영 |

### 설계와 달라진 점 2가지

1. **실행 시각 08:30 → 09:00 KST.** GitHub cron은 `L`(말일)을 지원하지 않는다. 08:30 KST는 전날 23:30 UTC라 말일 처리가 필요해진다. `'0 0 1 * *'`(UTC 0시 = KST 09:00)로 하면 기존 `kr_monthly_update.yml`과 같은 표현이 된다. KRX 기본정보는 장중 여부와 무관하므로 영향 없다
2. **변수명 `gsheet_stock_info` → `stock_info`.** 설계에서는 호출부를 안 고친다고 했으나, 시트에서 안 읽게 된 뒤에도 `gsheet_`라는 이름이 남으면 다음 사람이 오해한다. 기계적 치환 4곳이고 되돌리기 쉽다

---

### Task 1: CSV 로더 (`utils/stock_info.py`)

**Files:**
- Create: `utils/stock_info.py`
- Create: `tests/test_stock_info.py`

**Interfaces:**
- Consumes: 없음 (pandas·표준 라이브러리만)
- Produces:
  - `STOCK_INFO_PATH: str = 'data/krx_stock_info.csv'`
  - `COLUMNS: list[str] = ['종목코드', '종목명', '시장구분', '액면가', '상장주식수']`
  - `to_int(value, default=0) -> int`
  - `load_stock_info(path=STOCK_INFO_PATH) -> dict[str, dict[str, int]]`
    반환 형태: `{'098120': {'액면가': 500, '상장주식수': 8312766}}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_stock_info.py` 생성:

```python
# -*- coding: utf-8 -*-
"""종목 마스터 로더·수집기 테스트. pytest 없이 `python tests/test_stock_info.py`로 돌린다."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.stock_info import load_stock_info, to_int

FAILED = []


def check(label, got, expected):
    ok = got == expected
    if not ok:
        FAILED.append(label)
    print("  [%s] %s" % ("OK" if ok else "FAIL", label))
    if not ok:
        print("        got      %r" % (got,))
        print("        expected %r" % (expected,))


def write_csv(body):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(body)
    return path


print("=== to_int ===")
check("숫자 문자열", to_int("500"), 500)
check("콤마 포함", to_int("8,312,766"), 8312766)
check("정수 입력", to_int(500), 500)
check("빈 값은 0", to_int(""), 0)
check("무액면은 0", to_int("무액면"), 0)
check("None은 0", to_int(None), 0)

print()
print("=== load_stock_info ===")

path = write_csv(
    "종목코드,종목명,시장구분,액면가,상장주식수\n"
    "098120,마이크로컨텍솔,KOSDAQ,500,8312766\n"
    "009520,포스코엠텍,KOSDAQ GLOBAL,500,41642703\n"
    "005930,삼성전자,KOSPI,100,5969782550\n"
)
info = load_stock_info(path)
check("행 수", len(info), 3)
check("앞자리 0 보존", "098120" in info, True)
check("액면가", info["005930"]["액면가"], 100)
check("상장주식수", info["005930"]["상장주식수"], 5969782550)
os.remove(path)

path = write_csv(
    "종목코드,종목명,시장구분,액면가,상장주식수\n"
    "98120,마이크로컨텍솔,KOSDAQ,500,8312766\n"
)
check("앞자리 0이 잘린 코드도 6자리로 복원", "098120" in load_stock_info(path), True)
os.remove(path)

path = write_csv(
    "종목코드,종목명,시장구분,액면가,상장주식수\n"
    "00104K,CJ4우(전환),KOSPI,5000,4226512\n"
)
check("알파벳 섞인 코드 보존", "00104K" in load_stock_info(path), True)
os.remove(path)

path = write_csv(
    "종목코드,종목명,시장구분,액면가,상장주식수\n"
    "096770,SK이노베이션,KOSPI,무액면,92465564\n"
)
check("액면가가 숫자가 아니면 0", load_stock_info(path)["096770"]["액면가"], 0)
os.remove(path)

check("파일이 없으면 빈 dict", load_stock_info("data/없는파일.csv"), {})

print()
if FAILED:
    print("실패 %d건: %s" % (len(FAILED), ", ".join(FAILED)))
    sys.exit(1)
print("전건 통과")
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python tests/test_stock_info.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.stock_info'`

- [ ] **Step 3: 최소 구현을 쓴다**

`utils/stock_info.py` 생성:

```python
"""종목 마스터(액면가·상장주식수) 로더.

data/krx_stock_info.csv 는 매월 1일 GitHub Actions 로봇(update_stock_info.py)이
KRX 전종목 기본정보로 덮어쓴다. 이 모듈은 그 파일을 읽어 앱이 쓰는 형태로 바꾼다.

💡 streamlit 을 import 하지 않는다. 테스트에서 그냥 import 할 수 있어야 하기 때문이다.
"""
import os

import pandas as pd

STOCK_INFO_PATH = 'data/krx_stock_info.csv'
COLUMNS = ['종목코드', '종목명', '시장구분', '액면가', '상장주식수']


def to_int(value, default=0):
    """'1,000' · '500' · '' · '무액면' 을 정수로. 숫자가 하나도 없으면 default."""
    digits = ''.join(c for c in str(value) if c.isdigit() or c == '-')
    try:
        return int(digits)
    except ValueError:
        return default


def load_stock_info(path=STOCK_INFO_PATH):
    """{종목코드: {'액면가': int, '상장주식수': int}} 를 돌려준다.

    💡 파일이 없거나 깨졌으면 빈 dict 다. 앱은 액면가 경고와 시총 백업만 잃고
       나머지는 그대로 돈다 — 구글 시트를 못 읽던 때와 같은 동작이다.
    """
    if not os.path.exists(path):
        return {}
    try:
        # utf-8-sig: 레포의 CSV 는 전부 BOM 이 있다. BOM 을 안 벗기면
        # 첫 컬럼명이 '﻿종목코드' 가 되어 조용히 빈 결과가 나온다.
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig').fillna('')
    except Exception:
        return {}

    info = {}
    for _, row in df.iterrows():
        code = str(row.get('종목코드', '')).strip()
        if not code:
            continue
        info[code.zfill(6)] = {
            '액면가': to_int(row.get('액면가', 0)),
            '상장주식수': to_int(row.get('상장주식수', 0)),
        }
    return info
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python tests/test_stock_info.py`
Expected: PASS — `전건 통과`, exit code 0

- [ ] **Step 5: 커밋한다**

```bash
git add utils/stock_info.py tests/test_stock_info.py
git commit -m "feat: 종목 마스터 CSV 로더 추가

data/krx_stock_info.csv 를 {종목코드: {액면가, 상장주식수}} 로 읽는다.
streamlit 을 import 하지 않아 테스트에서 그대로 쓸 수 있다.

종목코드는 dtype=str 로 읽고 zfill(6) 한다. 앞자리 0 이 잘린 코드도
복원되고, 00104K 같은 알파벳 코드도 그대로 살아남는다.
인코딩은 utf-8-sig — 레포의 CSV 는 전부 BOM 이 있어 안 벗기면 첫 컬럼명이
깨지고 조용히 빈 결과가 나온다.

파일이 없으면 빈 dict 를 돌려준다. 구글 시트를 못 읽던 때와 같은 동작이라
화면이 깨지지 않는다."
```

---

### Task 2: 수집 스크립트 (`update_stock_info.py`)

**Files:**
- Create: `update_stock_info.py`
- Modify: `tests/test_stock_info.py` (파일 끝의 결과 출력 블록 **앞에** 테스트를 덧붙인다)

**Interfaces:**
- Consumes: `utils.stock_info.COLUMNS`
- Produces:
  - `OUT_PATH: str = 'data/krx_stock_info.csv'`
  - `build_frame(raw: pd.DataFrame) -> pd.DataFrame` — 티커 인덱스를 가진 pykrx 원본을 5개 컬럼 DataFrame으로 정리
  - `main() -> None` — 수집·검증·저장. 실패 시 `sys.exit(메시지)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_stock_info.py`에서 `print()` + `if FAILED:` 블록 **바로 위에** 아래를 삽입한다:

```python
print()
print("=== build_frame ===")

import pandas as pd

from update_stock_info import build_frame

raw = pd.DataFrame(
    {
        "한글종목약명": ["마이크로컨텍솔", "삼성전자", "CJ4우(전환)"],
        "시장구분": ["KOSDAQ", "KOSPI", "KOSPI"],
        "액면가": ["500", "100", "5000"],
        "상장주식수": [8312766, 5969782550, 4226512],
        "한글종목명": ["(주)마이크로컨텍솔루션", "삼성전자(주)", "씨제이(주)"],
    },
    index=pd.Index(["098120", "005930", "00104K"], name="티커"),
)
out = build_frame(raw)

check("컬럼 구성", list(out.columns), ["종목코드", "종목명", "시장구분", "액면가", "상장주식수"])
check("행 수", len(out), 3)
check("종목코드로 정렬", list(out["종목코드"]), ["00104K", "005930", "098120"])
check("종목명은 약명을 쓴다", out.loc[out["종목코드"] == "005930", "종목명"].iloc[0], "삼성전자")

raw2 = pd.DataFrame(
    {"한글종목약명": ["포스코엠텍"], "시장구분": ["KOSDAQ GLOBAL"], "액면가": ["500"], "상장주식수": [41642703]},
    index=pd.Index([9520], name="티커"),
)
check("숫자 티커도 6자리 문자열로", list(build_frame(raw2)["종목코드"]), ["009520"])
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `python tests/test_stock_info.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'update_stock_info'`

- [ ] **Step 3: 최소 구현을 쓴다**

`update_stock_info.py` 생성:

```python
"""KRX 전종목 기본정보(액면가·상장주식수)를 받아 data/krx_stock_info.csv 로 저장한다.

GitHub Actions 가 매월 1일 실행한다. KRX_ID / KRX_PW 환경변수로 로그인한다.

💡 pykrx 는 main() 안에서 import 한다. build_frame() 만 테스트할 때
   pykrx 없이도 이 파일을 import 할 수 있어야 하기 때문이다.
"""
import os
import sys

import pandas as pd

from utils.stock_info import COLUMNS

OUT_PATH = 'data/krx_stock_info.csv'


def build_frame(raw):
    """pykrx 의 전종목 기본정보를 저장용 5개 컬럼으로 정리한다.

    raw 는 티커를 인덱스로 갖고 '한글종목약명' '시장구분' '액면가' '상장주식수'
    컬럼을 가진 DataFrame 이다.
    """
    df = raw.reset_index().rename(columns={'티커': '종목코드', '한글종목약명': '종목명'})
    # 💡 zfill(6): KRX 가 숫자로 준 티커의 앞자리 0 을 되살린다.
    #    00104K 처럼 알파벳이 섞인 코드는 이미 6자리라 그대로 통과한다.
    df['종목코드'] = df['종목코드'].astype(str).str.strip().str.zfill(6)
    out = df[df['종목코드'] != ''][COLUMNS].copy()
    return out.sort_values('종목코드').reset_index(drop=True)


def main():
    from pykrx import stock

    if not os.getenv('KRX_ID') or not os.getenv('KRX_PW'):
        sys.exit('KRX_ID / KRX_PW 환경변수가 없다. 수집을 중단한다.')

    raw = stock.get_market_ohlcv_by_market('ALL')
    if raw is None or raw.empty:
        # 💡 빈 결과로 CSV 를 덮으면 액면가 경고가 조용히 사라진다.
        #    기존 파일을 보존하고 Actions 를 실패로 표시해 눈에 띄게 한다.
        sys.exit('KRX 응답이 비었다. 기존 CSV 를 보존하고 중단한다.')

    out = build_frame(raw)
    if out.empty:
        sys.exit('정리 결과가 0행이다. 기존 CSV 를 보존하고 중단한다.')

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out.to_csv(OUT_PATH, index=False, encoding='utf-8-sig')
    print('저장 완료: %s (%s행)' % (OUT_PATH, format(len(out), ',')))


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 테스트를 돌려 통과를 확인한다**

Run: `python tests/test_stock_info.py`
Expected: PASS — `전건 통과`, exit code 0

- [ ] **Step 5: 커밋한다**

```bash
git add update_stock_info.py tests/test_stock_info.py
git commit -m "feat: KRX 전종목 기본정보 수집 스크립트 추가

pykrx get_market_ohlcv_by_market('ALL') 로 액면가·상장주식수를 받아
data/krx_stock_info.csv 로 저장한다. KRX_ID/KRX_PW 환경변수로 로그인한다.

로그인 정보가 없거나 응답이 비었거나 정리 결과가 0행이면 CSV 를 건드리지
않고 종료한다. 빈 파일로 덮으면 액면가 경고가 조용히 사라지기 때문이다.

pykrx 는 main() 안에서 import 한다. build_frame() 을 pykrx 없이
테스트하기 위해서다."
```

---

### Task 3: 워크플로우 추가 · 수동 실행으로 CSV 생성

**Files:**
- Create: `.github/workflows/krx_stock_info_monthly.yml`

**Interfaces:**
- Consumes: `update_stock_info.py`, GitHub Secrets `KRX_ID`·`KRX_PW`
- Produces: `data/krx_stock_info.csv` (로봇이 생성·커밋)

**이 태스크는 라이브 앱에 영향이 없다.** 앱은 아직 시트를 읽고 있고, 여기서는 데이터 파일만 생긴다.

- [ ] **Step 1: 워크플로우를 쓴다**

`.github/workflows/krx_stock_info_monthly.yml` 생성:

```yaml
name: KRX Stock Info Monthly Update

on:
  schedule:
    - cron: '0 0 1 * *'   # 💡 매월 1일 UTC 0시 = 한국 시간 매월 1일 오전 9시
  workflow_dispatch:        # 수동 실행 가능 (첫 검증에 사용)

jobs:
  update-stock-info:
    runs-on: ubuntu-latest
    env:
      TZ: Asia/Seoul

    steps:
    - name: 1. 저장소 코드 불러오기
      uses: actions/checkout@v3

    - name: 2. 파이썬 환경 세팅
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: 3. 라이브러리 설치
      run: |
        python -m pip install --upgrade pip
        pip install pandas pykrx

    - name: 4. 📋 KRX 전종목 기본정보(액면가·상장주식수) 수집
      env:
        KRX_ID: ${{ secrets.KRX_ID }}
        KRX_PW: ${{ secrets.KRX_PW }}
      run: python update_stock_info.py

    - name: 5. 깃허브에 커밋
      run: |
        git config --local user.email "action@github.com"
        git config --local user.name "GitHub Action Bot"
        git add data/krx_stock_info.csv
        git diff --quiet && git diff --staged --quiet || (git commit -m "🤖 [KRX] 종목 기본정보(액면가·상장주식수) 자동 갱신" && git push)
```

- [ ] **Step 2: 커밋하고 push한다 (사용자 확인 후)**

```bash
git add .github/workflows/krx_stock_info_monthly.yml
git commit -m "ci: KRX 종목 기본정보 월간 갱신 로봇 추가

매월 1일 UTC 0시(KST 09:00)에 돈다. 기존 kr_monthly_update.yml 과 같은
표현이다 — GitHub cron 은 말일(L)을 지원하지 않아 1일 기준으로 잡았다.

workflow_dispatch 를 넣어 첫 검증은 수동으로 돌린다.
KRX_ID/KRX_PW 는 레포 Secrets 에서 이 스텝에만 주입한다."
git push
```

- [ ] **Step 3: GitHub에서 수동 실행한다**

GitHub → Actions → **KRX Stock Info Monthly Update** → **Run workflow** → main 브랜치 → 실행.

- [ ] **Step 4: 결과를 검증한다**

```bash
git pull
python -c "
import sys; sys.path.insert(0, '.')
from utils.stock_info import load_stock_info
info = load_stock_info()
print('행 수:', len(info))
for code, name in [('005930','삼성전자'), ('098120','마이크로컨텍솔'), ('009520','포스코엠텍')]:
    print(code, name, info.get(code))
"
```

Expected:
- 행 수가 2,000행 이상 (2026-08-12 실측 기준 전 종목 약 2,871)
- `005930` 액면가 `100`
- `098120` 액면가 `500`, 상장주식수 `8312766`
- 로봇 커밋 `🤖 [KRX] 종목 기본정보(액면가·상장주식수) 자동 갱신` 이 히스토리에 있음

값이 시트의 기존 `StockInfo` 내용과 맞는지 눈으로 대조한다. 시트 기준일은 `2026-05-08`이라
그 사이 증자·상장이 있었으면 상장주식수가 다를 수 있다 — 그건 정상이다.

- [ ] **Step 5: Actions 로그에 비밀정보가 안 찍혔는지 확인한다**

실행 로그의 4번 스텝을 연다. pykrx 가 `로그인 ID: ...` 를 출력하는데 `***` 로
가려져 있어야 한다. 평문이 보이면 즉시 사용자에게 알리고 KRX 비밀번호를 교체한다.

---

### Task 4: 앱이 CSV를 읽도록 전환

**Files:**
- Modify: `pages/5_내 소형주 퀀트 포트.py` — `:16`(상수 제거), `:8` 부근(import 추가), `:111-125`(함수 교체), `:176`·`:268`·`:273`·`:274`(변수명)

**Interfaces:**
- Consumes: `utils.stock_info.load_stock_info`
- Produces: 없음 (앱 내부 변경)

**전제:** Task 3에서 `data/krx_stock_info.csv` 가 이미 생성돼 있어야 한다. 없으면 액면가가 전부 0이 된다.

- [ ] **Step 1: CSV가 있는지 확인한다**

Run: `ls -la data/krx_stock_info.csv`
Expected: 파일 존재. 없으면 Task 3으로 돌아간다.

- [ ] **Step 2: import를 추가한다**

`pages/5_내 소형주 퀀트 포트.py`의 `import os` 다음 줄에 추가:

```python
from utils.stock_info import load_stock_info
```

- [ ] **Step 3: 쓰이지 않던 상수를 지운다**

아래 줄을 삭제한다. 경로는 이제 `utils/stock_info.py`의 `STOCK_INFO_PATH`가 갖는다.

```python
FACE_VALUE_PATH = 'data/krx_stock_info.csv' 
```

- [ ] **Step 4: 시트 읽기 함수를 CSV 읽기로 교체한다**

아래 함수 전체를

```python
def load_stock_info_from_gsheet():
    info_map = {}
    try:
        client = get_gspread_client()
        sheet = client.open_by_url(SHEET_URL)
        ws = sheet.worksheet("StockInfo")
        data = ws.get_all_records()
        for row in data:
            code = str(row.get('단축코드', row.get('종목코드', ''))).strip().zfill(6)
            if code:
                info_map[code] = {
                    '액면가': parse_krw(row.get('액면가', 0), 0),
                    '상장주식수': parse_krw(row.get('상장주식수', 0), 0)
                }
    except: pass
    return info_map
```

이것으로 바꾼다:

```python
@st.cache_data(ttl=3600, show_spinner=False)
def load_stock_info_cached():
    """종목 마스터를 CSV 에서 읽는다.

    💡 예전에는 구글 시트 StockInfo 탭을 읽었다. 매월 1일 GitHub Actions
       로봇이 KRX 에서 받아 data/krx_stock_info.csv 를 갱신하도록 바뀌었다.
       2,871행을 매 rerun 마다 파싱하지 않도록 1시간 캐시한다.
    """
    return load_stock_info()
```

- [ ] **Step 5: 호출부 4곳의 변수명을 바꾼다**

```python
# :176
gsheet_stock_info = load_stock_info_from_gsheet()
# →
stock_info = load_stock_info_cached()
```

```python
# :268
df['액면가'] = df['종목코드'].apply(lambda x: gsheet_stock_info.get(x, {}).get('액면가', 0))
# →
df['액면가'] = df['종목코드'].apply(lambda x: stock_info.get(x, {}).get('액면가', 0))
```

```python
# :273-274
                if cap == 0 and code in gsheet_stock_info:
                    shares = gsheet_stock_info[code].get('상장주식수', 0)
# →
                if cap == 0 and code in stock_info:
                    shares = stock_info[code].get('상장주식수', 0)
```

- [ ] **Step 6: 남은 참조가 없는지 확인한다**

Run: `grep -n "gsheet_stock_info\|load_stock_info_from_gsheet\|FACE_VALUE_PATH" "pages/5_내 소형주 퀀트 포트.py"`
Expected: 출력 없음

- [ ] **Step 7: 문법과 동작을 검증한다**

```bash
python -c "
import ast, os, py_compile
p = 'pages/5_내 소형주 퀀트 포트.py'
tmp = p + '.pyc.tmp'
py_compile.compile(p, doraise=True, cfile=tmp)
os.remove(tmp)
print('[OK] 문법 통과')
src = open(p, encoding='utf-8').read()
tree = ast.parse(src)
names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
assert 'load_stock_info_cached' in names, '새 함수가 없다'
assert 'load_stock_info_from_gsheet' not in names, '옛 함수가 남았다'
print('[OK] 함수 교체 확인')
"
python tests/test_stock_info.py
```

Expected: `[OK] 문법 통과`, `[OK] 함수 교체 확인`, `전건 통과`

- [ ] **Step 8: 커밋한다 (push는 사용자 확인 후)**

```bash
git add "pages/5_내 소형주 퀀트 포트.py"
git commit -m "refactor: 소형주 종목 마스터를 구글 시트 대신 CSV 에서 읽는다

StockInfo 탭을 읽던 load_stock_info_from_gsheet() 를 utils.stock_info 의
CSV 로더로 교체한다. 매월 1일 로봇이 갱신하는 data/krx_stock_info.csv 를 쓴다.

이로써 구글 서비스 계정 키를 GitHub Secrets 에 복사하지 않아도 된다.
시트 권한은 파일 단위라 그 키는 보유 종목(ddo·sso·mom)까지 읽을 수 있었다.
키는 Streamlit 한 곳에만 남는다.

부수 효과 — 소형주 화면의 구글 시트 호출이 4회에서 3회로 줄고, 하필
제일 무거운 2,871행 호출이 빠진다. 1시간 캐시도 붙였다.

변수명 gsheet_stock_info 를 stock_info 로 바꾼다. 시트에서 안 읽게 된 뒤에도
gsheet_ 가 남으면 오해를 부른다. 시트의 StockInfo 탭은 지우지 않고 둔다."
```

- [ ] **Step 9: 사용자 확인 후 push하고 라이브를 검증한다**

push 뒤 `myquantumjump-bccuvb2zu4yacfnqd9exjc.streamlit.app` 의
**내 소형주 퀀트 포트** 화면이 에러 없이 뜨는지 확인한다. 포트폴리오가 비어 있어
액면가 열은 아직 안 보이지만, 화면이 뜨면 로더가 정상이라는 뜻이다.

---

### Task 5: 문서 반영

**Files:**
- Modify: `현황.md` — 자동화 완료 기록, 이력 추가
- Modify: `CLAUDE.md` — 로봇 9개 → 10개, 구글 시트 섹션에서 StockInfo 항목 갱신

**Interfaces:**
- Consumes: 없음
- Produces: 없음

- [ ] **Step 1: `CLAUDE.md`의 로봇 표를 고친다**

`## 자동 갱신 로봇` 표의 `| 월말~월초 |` 행 아래에 추가:

```markdown
| 월 1회 | KRX Stock Info (액면가·상장주식수) | 약 40초 |
```

같은 절의 `월 합계 약 **220분**` 을 `월 합계 약 **221분**` 으로 고친다.

- [ ] **Step 2: `CLAUDE.md`의 구글 시트 섹션을 고친다**

`| StockInfo |` 행을 삭제하고, 표 아래 1번 항목 앞에 추가:

```markdown
`StockInfo` 탭은 **더 이상 쓰지 않는다.** 2026-08-12부터 액면가·상장주식수는
`data/krx_stock_info.csv` 에서 읽는다(`utils/stock_info.py`). 로봇이 매월 1일 갱신한다.
시트의 탭은 되돌릴 때를 위해 지우지 않고 남겨뒀다.
```

- [ ] **Step 3: `현황.md`에 결과를 기록한다**

`## ✅ 2026-08-12 확인된 사실` 표의 `| StockInfo 탭 |` 행을 아래로 바꾼다:

```markdown
| `StockInfo` 탭 | **자동화 완료.** 손 입력 → 매월 1일 로봇이 `data/krx_stock_info.csv` 갱신. 시트 탭은 미사용이나 보존 |
```

`## 이력` 맨 아래에 추가:

```markdown
- **2026-08-12** — StockInfo 자동화 완료. KRX 전종목 기본정보를 매월 1일 로봇이 받아 `data/krx_stock_info.csv` 로 저장하고, 앱이 구글 시트 대신 이 파일을 읽는다. 구글 서비스 계정 키를 GitHub 에 복사하지 않는 쪽을 택했다 — 설계 근거는 `docs/superpowers/specs/2026-08-12-krx-stockinfo-automation-design.md`
```

- [ ] **Step 4: 커밋한다**

```bash
git add CLAUDE.md 현황.md
git commit -m "docs: StockInfo 자동화 완료 반영

로봇이 9개에서 10개가 됐다. 액면가·상장주식수는 이제 구글 시트가 아니라
data/krx_stock_info.csv 에서 읽는다. 시트의 StockInfo 탭은 되돌릴 때를
위해 지우지 않고 남겨뒀다."
```

---

## 완료 조건

- [ ] `python tests/test_stock_info.py` 가 전건 통과한다
- [ ] Actions 에서 `KRX Stock Info Monthly Update` 수동 실행이 성공한다
- [ ] `data/krx_stock_info.csv` 가 2,000행 이상이고 `005930` 액면가가 `100` 이다
- [ ] Actions 로그에 KRX 자격증명이 평문으로 안 보인다
- [ ] 라이브 앱의 소형주 화면이 에러 없이 뜬다
- [ ] `현황.md` · `CLAUDE.md` 가 갱신됐다
