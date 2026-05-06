import pandas as pd
from datetime import datetime, timedelta

# 💡 [버그 해결 핵심] API 과부하 및 지연을 막는 전역 메모리 캐시
# 이 장치가 지수를 최초 1번만 가져오게 만들어 마켓타이밍 슬라이더를 즉각 반응하게 합니다.
_CACHE = {}

# ==========================================
# 🇰🇷 한국 주식 전용 함수
# ==========================================
PRESIDENTIAL_DANGEROUS_MONTHS = {
    1: [2, 9], 2: [2, 4, 6, 9, 12], 3: [8, 9], 4: [3],
    5: [], 6: [7], 7: [6, 8, 11, 12], 8: [1, 6, 9, 10, 11]
}

def get_cycle_year(current_year):
    years_since = current_year - 2021
    return (years_since % 8) + 1

def get_kospi_ma_all(target_date_str):
    import FinanceDataReader as fdr
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=450)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0, {}
        curr_p = df['Close'].iloc[-1]
        mas = {
            4: round(df['Close'].rolling(80).mean().iloc[-1], 2), 
            5: round(df['Close'].rolling(100).mean().iloc[-1], 2), 
            6: round(df['Close'].rolling(120).mean().iloc[-1], 2), 
            10: round(df['Close'].rolling(200).mean().iloc[-1], 2), 
            12: round(df['Close'].rolling(240).mean().iloc[-1], 2)
        }
        return curr_p, mas
    except: return 0, {}

