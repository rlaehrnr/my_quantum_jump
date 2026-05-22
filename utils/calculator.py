import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

# ==========================================
# 🇰🇷 한국 주식 전용 함수
# ==========================================

# 대통령 사이클 모델: 임기 N년차에 위험한 달 (참고용 시그널)
# 키 = 사이클 연차(1~8), 값 = 위험한 월(들)
PRESIDENTIAL_DANGEROUS_MONTHS = {
    1: [2, 9], 2: [2, 4, 6, 9, 12], 3: [8, 9], 4: [3],
    5: [], 6: [7], 7: [6, 8, 11, 12], 8: [1, 6, 9, 10, 11]
}

def get_cycle_year(current_year):
    """2021년 기준으로 사이클 연차 계산 (1~8 순환)."""
    years_since = current_year - 2021
    return (years_since % 8) + 1


# ==========================================
# 💡 KOSPI 지수 데이터 캐싱
# Streamlit의 @st.cache_data로 6시간마다 갱신.
# 전역 변수 _CACHE 대신 사용 → 사용자별 격리 + 자동 만료.
# ==========================================
@st.cache_data(ttl="6h", show_spinner=False)
def _load_kospi_index():
    """KOSPI 일별 종가 데이터를 받아서 캐시. 6시간마다 갱신."""
    import FinanceDataReader as fdr
    return fdr.DataReader('KS11', '2000-01-01', datetime.today())


