"""승인된 동시 보유 제한의 월별 변경과 실제 엑셀 출력 경로를 검산한다."""
import ast
import io
import json
from pathlib import Path
import subprocess
import sys
import types

import numpy as np
import pandas as pd
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import snowball as sb


def main():
    prices = sb.load_monthly_prices.__wrapped__().loc[:'2026-10']
    source = subprocess.check_output(['git', 'show', 'a97dac8:utils/snowball.py'], text=True, encoding='utf-8')
    baseline = types.ModuleType('baseline_so')
    baseline.__file__ = str(Path('utils/snowball.py').resolve())
    exec(compile(source, baseline.__file__, 'exec'), baseline.__dict__)
    before = baseline.compute_signals_so.__wrapped__(prices)
    after = sb.compute_signals_so.__wrapped__(prices)
    bt = sb.run_backtest_samsung.__wrapped__(prices, after)
    old_bt = baseline.run_backtest_samsung.__wrapped__(prices, before)
    expected = {
        '2017-06': ('SMH·EWY', 'SMH·LIT'), '2017-08': ('SMH·EWY', 'SMH·LIT'),
        '2025-07': ('EWY·SMH', 'EWY·FDN'), '2025-08': ('EWY·SMH', 'EWY·FDN'),
        '2026-05': ('EWY·SMH', 'EWY·LIT'), '2026-06': ('EWY·SMH', 'EWY·LIT'),
        '2026-07': ('EWY·SMH', 'EWY·IBB'), '2026-10': ('EWY·SMH', 'EWY·IBB'),
    }
    pd.testing.assert_series_equal(before.hold.notna(), after.hold.notna())
    changed = before.hold.fillna('__warmup__').ne(after.hold.fillna('__warmup__'))
    changes = {str(month + 1): (before.at[month, 'hold'], after.at[month, 'hold'])
               for month in prices.index[changed]}
    assert changes == expected, changes
    assert not any(isinstance(holds, list) and {'EWY', 'SMH'}.issubset(holds) for holds in after.holds)
    assert len(bt) == len(old_bt) == 183
    previous = {}
    maximum_error = 0.
    for _, row in bt.iterrows():
        month = pd.Period(row.signal_month, 'M')
        holds = after.at[month, 'holds']
        weights = {asset: 1 / len(holds) for asset in holds}
        gross = sum(weight * (prices.loc[month + 1, asset] / prices.loc[month, asset] - 1)
                    for asset, weight in weights.items())
        fee = .0025 * sum(max(weight - previous.get(asset, 0.), 0.) for asset, weight in weights.items())
        maximum_error = max(maximum_error, abs(gross - fee - row.ret_strategy))
        previous = weights
    assert maximum_error < 1e-12

    page = next(Path('pages').glob('6*.py'))
    tree = ast.parse(page.read_text(encoding='utf-8'))
    functions = {'_pct', '_cf_so', '_build_cf_excel', 'build_so_detail',
                 '_heatmap_pivot_for_excel', 'build_report_excel'}
    namespace = {**vars(sb), 'pd': pd, 'np': np}
    # 페이지의 실제 함수를 가져오되 다른 계좌 화면과 네트워크는 실행하지 않는다.
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(page), 'exec'), namespace)
    for _, row in after[after.hold.notna()].iterrows():
        ranked = sorted(sb.SO_OFFENSE_ASSETS, key=lambda asset: row[f'score_{asset}'], reverse=True)
        picks = [asset for asset in ranked[:2] if row[f'abs_{asset}'] > 0]
        if set(picks) == {'EWY', 'SMH'}:
            alternatives = [asset for asset in ranked[2:] if asset not in picks and row[f'abs_{asset}'] > 0]
            picks = [picks[0]] + alternatives[:1]
        assert namespace['_cf_so'](row) == {asset: 1 / len(picks) for asset in picks}
    detail = namespace['build_so_detail'](after, bt)
    july_detail = detail.loc[detail['보유월'] == '2026-07'].iloc[0]
    assert july_detail['보유'] == 'EWY·IBB' and 'SMH 제외' in july_detail['판정 근거']
    excel_detail = namespace['_build_cf_excel'](detail, after, bt, prices, namespace['_cf_so'], lambda asset: asset)
    performance = sb.compute_performance(bt)
    render = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'render_so')
    settings = next(node for node in ast.walk(render) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'settings_dict' for target in node.targets))
    namespace.update(bt=bt, perf=performance, rule_act=None, use_riskoff=True, cost_pct=.25)
    exec(compile(ast.Module(body=[settings], type_ignores=[]), str(page), 'exec'), namespace)
    returns = pd.DataFrame({'투자월': bt.hold_month, '맘·쏘 삼성 전략': bt.ret_strategy * 100})
    excel = namespace['build_report_excel'](
        namespace['settings_dict'], pd.DataFrame({'CAGR': [performance['cagr']]}), excel_detail,
        returns, pd.DataFrame({'자산': bt.cum_strategy.to_numpy()}, index=bt.hold_month),
        pd.DataFrame(), '맘·쏘 삼성 전략')
    book = load_workbook(io.BytesIO(excel), data_only=True)
    rows = list(book['월별_상세근거'].values)
    columns = rows[0]
    july = next(row for row in rows[1:] if row[0] == '2026-07')
    assert july[columns.index('보유')] == 'EWY·IBB' and 'SMH 제외' in july[columns.index('판정 근거')]
    assert any(row[0] == '동시 보유 제한' and 'EWY·SMH' in row[1] for row in book['요약_통계'].values if row[0])
    result = dict(changes=changes, months=len(bt), independent_return_max_error=maximum_error,
                  counterfactual_rows=int(after.hold.notna().sum()), excel_sheets=book.sheetnames,
                  excel_july_hold=july[columns.index('보유')], before=baseline.compute_performance(old_bt),
                  after=performance, latest_hold=after.iloc[-1]['hold'])
    out = Path('기록/2026-11-10-맘쏘삼성-동시보유제한-라이브적용')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['changes', 'months', 'independent_return_max_error',
                                                'counterfactual_rows', 'excel_sheets', 'latest_hold']}, ensure_ascii=False))
    print('LIVE_AUDIT_OK')


if __name__ == '__main__':
    main()