def get_idx_kr(target_date_str):
    import FinanceDataReader as fdr
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=120)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0.0, 0.0
        curr_p = df['Close'].iloc[-1]
        df_1m = df[df.index <= target_date - pd.DateOffset(months=1)]
        ret_1m = round(((curr_p / df_1m['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m.empty else 0.0
        df_3m = df[df.index <= target_date - pd.DateOffset(months=3)]
        ret_3m = round(((curr_p / df_3m['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m.empty else 0.0
        return ret_1m, ret_3m
    except: return 0.0, 0.0

def get_kospi_timing_for_backtest(ma_months):
    import FinanceDataReader as fdr
    global _CACHE
    try:
        # 💡 지수 데이터를 캐시에서 꺼내 씀 (속도 향상 및 차단 방지)
        if 'KS11' not in _CACHE:
            _CACHE['KS11'] = fdr.DataReader('KS11', '2000-01-01', datetime.today())
        
        df = _CACHE['KS11'].copy()
        if df.empty: return {}

        df['MA'] = df['Close'].rolling(ma_months * 20).mean()
        df['Is_Below'] = df['Close'] < df['MA']
        df_monthly = df.resample('ME' if pd.__version__ >= '2.0.0' else 'M').last()
        
        timing_dict = {}
        for d, val in zip(df_monthly.index, df_monthly['Is_Below']):
            target_month_str = (d + pd.DateOffset(months=1)).strftime('%Y-%m')
            timing_dict[target_month_str] = val
        return timing_dict
    except: return {}

def get_strategy_stocks_korea(df):
    q30 = {c: df[c].quantile(0.7) for c in ['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)']}
    perf_mask = (df['1개월(%)'] >= q30['1개월(%)']) & (df['1개월(%)'] > 0) & \
                (df['3개월(%)'] >= q30['3개월(%)']) & (df['3개월(%)'] > 0) & \
                (df['6개월(%)'] >= q30['6개월(%)']) & (df['6개월(%)'] > 0) & \
                (df['12개월(%)'] >= q30['12개월(%)']) & (df['12개월(%)'] > 0)
    df_perf = df[perf_mask].sort_values('3개월(%)', ascending=False).copy()
    
    spec_mask = (df['12개월(%)'] >= q30['12개월(%)']) & \
                (df['1개월(%)'] >= df['1개월(%)'].quantile(0.9))
    df_spec = df[spec_mask].sort_values('1개월(%)', ascending=False).copy()
    
    return df.copy(), df_perf, df_spec

# ==========================================
# 💡 1. KOSPI 200 전용 백테스트 함수 (완전 독립)
# ==========================================
def run_backtest_k200(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    timing_dict = get_kospi_timing_for_backtest(ma_months)
    records, trade_logs = [], []
    
    for m in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        m_data = df[df['투자월'] == m].copy()
        if m_data.empty: continue

        # [KOSPI 전용 로직] 시총 200위 자르기
        cap_col = '시가총액(억)' if '시가총액(억)' in m_data.columns else '시가총액'
        if cap_col in m_data.columns:
            m_data = m_data.sort_values(by=cap_col, ascending=False).head(200)

        ret_col = '다음달수익률(%)' if '다음달수익률(%)' in m_data.columns else '이번달수익률'
        is_below_ma = timing_dict.get(m, False)
        
        # [KOSPI 전용 로직] 1M, 3M 하락 종목 100개 이상 시 현금 방어기제
        neg_1m, neg_3m = (m_data['1개월(%)'] < 0).sum(), (m_data['3개월(%)'] < 0).sum()
        is_bad_market = (neg_1m >= 100 and neg_3m >= 100)
        
        mult = 0.0 if (apply_timing and (is_bad_market or is_below_ma)) else 1.0
        q_p, q_s = 1.0 - (perf_pct / 100.0), 1.0 - (spec_12m_pct / 100.0)

        # 종목 선정 수식 (퍼펙트: 0% 이상 유지 / 달리는 말: 0% 해제)
        cond_p = (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(q_p)) & (m_data['3개월(%)']>=m_data['3개월(%)'].quantile(q_p)) & \
                 (m_data['6개월(%)']>=m_data['6개월(%)'].quantile(q_p)) & (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_p)) & \
                 (m_data['1개월(%)']>0) & (m_data['3개월(%)']>0) & (m_data['6개월(%)']>0) & (m_data['12개월(%)']>0)

        cond_s = (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_s)) & (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(0.9))

        target_p = m_data[cond_p].sort_values('3개월(%)', ascending=False).iloc[rank_p[0]-1 : rank_p[1]]
        target_s = m_data[cond_s].sort_values('1개월(%)', ascending=False).iloc[rank_s[0]-1 : rank_s[1]]

        ret_p = (target_p[ret_col].mean() * mult) if not target_p.empty else 0.0
        ret_s = (target_s[ret_col].mean() * mult) if not target_s.empty else 0.0


        s_codes = target_s['종목코드'].tolist() # 달리는 말에 선정된 종목코드 추출
        target_p_unique = target_p[~target_p['종목코드'].isin(s_codes)] # 퍼펙트 종목 중 달리는 말과 겹치는 것 제외
        ret_p_unique = (target_p_unique[ret_col].mean() * mult) if not target_p_unique.empty else 0.0
        
        # 달리는말 전체 수익률(50%) + 중복제외된 퍼펙트 수익률(50%)
        ret_ensemble_priority = (ret_s + ret_p_unique) / 2

        # 포트폴리오 1/N 비중 조절
        combined_codes_unique = list(set(target_p['종목코드'].tolist() + target_s['종목코드'].tolist()))
        ret_total_unique = (m_data[m_data['종목코드'].isin(combined_codes_unique)][ret_col].mean() * mult) if combined_codes_unique else 0.0
        
        combined_series_dup = pd.concat([target_p[ret_col], target_s[ret_col]])
        ret_total_dup = (combined_series_dup.mean() * mult) if not combined_series_dup.empty else 0.0

        records.append({
            '투자월': m, 'invested': mult > 0, 
            f'🔥 퍼펙트 상승 ({rank_p[0]}~{rank_p[1]}위)': ret_p, 
            f'🐎 달리는 말 ({rank_s[0]}~{rank_s[1]}위)': ret_s, 
            '앙상블 (50:50 전략)': (ret_p+ret_s)/2,
            '앙상블 (달리는말 우선 50:50)': ret_ensemble_priority,
            '통합 전략 (중복 제외 1/N)': ret_total_unique,
            '통합 전략 (중복 인정 1/N)': ret_total_dup
        })

        if mult > 0:
            for i, (_, r) in enumerate(target_p.iterrows()): trade_logs.append({'투자월': m, '전략': '퍼펙트', '순위': f"{i+rank_p[0]}위", '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
            for i, (_, r) in enumerate(target_s.iterrows()): trade_logs.append({'투자월': m, '전략': '달리는말', '순위': f"{i+rank_s[0]}위", '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
        else:
            trade_logs.append({'투자월': m, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)


# ==========================================
# 💡 2. KOREA 통합 전용 백테스트 함수 (완전 독립)
# ==========================================
def run_backtest_korea(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    timing_dict = get_kospi_timing_for_backtest(ma_months)
    records, trade_logs = [], []
    
    for m in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        m_data = df[df['투자월'] == m].copy()
        if m_data.empty: continue

        # [KOREA 전용 로직] 별도의 시총 200위 자르기 없이 제공된 유니버스 그대로 사용
        ret_col = '다음달수익률(%)' if '다음달수익률(%)' in m_data.columns else '이번달수익률'
        is_below_ma = timing_dict.get(m, False)
        
        # [KOREA 전용 로직] 100개 하락 방어기제 없음. 오직 이평선 이탈 여부만 확인!
        mult = 0.0 if (apply_timing and is_below_ma) else 1.0

        q_p, q_s = 1.0 - (perf_pct / 100.0), 1.0 - (spec_12m_pct / 100.0)

        cond_p = (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(q_p)) & (m_data['3개월(%)']>=m_data['3개월(%)'].quantile(q_p)) & \
                 (m_data['6개월(%)']>=m_data['6개월(%)'].quantile(q_p)) & (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_p)) & \
                 (m_data['1개월(%)']>0) & (m_data['3개월(%)']>0) & (m_data['6개월(%)']>0) & (m_data['12개월(%)']>0)

        cond_s = (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_s)) & (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(0.9))

        target_p = m_data[cond_p].sort_values('3개월(%)', ascending=False).iloc[rank_p[0]-1 : rank_p[1]]
        target_s = m_data[cond_s].sort_values('1개월(%)', ascending=False).iloc[rank_s[0]-1 : rank_s[1]]

        ret_p = (target_p[ret_col].mean() * mult) if not target_p.empty else 0.0
        ret_s = (target_s[ret_col].mean() * mult) if not target_s.empty else 0.0

        s_codes = target_s['종목코드'].tolist() # 달리는 말에 선정된 종목코드 추출
        target_p_unique = target_p[~target_p['종목코드'].isin(s_codes)] # 퍼펙트 종목 중 달리는 말과 겹치는 것 제외
        ret_p_unique = (target_p_unique[ret_col].mean() * mult) if not target_p_unique.empty else 0.0
        
        # 달리는말 전체 수익률(50%) + 중복제외된 퍼펙트 수익률(50%)
        ret_ensemble_priority = (ret_s + ret_p_unique) / 2

        combined_codes_unique = list(set(target_p['종목코드'].tolist() + target_s['종목코드'].tolist()))
        ret_total_unique = (m_data[m_data['종목코드'].isin(combined_codes_unique)][ret_col].mean() * mult) if combined_codes_unique else 0.0
        
        combined_series_dup = pd.concat([target_p[ret_col], target_s[ret_col]])
        ret_total_dup = (combined_series_dup.mean() * mult) if not combined_series_dup.empty else 0.0

        records.append({
            '투자월': m, 'invested': mult > 0, 
            f'🔥 퍼펙트 상승 ({rank_p[0]}~{rank_p[1]}위)': ret_p, 
            f'🐎 달리는 말 ({rank_s[0]}~{rank_s[1]}위)': ret_s, 
            '앙상블 (50:50 전략)': (ret_p+ret_s)/2, 
            '앙상블 (달리는말 우선 50:50)': ret_ensemble_priority,
            '통합 전략 (중복 제외 1/N)': ret_total_unique,
            '통합 전략 (중복 인정 1/N)': ret_total_dup
        })

        if mult > 0:
            for i, (_, r) in enumerate(target_p.iterrows()): trade_logs.append({'투자월': m, '전략': '퍼펙트', '순위': f"{i+rank_p[0]}위", '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
            for i, (_, r) in enumerate(target_s.iterrows()): trade_logs.append({'투자월': m, '전략': '달리는말', '순위': f"{i+rank_s[0]}위", '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
        else:
            trade_logs.append({'투자월': m, '전략': '마켓타이밍', '순위': '-', '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)

