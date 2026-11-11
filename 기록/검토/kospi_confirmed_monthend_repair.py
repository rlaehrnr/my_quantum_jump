"""동월일 오류가 일별 원천으로 확인된 셀만 별도 교체본에 수정한다."""

import argparse
from collections import Counter
import csv
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FIELDS = dict(zip(('1개월(%)', '3개월(%)', '6개월(%)', '12개월(%)', '이번달수익률'),
                  (1, 3, 6, 12, -1)))
KEY = '투자월'


def git(*args):
    return subprocess.check_output(
        ['git', '-c', 'core.quotepath=false', '-c', 'core.autocrlf=false',
         '-c', 'core.eol=lf', *args], cwd=ROOT)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def daily_source(source, codes):
    parts, sessions, hashes = [], [], {}
    for year in range(2013, 2027):
        path = source / f'marcap-{year}.parquet'
        frame = pd.read_parquet(path, columns=['Date', 'Code', 'Close', 'Changes', 'Volume', 'MarketId'])
        frame = frame.loc[frame.MarketId.eq('STK')].copy()
        sessions.extend(frame.Date.unique())
        frame['Code'] = frame.Code.astype(str).str.zfill(6)
        parts.append(frame.loc[frame.Code.isin(codes), ['Date', 'Code', 'Close', 'Changes', 'Volume']])
        hashes[path.name] = digest(path.read_bytes())
    calendar = pd.DatetimeIndex(sessions).unique().sort_values()
    prices = pd.concat(parts, ignore_index=True).sort_values(['Code', 'Date'])
    assert not prices.duplicated(['Code', 'Date']).any()
    histories = {}
    for code, group in prices.groupby('Code'):
        close = group.Close.to_numpy(dtype=float)
        changes = group.Changes.to_numpy(dtype=float)
        bad = np.ones(len(close), dtype=bool)
        bad[1:] = (~np.isfinite(changes[1:]) | (close[1:] <= 0) | (close[:-1] <= 0) |
                   (abs(close[1:] - changes[1:] - close[:-1]) > 0.01))
        histories[code] = (group.Date.to_numpy(), close, group.Volume.to_numpy(), np.cumsum(bad))
    return calendar, histories, hashes


def repair_cell(value, base, old_day, new_day, history, forward):
    if not value.strip() or not np.isfinite(float(value)):
        return '기존값 없음', None
    if old_day == new_day:
        return '비교일 동일', None
    if history is None:
        return '원천 이력 부족', None
    days, close, volume, breaks = history
    targets = pd.DatetimeIndex([base, old_day, new_day]).to_numpy()
    positions = np.searchsorted(days, targets)
    if (positions >= len(days)).any() or not np.array_equal(days[positions], targets):
        return '원천 이력 부족', None
    if not np.isfinite(volume[positions]).all() or (volume[positions] <= 0).any():
        return '비교일 거래량 0', None
    low, high = positions.min(), positions.max()
    if breaks[high] != breaks[low]:
        return '기준가격 단절', None
    b, old, new = close[positions]
    if not np.isfinite([b, old, new]).all() or min(b, old, new) <= 0:
        return '유효 가격 없음', None
    a, z = (old / b, new / b) if forward else (b / old, b / new)
    old_return, new_return = (a - 1) * 100, (z - 1) * 100
    stored = float(value)
    if abs(stored - new_return) <= .00500001:
        return '월말 값 일치', None
    if abs(stored - old_return) > .00500001:
        return '기존값과 원천 불일치', None
    return '교정', (b, old, new, round(new_return, 2))


def csv_bytes(rows, columns, original):
    buffer = StringIO(newline='')
    newline = '\r\n' if b'\r\n' in original else '\n'
    writer = csv.DictWriter(buffer, columns, lineterminator=newline)
    writer.writeheader()
    writer.writerows(rows)
    encoding = 'utf-8-sig' if original.startswith(b'\xef\xbb\xbf') else 'utf-8'
    return buffer.getvalue().encode(encoding)


def rebuild_month(month, base, columns, hashes):
    source = ROOT / '기록/2026-11-10-KOSPI-최장기간-재구성입력'
    manifest = json.loads((source / 'summary.json').read_text(encoding='utf-8'))['source_manifest']
    assert all(h == manifest[name]['sha256'] for name, h in hashes.items())
    frame = pd.read_csv(source / 'monthly_price_data.csv', dtype={'종목코드': str})
    frame = frame.loc[frame[KEY].eq(month)].copy()
    assert len(frame) == 200 and frame['종목코드'].is_unique
    assert pd.to_datetime(frame['종목선정일']).eq(base).all()
    assert frame['이번달수익률'].notna().all()
    return [{column: '' if pd.isna(row[column]) else row[column] for column in columns}
            for row in frame.to_dict('records')]


