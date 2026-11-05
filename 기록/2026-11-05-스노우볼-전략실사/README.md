# 스노우볼 6전략 탐색·맘쏘 삼성 독립 검산 재현

- 입력 커밋: `17ee7026d693ca1468900fb7e9c99a0139854b04`, 확정월 2026-10.
- 라이브 코드·전략 상수·원본 `data/` 수정 없음. HTTP 폴백 금지.
- 결론·판정: `기록/DGbrain-이관대기.md`의 **맘쏘 삼성 7~10월 낙폭 재현과 대안 13종 실사 (2026-11-05)**.
- 사용자가 전체 실사를 요청한 뒤 맘쏘 삼성부터 하기로 범위를 좁혔다. 다른 5전략은 첫 탐색 수치만 보존하며 최종 채택 판정이 아니다.

## 실행

현재 작업 폴더를 바꾸지 않고 해당 커밋을 별도 `source` 폴더에 펼친다. Windows 기본 tar의 한글 파일명 오류를 피하려면 Python `tarfile`로 추출한다. source 안에는 `SOURCE_COMMIT.txt`에 위 커밋을 적어둔다.

```powershell
git archive --output=source.tar 17ee7026d693ca1468900fb7e9c99a0139854b04
python -c "import tarfile; tarfile.open('source.tar',encoding='utf-8').extractall('source',filter='data')"
python 기록/검토/snowball_robustness_20261105.py --source source --output 기록/2026-11-05-스노우볼-전략실사
python 기록/검토/so_failure_audit_20261105.py --source source --output 기록/2026-11-05-스노우볼-전략실사
python 기록/검토/so_audit_figures_20261105.py
```

기본 의존성은 앱과 같은 pandas·numpy·streamlit이며 그림만 matplotlib가 추가로 필요하다. 검산의 위험대응 대조군은 이 폴더의 `risk_control_reference.py`를 사용한다. 동일일 기존 로컬 검증 러너의 실행 시점 사본이며, 원본 파일에는 쓰지 않는다.

## 파일과 검증 범위

- `results.json`·`summary.csv`: 6전략 기준·비교안 전체 수치, 비용 민감도, 입력 CSV SHA-256. 성과 비교는 각 전략의 마지막 누락월 이후 연속 구간으로 통일. 초기에 건너뛴 달은 `checks.missing_months`에 명시.
- `*_monthly.csv`·`*_weights.csv`: 매월 신호·다음 달 수익·비용·보유비중. 초기 진입부터 비교안별 비용을 다시 계산. `live_original`은 앱 원출력 그대로다.
- `so_independent_audit.json`: 원가격에서 184개 신호(183개 실현월+최신 신호), 13안×183개월 수익·매수비용, 변동성의 개별 월수익/공분산 수식 검산.
- `so_riskmatched*`: 2016년 말까지 최소 60개월 학습 후, 해당 연도 전 자료만으로 연초 고정비중을 정한 대조군. 확장 표본·최근 60개월 방식. 수익·위험 절대값이 완전히 같은 대조군은 아니며 사전 위험 규모를 맞춘 실용적 대조군이다.
- `so_2026_wealth_drawdown.png`: 월말 자산과 낙폭, 2025-12=100.

2026년은 이미 손실을 보고 선정한 검토기간이다. `pre2026`와 분리했어도 진짜 미사용 검증이라고 부르지 않는다. 최초 러너의 `annual_selection`은 후보별 연속 성과를 접합한 선택 안정성 진단으로, 추가 전략 간 전환비용이 없어 실운용 메타전략의 백테스트가 아니다.

USD·KRW가 섞인 6전략 합산은 통화 미통일 진단값이다. 맘쏘 삼성 결과는 USD 기준이다. 배당·분할은 기존 로봇 수정종가를 따르고, 월말 동시 신호·체결 가정, 월중 낙폭·세금·실제 체결·개인 계좌 환전손익·과거 시점의 유니버스 선택은 별도 검증하지 못했다. 현금 수익률은 0%, Sharpe 무위험수익률도 0%다.
