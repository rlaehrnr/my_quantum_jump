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


@st.cache_data(ttl=3600, show_spinner=False)
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
    except Exception as e:
        print(f"⚠️ get_kospi_ma_all({target_date_str}) 오류: {e}")
        return 0, {}


# 💡 [중복 제거] page1, page2에 각각 정의되어 있던 KOSDAQ MA 계산을 utils로 이동.
@st.cache_data(ttl=3600, show_spinner=False)
def get_kosdaq_ma_all(target_date_str):
    """
    특정 날짜 기준 KOSDAQ 현재가와 이동평균선 값들을 반환.
    get_kospi_ma_all과 동일한 구조 (대상 지수만 KQ11).
    """
    import FinanceDataReader as fdr
    target_date = pd.to_datetime(target_date_str)
    start_date = target_date - timedelta(days=450)
    try:
        df = fdr.DataReader('KQ11', start_date, target_date)
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
    except Exception as e:
        print(f"⚠️ get_kosdaq_ma_all({target_date_str}) 오류: {e}")
        return 0, {}


@st.cache_data(ttl=3600, show_spinner=False)
def get_idx_kr(target_date_str):
    """
    KOSPI 지수의 1개월/3개월 수익률 반환.
    
    정의:
    - 1개월 수익률: 전월 말일 종가 대비 (예: 5월 21일 기준 → 4월 말 대비)
    - 3개월 수익률: "3개월 전 월말" 종가 대비
      예) 5월 21일 기준 → 2월 말일 종가 대비 (2월, 3월, 4월 → 3개월 흐른 시점)
          1월 21일 기준 → 10월 말일 종가 대비
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
        
        # 1M 기준: 전월 말일 (이번 달 1일 직전 거래일)
        df_1m_ref = df[df.index < first_day_of_this_month]
        ret_1m = round(((curr_p / df_1m_ref['Close'].iloc[-1]) - 1) * 100, 2) if not df_1m_ref.empty else 0.0
            
        # 3M 기준: "3개월 전 월말 거래일"을 정확히 잡으려면
        #   = (이번달 1일 - 2개월) 직전 거래일
        # 예: 5월 기준 → 5/1 - 2개월 = 3/1 → 3/1 직전 거래일 = 2월 말 거래일 ✓
        # ※ 5/1 - 3개월 = 2/1 → 2/1 직전 거래일 = 1월 말. 1월 말은 4개월 전이므로 틀림.
        ref_anchor = first_day_of_this_month - pd.DateOffset(months=2)
        df_3m_ref = df[df.index < ref_anchor]
        ret_3m = round(((curr_p / df_3m_ref['Close'].iloc[-1]) - 1) * 100, 2) if not df_3m_ref.empty else 0.0
            
        return ret_1m, ret_3m
    except Exception as e:
        print(f"⚠️ get_idx_kr({target_date_str}) 오류: {e}")
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
# 💡 백테스트: KOSPI 200 전용
# 
# K200 모드의 특징:
# - 매월 시총 상위 200위만 사용 (m_data.sort_values(...).head(200))
# - 하락 종목 100개 이상이면 현금 (방어기제 OR 마켓타이밍 조건)
# 
# 거래비용:
# - trading_cost_pct: 편도 거래비용 (%). 기본 0.25%.
# - 풀 리밸런싱 가정 → 매월 매수+매도 양방향 발생 = 비용 × 2
# - 현금 보유 달에는 비용 0 (단, 진입/이탈 시 한 번은 발생하나 단순화 위해 무시)
# ==========================================
def run_backtest_k200(df, start_year, end_year, ma_months, apply_timing, 
                     rank_p, rank_s, perf_pct, spec_12m_pct,
                     trading_cost_pct=0.25):
    """
    Args:
        df: 한국 데이터프레임
        start_year, end_year: 백테스트 기간
        ma_months: MA 기간 (월)
        apply_timing: 마켓타이밍 적용 여부
        rank_p: 퍼펙트 종목 순위 범위 (예: (1, 5) = 1~5위)
        rank_s: 달리는말 종목 순위 범위
        perf_pct: 퍼펙트 컷오프 (%) — 30 = 상위 30%
        spec_12m_pct: 달리는말 12개월 컷오프 (%)
        trading_cost_pct: 편도 거래비용 (%). 기본 0.25%. 0이면 비용 무시.
    """
    timing_dict = get_kospi_timing_for_backtest(ma_months, df_korea=df) if apply_timing else {}
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
        is_below_ma = timing_dict.get(m, False)
        
        # [K200 전용] 하락 종목 100개 이상 시 현금 방어
        neg_1m, neg_3m = (m_data['1개월(%)'] < 0).sum(), (m_data['3개월(%)'] < 0).sum()
        is_bad_market = (neg_1m >= 100 and neg_3m >= 100)
        
        mult = 0.0 if (apply_timing and (is_bad_market or is_below_ma)) else 1.0
        q_p, q_s = 1.0 - (perf_pct / 100.0), 1.0 - (spec_12m_pct / 100.0)

        # 퍼펙트 상승: 1/3/6/12개월 모두 상위 (1-q_p) & 모두 양수
        cond_p = (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(q_p)) & (m_data['3개월(%)']>=m_data['3개월(%)'].quantile(q_p)) & \
                 (m_data['6개월(%)']>=m_data['6개월(%)'].quantile(q_p)) & (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_p)) & \
                 (m_data['1개월(%)']>0) & (m_data['3개월(%)']>0) & (m_data['6개월(%)']>0) & (m_data['12개월(%)']>0)

        # 달리는 말: 12개월 상위 + 1개월 상위 10%
        cond_s = (m_data['12개월(%)']>=m_data['12개월(%)'].quantile(q_s)) & (m_data['1개월(%)']>=m_data['1개월(%)'].quantile(0.9))

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

        # 💡 중지 사유 텍스트 생성 (엑셀 리포트용)
        if not apply_timing:
            stop_reason = ""
        elif mult > 0:
            stop_reason = ""
        else:
            parts = []
            if is_bad_market: parts.append("하락장")
            if is_below_ma: parts.append(f"{ma_months}개월선 이탈")
            stop_reason = " + ".join(parts) if parts else ""

        records.append({
            '투자월': m, 'invested': mult > 0, '중지 사유': stop_reason,
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
