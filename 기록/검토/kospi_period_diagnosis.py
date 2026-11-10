"""저장된 연속 백테스트의 시기·자산별 로그수익 분해. 전략 재최적화 없음."""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / '기록/2026-11-10-KOSPI-최장기간-차순위vs현금'
INPUT = ROOT / '기록/2026-11-10-KOSPI-최장기간-재구성입력'
OUT = ROOT / '기록/2026-11-10-KOSPI-시기별성과진단'
NAME = '통합 전략 (중복 제외 1/N)'

def read(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))

def main():
    rows = read(RESULT / 'next_monthly.csv')
    modes = {r['투자월']: r for r in read(INPUT / 'diagnostic_details.csv')}
    assert len(rows) == len(modes) == 365
    def classify(row):
        mode = modes[row['투자월']]
        return '주식' if mode['invested'] == 'True' else mode['방어자산']
    report = {'strategy': NAME, 'policy': 'next', 'method': '기존 연속 실행의 사후 분해. 자산명은 월초 목표 기준이며 잔존 매도대기 주식의 손익을 포함할 수 있음.', 'periods': []}
    for start, end in [('1996-06','2013-12'), ('2014-01','2026-10'), ('2014-01','2019-12'), ('2020-01','2026-10')]:
        sample = [row for row in rows if start <= row['투자월'] <= end]
        asset = peak = 1.
        mdd = 0.
        for row in sample:
            asset *= 1 + float(row[NAME])/100
            peak = max(peak, asset)
            mdd = min(mdd, asset/peak-1)
        stats = {'start':start,'end':end,'months':len(sample), 'cagr_pct':(asset**(12/len(sample))-1)*100, 'mdd_pct':mdd*100, 'modes':{}}
        total_log = math.log(asset)
        for mode in ['주식','금','현금']:
            returns = [float(row[NAME])/100 for row in sample if classify(row)==mode]
            mode_log = sum(math.log1p(r) for r in returns)
            stats['modes'][mode] = {'months':len(returns), 'positive_months':sum(r>1e-12 for r in returns),
                                  'mean_month_pct':sum(returns)/len(returns)*100 if returns else None,
                                  'log_growth':mode_log, 'log_share_pct':mode_log/total_log*100}
        stats['log_growth'] = total_log
        assert abs(sum(item['log_growth'] for item in stats['modes'].values())-total_log)<1e-10
        report['periods'].append(stats)
    after = [r for r in rows if r['투자월'] >= '2014-01']
    ordered = sorted(after,key=lambda r:float(r[NAME]),reverse=True)
    prices = {(r['투자월'],r['종목코드']):r for r in read(INPUT/'monthly_price_data.csv')}
    positions = read(RESULT/'target_positions.csv')
    report['top5_months']=[]
    for row in ordered[:5]:
        month = row['투자월']
        picks = [r for r in positions if r['정책']=='next' and r['전략']==NAME and r['투자월']==month]
        holdings = []
        for pick in picks:
            price = prices[(month,pick['대상'])]
            holdings.append({'code':pick['대상'],'name':price['종목명'],'weight':float(pick['가용자금내비중']),
                             'adjusted_return_pct':float(price['이번달수익률']), 'raw_close_return_pct':float(price['raw_return'])})
        report['top5_months'].append({'month':month,'return_pct':float(row[NAME]),'mode':classify(row),'holdings':holdings})
    report['top5_log_share_pct']=sum(math.log1p(float(r[NAME])/100) for r in ordered[:5])/report['periods'][1]['log_growth']*100
    annual = read(RESULT / 'next_annual.csv')
    report['annual_after2014']={r['투자월']:float(r[NAME]) for r in annual if r['투자월']>='2014'}
    OUT.mkdir(exist_ok=True)
    (OUT/'diagnosis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
