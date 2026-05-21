import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

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


# ==========================================
# 💡 [버그 해결] Streamlit 캐시로 KOSPI 데이터 1회만 로드
# ==========================================
@st.cache_data(ttl="6h", show_spinner=False)
def _load_kospi_index():
    """KOSPI 일별 데이터를 캐시. 6시간마다 갱신."""
    import FinanceDataReader as fdr
    return fdr.DataReader('KS11', '2000-01-01', datetime.today())


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
    start_date = target_date - timedelta(days=150)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0.0, 0.0
        
        curr_p = df['Close'].iloc[-1]
        first_day_of_this_month = target_date.replace(day=1)
        
        # 1M (이번 달) 기준: 전월 말일
        df_1m_ref = df[df.index < first_day_of_this_month]
        ret_1m = round(((curr_p / df_1m_ref['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m_ref.empty else 0.0
            
        # 3M 기준: 3개월 전 동일자 (표준 정의)
        three_months_ago = target_date - pd.DateOffset(months=3)
        df_3m_ref = df[df.index <= three_months_ago]
        ret_3m = round(((curr_p / df_3m_ref['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m_ref.empty else 0.0
            
        return ret_1m, ret_3m
    except: 
        return 0.0, 0.0


# ==========================================
# 💡 [버그 1, 2, 3 해결] 정확한 거래일 기준 + 종목선정일 정렬
# ==========================================
def get_kospi_timing_for_backtest(ma_months, df_korea=None):
    """
    KOSPI 이동평균선 이탈 여부를 timing_dict로 반환.
    
    버그 수정 사항:
    1. ma_months * 20 (부정확) → ma_months * 20 거래일을 그대로 쓰되, df_korea가 있으면
       실제 종목선정일에 맞춰 정확히 계산 (look-ahead bias 제거)
    2. _CACHE 전역 변수 → @st.cache_data 사용 (위 _load_kospi_index)
    3. df_korea의 '종목선정일' 컬럼이 있으면 그 날짜 기준 MA 계산 (시점 정렬)
    
    Args:
        ma_months: 이동평균 기간 (월 단위). 6이면 120거래일 (= 6 * 20)
        df_korea: 한국 데이터프레임. 있으면 실제 종목선정일 사용.
    
    Returns:
        dict: {'YYYY-MM': True/False} — True면 MA 이탈(=현금 보유)
    """
    try:
        df = _load_kospi_index().copy()
        if df.empty: return {}
        
        ma_days = ma_months * 20  # 정확한 거래일 수
        df['MA'] = df['Close'].rolling(ma_days).mean()
        df['Is_Below'] = df['Close'] < df['MA']
        
        timing_dict = {}
        
        # === Path A: df_korea가 있고 종목선정일 컬럼이 있으면, 그 날짜로 정확히 매칭 ===
        if df_korea is not None and '종목선정일' in df_korea.columns:
            for ym in sorted(df_korea['투자월'].dropna().unique()):
                month_data = df_korea[df_korea['투자월'] == ym]
                if month_data.empty:
                    timing_dict[ym] = False
                    continue
                
                sel_date = pd.to_datetime(month_data['종목선정일'].iloc[0])
                
                # 선정일 이하 거래일 중 마지막
                avail = df[df.index <= sel_date]
                if len(avail) < ma_days:
                    timing_dict[ym] = False
                    continue
                
                price = avail['Close'].iloc[-1]
                ma = avail['MA'].iloc[-1]
                if pd.isna(ma):
                    timing_dict[ym] = False
                else:
                    timing_dict[ym] = bool(price < ma)
            return timing_dict
        
        # === Path B: 폴백 — 각 월의 1일 직전 거래일을 종목선정일로 가정 ===
        # 모든 거래일에 대해 "이 거래일이 어느 달의 종목선정일인가?" 매핑
        # 종목선정일 = 다음 달의 1일 직전 거래일
        # 즉, 6월 데이터의 종목선정일 = 6월 1일 직전 거래일 = 보통 5월 말 거래일
        
        df_with_month = df.copy()
        df_with_month['next_bday_month'] = None
        
        # 각 거래일에 대해, 그 다음 거래일이 다른 달이면 이 날이 "그 다음 달의 종목선정일"
        next_dates = pd.Series(df_with_month.index).shift(-1)
        for i in range(len(df_with_month) - 1):
            curr_date = df_with_month.index[i]
            next_date = next_dates.iloc[i]
            if pd.isna(next_date):
                continue
            if next_date.month != curr_date.month or next_date.year != curr_date.year:
                # curr_date가 어느 달의 마지막 거래일 → 다음 달의 종목선정일
                target_ym = next_date.strftime('%Y-%m')
                price = df_with_month['Close'].iloc[i]
                ma = df_with_month['MA'].iloc[i]
                if pd.notna(ma):
                    timing_dict[target_ym] = bool(price < ma)
        
        return timing_dict
    
    except Exception as e:
        print(f"⚠️ get_kospi_timing_for_backtest 오류: {e}")
        return {}


def get_strategy_stocks_korea(df):
    """현재 시점 전략 종목 선정 (현재 데이터에 적용)."""
    # NaN 안전 처리
    df_valid = df.dropna(subset=['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)'])
    if df_valid.empty:
        return df.copy(), pd.DataFrame(), pd.DataFrame()
    
    q30 = {c: df_valid[c].quantile(0.7) for c in ['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)']}
    perf_mask = (df_valid['1개월(%)'] >= q30['1개월(%)']) & (df_valid['1개월(%)'] > 0) & \
                (df_valid['3개월(%)'] >= q30['3개월(%)']) & (df_valid['3개월(%)'] > 0) & \
                (df_valid['6개월(%)'] >= q30['6개월(%)']) & (df_valid['6개월(%)'] > 0) & \
                (df_valid['12개월(%)'] >= q30['12개월(%)']) & (df_valid['12개월(%)'] > 0)
    df_perf = df_valid[perf_mask].sort_values('3개월(%)', ascending=False).copy()
    
    spec_mask = (df_valid['12개월(%)'] >= q30['12개월(%)']) & \
                (df_valid['1개월(%)'] >= df_valid['1개월(%)'].quantile(0.9))
    df_spec = df_valid[spec_mask].sort_values('1개월(%)', ascending=False).copy()
    
    return df.copy(), df_perf, df_spec


# ==========================================
# 💡 1. KOSPI 200 전용 백테스트 함수
# ==========================================
def run_backtest_k200(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    # 💡 수정: df 전달로 종목선정일 정렬
    timing_dict = get_kospi_timing_for_backtest(ma_months, df_korea=df) if apply_timing else {}
    records, trade_logs = [], []
    
    for m in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        m_data = df[df['투자월'] == m].copy()
        if m_data.empty: continue

        cap_col = '시가총액(억)' if '시가총액(억)' in m_data.columns else '시가총액'
        if cap_col in m_data.columns:
            m_data = m_data.sort_values(by=cap_col, ascending=False).head(200)

        ret_col = '다음달수익률(%)' if '다음달수익률(%)' in m_data.columns else '이번달수익률'
        is_below_ma = timing_dict.get(m, False)
        
        neg_1m, neg_3m = (m_data['1개월(%)'] < 0).sum(), (m_data['3개월(%)'] < 0).sum()
        is_bad_market = (neg_1m >= 100 and neg_3m >= 100)
        
        mult = 0.0 if (apply_timing and (is_bad_market or is_below_ma)) else 1.0
        q_p, q_s = 1.0 - (perf_pct / 100.0), 1.0 - (spec_12m_pct / 100.0)

        cond_p = (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(q_p)) & (m_data['3개월(%)']>=m_data['3개월(%)'].quantile(q_p)) & \
                 (m_data['6개월(%)']>=m_data['6개월(%)'].quantile(q_p)) & (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_p)) & \
                 (m_data['1개월(%)']>0) & (m_data['3개월(%)']>0) & (m_data['6개월(%)']>0) & (m_data['12개월(%)']>0)

        cond_s = (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_s)) & (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(0.9))

        target_p = m_data[cond_p].sort_values('3개월(%)', ascending=False).iloc[rank_p[0]-1 : rank_p[1]]
        target_s = m_data[cond_s].sort_values('1개월(%)', ascending=False).iloc[rank_s[0]-1 : rank_s[1]]

        ret_p = (target_p[ret_col].mean() * mult) if not target_p.empty else 0.0
        ret_s = (target_s[ret_col].mean() * mult) if not target_s.empty else 0.0

        s_codes = target_s['종목코드'].tolist()
        target_p_unique = target_p[~target_p['종목코드'].isin(s_codes)]
        ret_p_unique = (target_p_unique[ret_col].mean() * mult) if not target_p_unique.empty else 0.0
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


# ==========================================
# 💡 2. KOREA 통합 전용 백테스트 함수
# ==========================================
def run_backtest_korea(df, start_year, end_year, ma_months, apply_timing, rank_p, rank_s, perf_pct, spec_12m_pct):
    # 💡 수정: df 전달로 종목선정일 정렬
    timing_dict = get_kospi_timing_for_backtest(ma_months, df_korea=df) if apply_timing else {}
    records, trade_logs = [], []
    
    for m in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        m_data = df[df['투자월'] == m].copy()
        if m_data.empty: continue

        ret_col = '다음달수익률(%)' if '다음달수익률(%)' in m_data.columns else '이번달수익률'
        is_below_ma = timing_dict.get(m, False)
        
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

        s_codes = target_s['종목코드'].tolist()
        target_p_unique = target_p[~target_p['종목코드'].isin(s_codes)]
        ret_p_unique = (target_p_unique[ret_col].mean() * mult) if not target_p_unique.empty else 0.0
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
