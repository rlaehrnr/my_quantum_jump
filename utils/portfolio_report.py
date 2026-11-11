"""통합포트의 월별 가중 성과와 다운로드 리포트."""
import io

import pandas as pd


def common_portfolio_months(returns, selected):
    """선택 전략이 모두 준비된 최근 연속 달력 구간을 반환한다."""
    available = returns.loc[:, selected].notna().all(axis=1)
    available.index = pd.PeriodIndex(available.index, freq='M')
    complete = available[available]
    if complete.empty:
        return pd.Index([], dtype=str)
    calendar = pd.period_range(available.index.min(), complete.index.max(), freq='M')
    complete_calendar = available.reindex(calendar, fill_value=False)
    missing = complete_calendar[~complete_calendar]
    start = missing.index.max() + 1 if len(missing) else calendar[0]
    return pd.period_range(start, calendar[-1], freq='M').astype(str)


def build_combined_monthly(returns, defensive, weights, *, missing_as_cash=False):
    """이력 없는 배정금을 현금으로 두거나 가용 전략에 재배분한다."""
    selected = pd.Series({key: value for key, value in weights.items() if value > 0}, dtype=float)
    if selected.empty:
        raise ValueError('투자 비중을 하나 이상 입력해주세요.')
    sub = returns.loc[:, selected.index].sort_index()
    if not missing_as_cash:
        sub = sub.dropna(how='all')
    available = sub.notna()
    regime = defensive.reindex(index=sub.index, columns=sub.columns)
    if (available & regime.isna()).any().any():
        raise ValueError('수익률이 있는 전략의 공격·방어 국면 정보가 누락되었습니다.')
    effective = available.mul(selected, axis=1)
    if missing_as_cash:
        effective = effective / selected.sum()
    else:
        effective = effective.div(effective.sum(axis=1), axis=0)
    contributions = sub.fillna(0).mul(effective)
    monthly = pd.DataFrame({'종합전략': contributions.sum(axis=1)})
    monthly['자산배수'] = (1 + monthly['종합전략']).cumprod()
    monthly['누적수익률'] = monthly['자산배수'] - 1
    monthly['낙폭'] = monthly['자산배수'] / monthly['자산배수'].cummax().clip(lower=1.) - 1
    monthly['공격투자비율'] = effective.where(regime.eq(False), 0).sum(axis=1)
    monthly['방어투자비율'] = effective.where(regime.eq(True), 0).sum(axis=1)
    if missing_as_cash:
        monthly['미운용 현금비율'] = (1 - effective.sum(axis=1)).clip(lower=0)
    monthly.index.name = effective.index.name = contributions.index.name = '투자월'
    return monthly, effective, contributions