def get_kospi_ma_all(target_date_str):
    """
    특정 날짜 기준 KOSPI 현재가와 여러 이동평균선 값을 반환.
    
    Returns:
        (현재가, {4: 80일선, 5: 100일선, 6: 120일선, 10: 200일선, 12: 240일선})
        에러 시 (0, {})
    """
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
    """
    KOSPI 지수의 1개월/3개월 수익률 반환.
    
    정의:
    - 1개월 수익률: 전월 말일 종가 대비 (예: 5월 21일 기준 → 4월 말 대비)
    - 3개월 수익률: 3개월 전 월말 종가 대비 (예: 5월 21일 기준 → 2월 말 대비)
    
    💡 [버그 수정] 기존 코드는 months=2를 빼서 사실상 2개월 전 월말과 비교했음.
    이제 months=3을 빼서 의도대로 3개월 전 월말과 비교.
    """
    import FinanceDataReader as fdr
    target_date = pd.to_datetime(target_date_str)
    # 3개월 전 월말까지 커버하려면 약 5개월 = 150일 이상 데이터 필요
    start_date = target_date - timedelta(days=180)
    try:
        df = fdr.DataReader('KS11', start_date, target_date)
        if df.empty: return 0.0, 0.0
        
        curr_p = df['Close'].iloc[-1]
        first_day_of_this_month = target_date.replace(day=1)
        
        # 1M 기준: 전월 말일 (이번 달 1일보다 이전 마지막 거래일)
        df_1m_ref = df[df.index < first_day_of_this_month]
        ret_1m = round(((curr_p / df_1m_ref['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m_ref.empty else 0.0
            
        # 💡 [수정] 3M 기준: 3개월 전 월말 종가
        # 예: 5월 21일 기준 → 2월 28일 (3개월 전 월말)
        # 계산: 이번달 1일에서 3개월 빼면 (3월에서 -3 = 12월 또는 4월에서 -3 = 1월 식으로 어색해질 수 있어,
        # 명시적으로 "이번달 1일 - 3개월" 이전 마지막 거래일을 잡으면 정확히 3개월 전 월말 거래일이 됨)
        three_months_ago_first = first_day_of_this_month - pd.DateOffset(months=3)
        # three_months_ago_first 이전의 마지막 거래일 = 그 직전 달의 마지막 거래일 = 우리가 원하는 시점
        # 잠깐, 더 정확하게는: target_date - 3개월 = 그 시점의 월말
        # 예: 5월 21일 - 3개월 = 2월 21일 → 우리는 2월 말일이 필요
        # 그래서: 3월 1일 - 1거래일 = 2월 28일
        three_months_ago_month_start = first_day_of_this_month - pd.DateOffset(months=2)
        # 5월 1일에서 2개월 뒤로 = 3월 1일. 3월 1일보다 작은 마지막 거래일 = 2월 말 거래일.
        df_3m_ref = df[df.index < three_months_ago_month_start]
        ret_3m = round(((curr_p / df_3m_ref['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m_ref.empty else 0.0
            
        return ret_1m, ret_3m
    except: 
        return 0.0, 0.0


# ==========================================
# KOSPI 마켓타이밍 (백테스트용)
# 
# 핵심 수정 사항 (look-ahead bias 제거):
# 1. 전역 _CACHE 대신 @st.cache_data 사용 (위 _load_kospi_index)
# 2. df_korea가 주어지면 실제 종목선정일 기준으로 정확히 MA 비교
# 3. df_korea 없으면 폴백 — 매 달 마지막 거래일 기준
# ==========================================
def get_kospi_timing_for_backtest(ma_months, df_korea=None):
    """
    KOSPI 이동평균선 이탈 여부를 timing_dict로 반환.
    
    Args:
        ma_months: 이동평균 기간 (월). 6 → 120거래일 (6*20)
        df_korea: 한국 데이터프레임 (옵션). 있으면 실제 종목선정일에 맞춰 정확히 계산.
    
    Returns:
        dict: {'YYYY-MM': True/False}. True면 MA 이탈 = 현금 보유 신호.
    """
    try:
        df = _load_kospi_index().copy()
        if df.empty: return {}
        
        ma_days = ma_months * 20  # 한 달 ≈ 20거래일
        df['MA'] = df['Close'].rolling(ma_days).mean()
        df['Is_Below'] = df['Close'] < df['MA']
        
        timing_dict = {}
        
        # === Path A: df_korea에 '종목선정일' 컬럼 있으면 정확히 매칭 ===
        if df_korea is not None and '종목선정일' in df_korea.columns:
            for ym in sorted(df_korea['투자월'].dropna().unique()):
                month_data = df_korea[df_korea['투자월'] == ym]
                if month_data.empty:
                    timing_dict[ym] = False
                    continue
                
                sel_date = pd.to_datetime(month_data['종목선정일'].iloc[0])
                avail = df[df.index <= sel_date]
                if len(avail) < ma_days:
                    timing_dict[ym] = False
                    continue
                
                price = avail['Close'].iloc[-1]
                ma = avail['MA'].iloc[-1]
                timing_dict[ym] = False if pd.isna(ma) else bool(price < ma)
            return timing_dict
        
        # === Path B: 폴백 — 매 달의 마지막 거래일 기준 ===
        # 각 거래일을 보고 "다음 거래일이 다른 달이면 이 날이 그 달의 마지막 거래일"
        next_dates = pd.Series(df.index).shift(-1)
        for i in range(len(df) - 1):
            curr_date = df.index[i]
            next_date = next_dates.iloc[i]
            if pd.isna(next_date):
                continue
            if next_date.month != curr_date.month or next_date.year != curr_date.year:
                # curr_date가 그 달의 마지막 거래일 → 다음 달의 종목선정일
                target_ym = next_date.strftime('%Y-%m')
                price = df['Close'].iloc[i]
                ma = df['MA'].iloc[i]
                if pd.notna(ma):
                    timing_dict[target_ym] = bool(price < ma)
        
        return timing_dict
    
    except Exception as e:
        print(f"⚠️ get_kospi_timing_for_backtest 오류: {e}")
        return {}


def get_strategy_stocks_korea(df):
    """
    현재 시점 전략 종목 선정 (실시간 데이터에 적용).
    
    Returns:
        (전체 df, 퍼펙트 종목, 달리는말 종목)
    
    NaN 처리: NaN >= 분위수는 False, NaN > 0도 False 이므로 자동 제외됨.
    별도 dropna 없이도 신규 상장 종목은 마스크에서 자연스럽게 빠짐.
    """
    q30 = {c: df[c].quantile(0.7) for c in ['1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)']}
    
    # 퍼펙트 상승: 1/3/6/12개월 모두 상위 30% & 모두 양수
    perf_mask = (df['1개월(%)'] >= q30['1개월(%)']) & (df['1개월(%)'] > 0) & \
                (df['3개월(%)'] >= q30['3개월(%)']) & (df['3개월(%)'] > 0) & \
                (df['6개월(%)'] >= q30['6개월(%)']) & (df['6개월(%)'] > 0) & \
                (df['12개월(%)'] >= q30['12개월(%)']) & (df['12개월(%)'] > 0)
    df_perf = df[perf_mask].sort_values('3개월(%)', ascending=False).copy()
    
    # 달리는 말: 12개월 상위 30% & 1개월 상위 10%
    spec_mask = (df['12개월(%)'] >= q30['12개월(%)']) & \
                (df['1개월(%)'] >= df['1개월(%)'].quantile(0.9))
    df_spec = df[spec_mask].sort_values('1개월(%)', ascending=False).copy()
    
    return df.copy(), df_perf, df_spec


# ==========================================
# 💡 백테스트: KOSPI 200 전용 [업그레이드]
# 
# K200 모드의 특징:
# - 매월 시총 상위 200위만 사용 (m_data.sort_values(...).head(200))
# - 마켓타이밍을 3개의 독립 필터로 분리:
#   * 필터 A: 1개월 하락 ≥ N개 AND 3개월 하락 ≥ N개 시 현금
#   * 필터 B: KOSPI N개월 이동평균선 이탈 시 현금
#   * 필터 C: 200종목 3개월 평균 수익률 < 0% 시 현금
# - 각 필터마다 on/off + 결합방식(AND/OR) 선택 가능
# 
# 거래비용:
# - trading_cost_pct: 편도 거래비용 (%). 기본 0.25%.
# - 풀 리밸런싱 가정 → 매월 매수+매도 양방향 발생 = 비용 × 2
# - 현금 보유 달에는 비용 0 (단, 진입/이탈 시 한 번은 발생하나 단순화 위해 무시)
# ==========================================
def run_backtest_k200(df, start_year, end_year, ma_months, apply_timing, 
                     rank_p, rank_s, perf_pct, spec_12m_pct,
                     trading_cost_pct=0.25,
                     spec_1m_pct=10,
                     bad_market_threshold=100,
                     filter_a_enabled=True, filter_a_mode='OR',
                     filter_b_enabled=True, filter_b_mode='OR',
                     filter_c_enabled=False, filter_c_mode='OR'):
    """
    Args:
        df: 한국 데이터프레임
        start_year, end_year: 백테스트 기간
        ma_months: MA 기간 (월). 필터 B에서 사용.
        apply_timing: 마켓타이밍 마스터 스위치. False면 모든 필터 무시.
        rank_p: 퍼펙트 종목 순위 범위 (예: (1, 5) = 1~5위)
        rank_s: 달리는말 종목 순위 범위
        perf_pct: 퍼펙트 컷오프 (%) — 30 = 상위 30%
        spec_12m_pct: 달리는말 12개월 컷오프 (%)
        trading_cost_pct: 편도 거래비용 (%). 기본 0.25%. 0이면 비용 무시.
        spec_1m_pct: 달리는말 1개월 수익률 컷오프 (%). 기본 10 = 상위 10%.
        bad_market_threshold: 필터 A의 1&3개월 하락 종목 수 임계값. 기본 100.
        filter_a_enabled: 필터 A (하락 종목 수) on/off
        filter_a_mode: 'OR' or 'AND' — 다른 활성 필터와의 결합 방식
        filter_b_enabled: 필터 B (MA 이탈) on/off
        filter_b_mode: 'OR' or 'AND'
        filter_c_enabled: 필터 C (3개월 평균 < 0) on/off
        filter_c_mode: 'OR' or 'AND'
    
    Note on 결합 방식:
        활성화된 필터들의 결합 방식은 "각 필터의 mode"로 결정됩니다.
        - 한 필터의 mode='OR'면 그 필터 단독으로 신호 발생 가능
        - mode='AND'인 필터들은 모두 함께 신호 발생해야 함
        예: A(OR), B(AND), C(AND) → A 단독 OR (B AND C)
    """
    # 필터 B는 마켓타이밍 적용 시에만 의미가 있음
    timing_dict = get_kospi_timing_for_backtest(ma_months, df_korea=df) if (apply_timing and filter_b_enabled) else {}
    records, trade_logs = [], []
    
    # 거래비용: 매월 풀 리밸런싱 가정 → 왕복 = 편도 × 2
    cost_pct = trading_cost_pct * 2.0  # 매월 차감되는 비용 (%)
    
    for m in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        m_data = df[df['투자월'] == m].copy()
        if m_data.empty: continue

        # [K200 전용] 시총 상위 200위 자르기
        cap_col = '시가총액(억)' if '시가총액(억)' in m_data.columns else '시가총액'
        if cap_col in m_data.columns:
            m_data = m_data.sort_values(by=cap_col, ascending=False).head(200)

        ret_col = '다음달수익률(%)' if '다음달수익률(%)' in m_data.columns else '이번달수익률'
        
        # === 각 필터 신호 계산 ===
        # 필터 A: 1개월 하락 ≥ N개 AND 3개월 하락 ≥ N개 (기존 OR → AND로 변경됨)
        neg_1m = (m_data['1개월(%)'] < 0).sum()
        neg_3m = (m_data['3개월(%)'] < 0).sum()
        signal_a = (neg_1m >= bad_market_threshold) and (neg_3m >= bad_market_threshold)
        
        # 필터 B: MA 이탈
        signal_b = bool(timing_dict.get(m, False))
        
        # 필터 C: 200종목 3개월 평균 수익률 < 0
        signal_c = bool(m_data['3개월(%)'].mean() < 0)
        
        # === 활성 필터들을 결합 방식에 따라 평가 ===
        # OR 그룹: 활성+OR 필터 중 하나라도 True면 신호
        # AND 그룹: 활성+AND 필터가 모두 True여야 신호
        # 최종 신호 = OR그룹 OR AND그룹
        or_signals, and_signals = [], []
        if filter_a_enabled:
            (or_signals if filter_a_mode == 'OR' else and_signals).append(signal_a)
        if filter_b_enabled:
            (or_signals if filter_b_mode == 'OR' else and_signals).append(signal_b)
        if filter_c_enabled:
            (or_signals if filter_c_mode == 'OR' else and_signals).append(signal_c)
        
        or_part = any(or_signals) if or_signals else False
        and_part = all(and_signals) if and_signals else False
        # AND 그룹이 비어있으면 False (기여 안 함). OR 그룹도 비어있으면 False.
        any_active = filter_a_enabled or filter_b_enabled or filter_c_enabled
        cash_signal = (or_part or and_part) if any_active else False
        
        mult = 0.0 if (apply_timing and cash_signal) else 1.0
        q_p, q_s = 1.0 - (perf_pct / 100.0), 1.0 - (spec_12m_pct / 100.0)
        q_s_1m = 1.0 - (spec_1m_pct / 100.0)  # 달리는말 1개월 컷오프

        # 퍼펙트 상승: 1/3/6/12개월 모두 상위 (1-q_p) & 모두 양수
        cond_p = (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(q_p)) & (m_data['3개월(%)']>=m_data['3개월(%)'].quantile(q_p)) & \
                 (m_data['6개월(%)']>=m_data['6개월(%)'].quantile(q_p)) & (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_p)) & \
                 (m_data['1개월(%)']>0) & (m_data['3개월(%)']>0) & (m_data['6개월(%)']>0) & (m_data['12개월(%)']>0)

        # 달리는 말: 12개월 상위 spec_12m_pct% + 1개월 상위 spec_1m_pct%
        cond_s = (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_s)) & (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(q_s_1m))

        target_p = m_data[cond_p].sort_values('3개월(%)', ascending=False).iloc[rank_p[0]-1 : rank_p[1]]
        target_s = m_data[cond_s].sort_values('1개월(%)', ascending=False).iloc[rank_s[0]-1 : rank_s[1]]

        # 각 전략 수익률 (마켓타이밍 mult 적용)
        ret_p = (target_p[ret_col].mean() * mult) if not target_p.empty else 0.0
        ret_s = (target_s[ret_col].mean() * mult) if not target_s.empty else 0.0

        # 💡 거래비용 차감 (투자 중인 달만)
        if mult > 0:
            ret_p -= cost_pct
            ret_s -= cost_pct

        # 달리는말 우선 앙상블 (B 50% + B와 중복 안 되는 A 50%)
        s_codes = target_s['종목코드'].tolist()
        target_p_unique = target_p[~target_p['종목코드'].isin(s_codes)]
        ret_p_unique = (target_p_unique[ret_col].mean() * mult) if not target_p_unique.empty else 0.0
        if mult > 0:
            ret_p_unique -= cost_pct
        ret_ensemble_priority = (ret_s + ret_p_unique) / 2

        # 통합 1/N (A∪B): 중복 제거 후 동일가중
        combined_codes_unique = list(set(target_p['종목코드'].tolist() + target_s['종목코드'].tolist()))
        ret_total_unique = (m_data[m_data['종목코드'].isin(combined_codes_unique)][ret_col].mean() * mult) if combined_codes_unique else 0.0
        if mult > 0:
            ret_total_unique -= cost_pct
        
        # 통합 1/N (A+B): 중복 허용 (같은 종목이 양쪽에 들어가면 2배 비중)
        combined_series_dup = pd.concat([target_p[ret_col], target_s[ret_col]])
        ret_total_dup = (combined_series_dup.mean() * mult) if not combined_series_dup.empty else 0.0
        if mult > 0:
            ret_total_dup -= cost_pct

        records.append({
            '투자월': m, 'invested': mult > 0, 
            f'🔥 퍼펙트 상승 ({rank_p[0]}~{rank_p[1]}위)': ret_p, 
            f'🐎 달리는 말 ({rank_s[0]}~{rank_s[1]}위)': ret_s, 
            '앙상블 (50:50 전략)': (ret_p+ret_s)/2,
            '앙상블 (달리는말 우선 50:50)': ret_ensemble_priority,
            '통합 전략 (중복 제외 1/N)': ret_total_unique,
            '통합 전략 (중복 인정 1/N)': ret_total_dup
        })

        # 거래 로그
        if mult > 0:
            for i, (_, r) in enumerate(target_p.iterrows()):
                trade_logs.append({'투자월': m, '전략': '퍼펙트', '순위': f"{i+rank_p[0]}위", 
                                  '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
            for i, (_, r) in enumerate(target_s.iterrows()):
                trade_logs.append({'투자월': m, '전략': '달리는말', '순위': f"{i+rank_s[0]}위", 
                                  '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
        else:
            trade_logs.append({'투자월': m, '전략': '마켓타이밍', '순위': '-', 
                              '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)


# ==========================================
# 💡 백테스트: KOREA 통합 (시총 컷오프 없음)
# 
# KOREA 모드 특징:
# - 데이터에 들어있는 종목 그대로 사용 (시총 200위 자르기 X)
# - 하락 종목 100개 방어기제 없음
# - 오직 KOSPI 120일선 이탈만 마켓타이밍으로 사용
# ==========================================
def run_backtest_korea(df, start_year, end_year, ma_months, apply_timing, 
                      rank_p, rank_s, perf_pct, spec_12m_pct,
                      trading_cost_pct=0.25):
    """
    KOREA 통합 백테스트. 인자는 run_backtest_k200과 동일.
    trading_cost_pct: 편도 거래비용 (%). 기본 0.25%.
    """
    timing_dict = get_kospi_timing_for_backtest(ma_months, df_korea=df) if apply_timing else {}
    records, trade_logs = [], []
    cost_pct = trading_cost_pct * 2.0
    
    for m in sorted(df['투자월'].dropna().unique()):
        m_yr = int(m.split('-')[0])
        if not (start_year <= m_yr <= end_year): continue
        m_data = df[df['투자월'] == m].copy()
        if m_data.empty: continue

        ret_col = '다음달수익률(%)' if '다음달수익률(%)' in m_data.columns else '이번달수익률'
        is_below_ma = timing_dict.get(m, False)
        
        # [KOREA 전용] 오직 KOSPI 이평선만 마켓타이밍으로 사용
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

        if mult > 0:
            ret_p -= cost_pct
            ret_s -= cost_pct

        s_codes = target_s['종목코드'].tolist()
        target_p_unique = target_p[~target_p['종목코드'].isin(s_codes)]
        ret_p_unique = (target_p_unique[ret_col].mean() * mult) if not target_p_unique.empty else 0.0
        if mult > 0:
            ret_p_unique -= cost_pct
        ret_ensemble_priority = (ret_s + ret_p_unique) / 2

        combined_codes_unique = list(set(target_p['종목코드'].tolist() + target_s['종목코드'].tolist()))
        ret_total_unique = (m_data[m_data['종목코드'].isin(combined_codes_unique)][ret_col].mean() * mult) if combined_codes_unique else 0.0
        if mult > 0:
            ret_total_unique -= cost_pct
        
        combined_series_dup = pd.concat([target_p[ret_col], target_s[ret_col]])
        ret_total_dup = (combined_series_dup.mean() * mult) if not combined_series_dup.empty else 0.0
        if mult > 0:
            ret_total_dup -= cost_pct

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
            for i, (_, r) in enumerate(target_p.iterrows()):
                trade_logs.append({'투자월': m, '전략': '퍼펙트', '순위': f"{i+rank_p[0]}위", 
                                  '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
            for i, (_, r) in enumerate(target_s.iterrows()):
                trade_logs.append({'투자월': m, '전략': '달리는말', '순위': f"{i+rank_s[0]}위", 
                                  '종목명': r.get('종목명', r['종목코드']), '수익률(%)': r[ret_col]})
        else:
            trade_logs.append({'투자월': m, '전략': '마켓타이밍', '순위': '-', 
                              '종목명': '현금보유(CASH)', '수익률(%)': 0.0})
            
    return pd.DataFrame(records), pd.DataFrame(trade_logs)