def compare(folder, output, latest_month, rebuilt):
    from utils import archive_store, calculator
    from utils.data_loader import load_archive_data

    def load():
        return load_archive_data.__wrapped__(str(folder))

    base = load()
    install = output / 'archive_kospi'
    install.mkdir()
    for file in folder.glob('only_*.csv'):
        (install / file.name).write_bytes(file.read_bytes())
    for file in (output / 'changed_csv').glob('only_*.csv'):
        (install / file.name).write_bytes(file.read_bytes())
    assert (install / latest_month).read_bytes() == (folder / latest_month).read_bytes()
    archive_store.build_history(str(install), verbose=False)
    files = archive_store.archive_csvs(str(install))
    assert archive_store._history_usable(str(install), files[:-1])
    pd.testing.assert_frame_equal(archive_store.load_frames(str(install)),
                                  archive_store.read_csv_frames(files), check_dtype=False)
    changed = load_archive_data.__wrapped__(str(install))
    unchanged_fields = [column for column in base if column not in FIELDS]
    before = base.loc[~base[KEY].isin(rebuilt), unchanged_fields].reset_index(drop=True)
    after = changed.loc[~changed[KEY].isin(rebuilt), unchanged_fields].reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)

    sources = ROOT / '기록/2026-11-06-KOSPI-1996-202610-검산'
    index = pd.read_csv(sources / 'kospi_daily.csv', index_col=0, parse_dates=True)
    gold = pd.read_csv(sources / 'gold_monthly.csv', index_col=0)
    end = latest_month[-11:-4].replace('_', '-')
    variants = {}
    for label, data in [('기존', base), ('교체', changed)]:
        data = data.loc[data[KEY].lt(end)].copy()
        with patch.object(calculator, '_load_kospi_index', return_value=index), \
             patch.object(calculator, 'get_gold_krw_monthly', return_value=gold):
            result, trades, modes = calculator.run_backtest_k200(
                data, 2014, int(end[:4]), 6, True, (1, 6), (1, 2), 30, 30,
                trading_cost_pct=.25, gold_returns=gold.ret.to_dict(), use_gold=True,
                use_gold_ma=True, gold_ma_months=6)
        assert result[KEY].tolist() == sorted(data[KEY].unique())
        result.to_csv(output / f'{label}_월별성과.csv', index=False, encoding='utf-8-sig')
        metrics = {}
        for column in result.columns.difference([KEY, 'invested', '중지 사유'], sort=False):
            monthly = result[column].to_numpy(dtype=float)
            assert np.isfinite(monthly).all()
            wealth = np.r_[1., np.cumprod(1 + monthly / 100)]
            metrics[column] = {'cagr': float((wealth[-1] ** (12 / len(monthly)) - 1) * 100),
                               'mdd': float((wealth / np.maximum.accumulate(wealth) - 1).min() * 100)}
        selections = trades.groupby(KEY).apply(
            lambda group: ' | '.join(f'{row.전략} {row.순위} {row.종목명}' for row in group.itertuples()),
            include_groups=False)
        regime = modes.set_index(KEY)['방어자산'].fillna('주식')
        variants[label] = (metrics, pd.DataFrame({'편입': selections, '배분': regime}))
    diff = variants['기존'][1].add_suffix('_기존').join(variants['교체'][1].add_suffix('_교체'))
    diff = diff[(diff['편입_기존'] != diff['편입_교체']) | (diff['배분_기존'] != diff['배분_교체'])]
    diff.to_csv(output / '편입_및_배분_변경.csv', encoding='utf-8-sig')
    return install, {'기간': [str(base[KEY].min()), result[KEY].iloc[-1]],
                     '편입_및_배분_변경월': len(diff),
                     '배분_변경월': int((diff['배분_기존'] != diff['배분_교체']).sum()),
                     '성과': {label: value[0] for label, value in variants.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ref', default='origin/main')
    args = parser.parse_args()
    ref = git('rev-parse', args.ref).decode().strip()
    legacy = set(git('diff-tree', '--no-commit-id', '--name-only', '-r', 'd262523', '--',
                     'archive_kospi').decode().splitlines())
    modified = set(git('diff', '--name-only', 'd262523', ref, '--',
                       'archive_kospi').decode().splitlines())
    args.output.mkdir()
    changed_dir = args.output / 'changed_csv'
    changed_dir.mkdir()
    with TemporaryDirectory() as temp:
        snapshot = Path(temp)
        with ZipFile(BytesIO(git('archive', '--format=zip', ref, 'archive_kospi', 'utils'))) as archive:
            archive.extractall(snapshot)
        archive_path = snapshot / 'archive_kospi'
        sys.path.insert(0, str(snapshot))
        by_file = {}
        codes = set()
        for path in sorted(archive_path.glob('only_*.csv')):
            rel = f'archive_kospi/{path.name}'
            if rel not in legacy - modified:
                continue
            blob = path.read_bytes()
            reader = csv.DictReader(StringIO(blob.decode('utf-8-sig'), newline=''))
            rows = list(reader)
            by_file[path.name] = (blob, reader.fieldnames, rows)
            codes.update(row['종목코드'].zfill(6) for row in rows)
        calendar, histories, hashes = daily_source(args.source_dir, codes)
        changes, monthly_audit, original_hashes, rebuilt = [], [], {}, {}
        for name, (blob, columns, rows) in by_file.items():
            counts = Counter()
            month = name[-11:-4].replace('_', '-')
            base = pd.Timestamp(rows[0]['종목선정일'])
            assert all(pd.Timestamp(row['종목선정일']) == base for row in rows)
            def trading_day(target):
                return calendar[calendar.searchsorted(target, side='right') - 1]
            selection_month = pd.Period(month) - 1
            month_end = trading_day(selection_month.end_time)
            if base != month_end:
                fixed = rebuild_month(month, month_end, columns, hashes)
                old_codes = {row['종목코드'].zfill(6) for row in rows}
                new_codes = {row['종목코드'] for row in fixed}
                rebuilt[month] = {'기존 선정일': str(base.date()), '교체 선정일': str(month_end.date()),
                                  '기존 행수': len(rows), '교체 행수': len(fixed),
                                  '제외 종목': sorted(old_codes - new_codes), '추가 종목': sorted(new_codes - old_codes)}
                (changed_dir / name).write_bytes(csv_bytes(fixed, columns, blob))
                original_hashes[name] = digest(blob)
                monthly_audit.append({KEY: month, '종목수': len(rows), '선정일 수정으로 월 전체 재구성': 1})
                continue
            for field, n in FIELDS.items():
                old_day = trading_day(base - pd.DateOffset(months=n))
                new_day = trading_day((base.to_period('M') - n).end_time)
                for row in rows:
                    code = row['종목코드'].zfill(6)
                    status, values = repair_cell(row[field], base, old_day, new_day,
                                                 histories.get(code), n == -1)
                    counts[status] += 1
                    if values is None:
                        continue
                    b, old, new, fixed = values
                    changes.append({KEY: month, '종목코드': code, '종목명': row['종목명'],
                                    '항목': field, '선정일': base.date(), '기존 비교일': old_day.date(),
                                    '월말 비교일': new_day.date(), '선정일 종가': b,
                                    '기존 비교일 종가': old, '월말 비교일 종가': new,
                                    '기존값': row[field], '교체값': fixed})
                    row[field] = f'{fixed:.2f}'
            if counts['교정']:
                (changed_dir / name).write_bytes(csv_bytes(rows, columns, blob))
                original_hashes[name] = digest(blob)
            monthly_audit.append({KEY: month, '종목수': len(rows), **counts})
        assert any(row[KEY] == '2017-05' and row['종목코드'] == '009150' and
                   row['항목'] == '1개월(%)' for row in changes)
        latest = sorted(archive_path.glob('only_*.csv'))[-1].name
        install, impact = compare(archive_path, args.output, latest, rebuilt)
        paths = [p for p in install.iterdir() if p.name in original_hashes or p.name.startswith('_history.')]
        for path in paths:
            original_hashes[path.name] = digest((archive_path / path.name).read_bytes())
        report = {'운영기준': ref, '기존 업로드 기준': 'd262523', '점검 파일수': len(by_file),
                  '교정 파일수': len(paths) - 2, '교정 셀수': len(changes), '월 전체 재구성': rebuilt,
                  '파일별 원본 해시': original_hashes, '일별 원천 해시': hashes,
                  '항목별 교정': dict(Counter(row['항목'] for row in changes)), **impact}
        pd.DataFrame(changes).to_csv(args.output / '셀별_교정_근거.csv', index=False, encoding='utf-8-sig')
        pd.DataFrame(monthly_audit).fillna(0).to_csv(args.output / '월별_점검.csv', index=False, encoding='utf-8-sig')
        (args.output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        with ZipFile(args.output / 'KOSPI_월말_교체후보.zip', 'w', compression=ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, f'archive_kospi/{path.name}')
            for name in ['summary.json', '셀별_교정_근거.csv', '월별_점검.csv', '편입_및_배분_변경.csv']:
                archive.write(args.output / name, name)
        print(json.dumps({k: v for k, v in report.items() if '해시' not in k}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