def build_combined_excel(summary, weights, monthly, effective, contributions,
                         returns, heatmap, mdd, names, cost_rate):
    """화면에서 사용한 계산 결과를 숫자형 셀·서식·차트로 내보낸다."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        book = writer.book
        header = book.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#27374D',
                                  'align': 'center', 'valign': 'vcenter'})
        percent = book.add_format({'num_format': '0.00%'})
        number = book.add_format({'num_format': '#,##0.00'})
        integer = book.add_format({'num_format': '#,##0'})
        title = book.add_format({'bold': True, 'font_size': 14})

        def table(frame, sheet_name, index=False, startrow=0):
            frame.to_excel(writer, sheet_name=sheet_name, index=index, startrow=startrow)
            sheet = writer.sheets[sheet_name]
            columns = ([frame.index.name or '연도'] if index else []) + list(frame.columns)
            for col, label in enumerate(columns):
                sheet.write(startrow, col, label, header)
                sheet.set_column(col, col, max(15, min(32, len(str(label)) * 2 + 3)), percent)
            if index:
                sheet.set_column(0, 0, 15, book.add_format({'num_format': 'General'}))
            sheet.set_row(startrow, 24)
            sheet.hide_gridlines(2)
            sheet.freeze_panes(startrow + 1, 1)
            if len(frame):
                sheet.autofilter(startrow, 0, startrow + len(frame), len(columns) - 1)
            sheet.set_landscape()
            sheet.fit_to_pages(1, 0)
            return sheet

        overview = table(summary, '요약', startrow=4)
        overview.write('A1', '스노우볼 종합전략 리포트', title)
        overview.write('A2', f'성과 집계 {monthly.index[0]} ~ {monthly.index[-1]} · {len(monthly)}개월')
        overview.write('A3', f'교체비용 {cost_rate:.2%} · 현재 입력 비중으로 매월 재배분')
        overview.set_column('A:A', 24)
        overview.set_column('B:B', 19, percent)
        for row, metric in enumerate(summary['지표'], start=5):
            if metric in ['Sharpe', 'Sortino']:
                value = summary.iloc[row - 5]['값']
                if pd.notna(value):
                    overview.write_number(row, 1, float(value), number)
            elif metric == '집계개월':
                overview.write_number(row, 1, int(summary.iloc[row - 5]['값']), integer)
        notes_row = max(24, len(summary) + 7)
        overview.write(notes_row, 0, '공격·방어 비율은 월별 투자 비중의 기간 평균')
        overview.write(notes_row + 1, 0, '전략별 계산 통화 기준 수익률 합산 · 환율 별도')
        if '미운용 현금비율' in monthly:
            overview.write(notes_row + 2, 0, '장기 구간 · 이력 없는 전략 배정금은 해당 월 수익률 0% 현금')
        else:
            overview.write(notes_row + 2, 0, '2017년 이후 네 전략의 연속 공통 확정월')
        overview.set_tab_color('#27374D')

        allocation = table(weights, '계좌비중')
        allocation.set_column('B:B', 21, number)

        detail = monthly.copy()
        detail['가상자산(만원)'] = detail['자산배수'] * weights['입력금액(만원)'].sum()
        detail_sheet = table(detail, '월별성과', index=True)
        detail_sheet.set_column('C:C', 17, number)
        detail_sheet.set_column(len(detail.columns), len(detail.columns), 23, number)
        detail_sheet.set_column('A:A', 14)

        contribution_table = contributions.rename(columns=names).copy()
        contribution_table['종합전략'] = monthly['종합전략']
        if '미운용 현금비율' in monthly:
            contribution_table['미운용 현금비율'] = monthly['미운용 현금비율']
        for key in effective:
            contribution_table[f'비중 - {names.get(key, key)}'] = effective[key]
        table(contribution_table, '월별기여도', index=True)
        table(returns.reindex(monthly.index)[list(effective)].rename(columns=names), '전략별수익률', index=True)

        heatmap = heatmap.copy()
        heatmap.index.name = '연도'
        heatmap_sheet = table(heatmap, '연월히트맵', index=True)
        heatmap_sheet.conditional_format(1, 1, len(heatmap), len(heatmap.columns), {
            'type': '3_color_scale', 'min_color': '#F6B5B5', 'mid_color': '#FFFFFF',
            'max_color': '#B7DFC6', 'mid_type': 'num', 'mid_value': 0})

        drawdowns = mdd.copy()
        drawdowns['MDD'] = pd.to_numeric(drawdowns['MDD'].str.rstrip('%'), errors='raise') / 100
        drawdown_sheet = table(drawdowns, 'MDD기간')
        drawdown_sheet.set_column('B:B', 30)
        drawdown_sheet.set_column('C:C', 18)

        chart = book.add_chart({'type': 'line'})
        chart.add_series({'name': '종합전략 자산배수',
                          'categories': ['월별성과', 1, 0, len(monthly), 0],
                          'values': ['월별성과', 1, 2, len(monthly), 2],
                          'line': {'color': '#365F91', 'width': 2}})
        chart.set_title({'name': '종합전략 누적 자산'})
        chart.set_legend({'none': True})
        chart.set_y_axis({'name': '시작자산 = 1', 'num_format': '0.0'})
        chart.set_size({'width': 650, 'height': 350})
        overview.insert_chart('D5', chart)
        overview.freeze_panes(0, 0)
    return output.getvalue()
