"""계좌별 배정 후보와 같은 확정월에서의 통합 성과 비교."""
from itertools import permutations

import numpy as np
import pandas as pd

from utils.portfolio_report import common_portfolio_months


def allocation_choices(amounts, keys):
    """계좌마다 잔액 전부를 배정하고 전략은 조합 안에서 한 번씩만 사용한다."""
    if not any(amounts):
        return []
    return [(assignment, dict(zip(assignment, amounts)))
            for assignment in permutations(keys, len(amounts))]


def comparison_window(returns, last_closed_month):
    """미확정월과 누락된 달 이전의 이력을 집계에서 제외한다."""
    closed = returns.loc[returns.index <= last_closed_month]
    span = common_portfolio_months(closed, list(returns.columns))
    return closed.loc[span]


def recovery_periods(equity):
    """직전 고점에서 회복월 또는 관측 종료월까지의 낙폭 구간."""
    peak = trough = pd.Period(equity.index[0], freq='M') - 1
    peak_value = trough_value = 1.0
    periods = []
    for label, value in equity.items():
        month = pd.Period(label, freq='M')
        if value >= peak_value * (1 - 1e-12):
            if trough_value < peak_value:
                periods.append(_period(peak, trough, month, month, trough_value / peak_value - 1))
            peak = trough = month
            peak_value = trough_value = max(peak_value, value)
        elif value < trough_value:
            trough, trough_value = month, value
    if trough_value < peak_value:
        periods.append(_period(peak, trough, month, None, trough_value / peak_value - 1))
    return periods


def _period(peak, trough, end, recovered, depth):
    return {'peak': str(peak), 'trough': str(trough), 'mdd': depth,
            'recovered': str(recovered) if recovered is not None else None,
            'months': end.ordinal - peak.ordinal}


def portfolio_stats(returns):
    equity = (1 + returns).cumprod()
    drawdown = equity / equity.cummax().clip(lower=1.0) - 1.0
    mean = returns.mean()
    volatility = returns.std(ddof=0)
    downside = np.sqrt(returns.clip(upper=0).pow(2).mean())
    periods = recovery_periods(equity)
    worst_count = max(1, int(np.ceil(len(returns) * 0.05)))
    return {
        'n': len(returns), 'cum': equity.iloc[-1] - 1,
        'cagr': equity.iloc[-1] ** (12 / len(returns)) - 1,
        'mdd': drawdown.min(),
        'sharpe': mean * np.sqrt(12) / volatility if volatility > 1e-12 else np.nan,
        'sortino': mean * np.sqrt(12) / downside if downside > 1e-12 else np.nan,
        'win': (returns > 0).mean(), 'equity': equity, 'dd': drawdown, 'ret': returns,
        'worst': returns.min(), 'tail': returns.nsmallest(worst_count).mean(),
        'longest': max((period['months'] for period in periods), default=0),
        'periods': periods,
    }


SCORE_METRICS = ['cagr', 'sharpe', 'sortino', 'mdd', 'worst', 'tail', 'longest']


def compare_allocations(returns, candidates):
    """금액 비중이 같은 배정은 한 번만 계산하고 순위에도 한 번만 반영한다."""
    profiles = {}
    groups = []
    for _, amounts in candidates:
        profile = tuple(amounts.get(key, 0) for key in returns.columns)
        if profile not in profiles:
            weights = pd.Series(profile, index=returns.columns) / sum(profile)
            profiles[profile] = portfolio_stats(returns @ weights)
        groups.append(profile)
    metrics = pd.DataFrame([profiles[profile] for profile in profiles], columns=SCORE_METRICS)
    # 부동소수점 연산 순서에서 생긴 미세한 오차는 순위 동점으로 취급한다.
    metrics = metrics.round(10)
    ranks = metrics.rank(pct=True, ascending=True)
    ranks['longest'] = metrics['longest'].rank(pct=True, ascending=False)
    # 분모가 0인 샤프·소르티노는 표에서 미산출, 종합 점수에서 중간 순위.
    scores = dict(zip(profiles, ranks.fillna(0.5).mean(axis=1) * 100))
    return [(profiles[profile], scores[profile]) for profile in groups]
