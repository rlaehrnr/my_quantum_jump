# -*- coding: utf-8 -*-
"""push 전 검증 — 두 가지만 본다.

  1. **신호 지문** — 6개 전략의 신호·백테스트가 기준(기본 HEAD) 대비 바뀌었나
  2. **실행**     — app.py와 켜져 있는 페이지가 예외 없이 뜨나

왜 저장해둔 기준값과 대조하지 않나: `data/`가 매일 로봇에 의해 갱신되므로
신호 지문은 코드를 안 고쳐도 달마다 바뀐다. 그래서 **같은 데이터 위에서
'지금 코드'와 '기준 커밋 코드'를 나란히 돌려 비교한다.** 기준 커밋은 git
worktree로 따로 펼치므로 작업 중인 파일을 건드리지 않는다.

    python check.py                # 워킹트리 vs HEAD
    python check.py --base <ref>   # 비교 기준 지정
    python check.py --run-only     # 지문 비교 없이 실행만
    python check.py --print        # 지문만 JSON으로 (내부용)

종료코드 0 = 통과, 1 = 실패.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import warnings

# ⚠️ 캡처는 전부 encoding='utf-8'을 준다 — Windows 기본 cp949는 한글 출력에서 터진다.
REPO = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 지문
def _sha(obj):
    """DataFrame/Series -> 내용 sha256. 셀에 dict·list가 들어 있어도 된다."""
    try:
        import pandas as pd
        if obj is None:
            return 'none'
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            b = obj.to_csv().encode('utf-8', 'replace')
        else:
            b = repr(obj).encode('utf-8', 'replace')
    except Exception as e:
        return 'ERR:' + type(e).__name__
    return hashlib.sha256(b).hexdigest()[:16]


def fingerprints():
    """6개 전략의 (신호, 백테스트) 지문. 라이브 기본 파라미터 그대로."""
    warnings.filterwarnings('ignore')
    sys.path.insert(0, os.getcwd())      # 워크트리 격리: cwd가 스크립트 위치를 이긴다
    from utils import snowball as sb
    # 네트워크 변수를 없앤다 — 로컬 data/ 만 읽게 한다
    sb.KO_RAW_BASE = 'http://127.0.0.1:9/'
    sb.SNOWBALL_RAW_BASE = 'http://127.0.0.1:9/'

    prices = sb.load_monthly_prices()
    div = sb.load_dividend_yield()
    ko = sb.load_ko_prices()
    pen = sb.load_pen_prices()
    sso = sb.load_ssopen_prices()
    mam = sb.load_mamtax_prices()

    plan = [
        ('또 메리츠',  lambda: sb.compute_signals(prices, div),        sb.run_backtest,         prices),
        ('맘쏘 삼성',  lambda: sb.compute_signals_so(prices),          sb.run_backtest_so,      prices),
        ('또 ISA',     lambda: sb.compute_signals_ko(ko),              sb.run_backtest_ko,      ko),
        ('또 연금',    lambda: sb.compute_signals_pension(pen),        sb.run_backtest_pension, pen),
        ('쏘 연금',    lambda: sb.compute_signals_ssopen(sso, prices), sb.run_backtest_ssopen,  sso),
        ('맘 비과세',  lambda: sb.compute_signals_mamtax(mam, prices), sb.run_backtest_mamtax,  mam),
    ]
    out = {}
    for name, sig_fn, bt_fn, px in plan:
        try:
            sig = sig_fn()
            out[name + ' · 신호'] = _sha(sig)
            out[name + ' · 백테스트'] = _sha(bt_fn(px, sig))
        except Exception as e:
            out[name + ' · 신호'] = 'ERR:' + type(e).__name__
            out[name + ' · 백테스트'] = 'ERR:' + type(e).__name__
    return out


# ---------------------------------------------------------------- 실행
def run_pages():
    """app.py + 켜져 있는 페이지를 AppTest로 실제 실행. (예외건수, 상세) 반환.

    AppTest로 페이지 파일을 직접 돌리면 st.page_link가 페이지 레지스트리를
    못 찾아 KeyError를 낸다 — 하네스 한계라 무력화하고 본문을 실행한다.
    """
    warnings.filterwarnings('ignore')
    from streamlit.testing.v1 import AppTest
    shim = ('import streamlit as st\n'
            'st.page_link = lambda *a, **k: None\n'
            'exec(compile(open(r"{p}", encoding="utf-8").read(), r"{p}", "exec"), '
            '{{"__name__": "__main__"}})\n')
    pages_dir = os.path.join(REPO, 'pages')
    targets = ['app.py'] + sorted(
        'pages/' + f for f in os.listdir(pages_dir) if f.endswith('.py'))
    rows, bad = [], 0
    for t in targets:
        try:
            at = AppTest.from_string(shim.format(p=t), default_timeout=300).run()
            errs = [str(e.value) for e in at.exception]
        except Exception as e:
            errs = [type(e).__name__ + ': ' + str(e)]
        bad += len(errs)
        rows.append((t, errs))
    return bad, rows


# ---------------------------------------------------------------- 비교
def changed_py(base):
    """기준 대비 바뀐 .py 목록 (커밋 + 미커밋 + 새 파일 전부)."""
    def q(*a):
        r = subprocess.run(['git', '-C', REPO] + list(a), capture_output=True, text=True, encoding='utf-8', errors='replace')
        return [x for x in r.stdout.splitlines() if x.strip()]
    files = set(q('diff', '--name-only', base, '--', '*.py'))
    files |= set(q('diff', '--name-only', '--', '*.py'))
    files |= set(q('diff', '--name-only', '--cached', '--', '*.py'))
    files |= set(f for f in q('ls-files', '--others', '--exclude-standard')
                 if f.endswith('.py'))
    return sorted(files)


def baseline_fingerprints(base):
    """기준 커밋을 worktree로 따로 펼쳐 같은 방식으로 지문을 뽑는다."""
    tmp = tempfile.mkdtemp(prefix='qjcheck_')
    wt = os.path.join(tmp, 'base')
    r = subprocess.run(['git', '-C', REPO, 'worktree', 'add', '--detach', '-q', wt, base],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        return None, 'worktree 생성 실패: ' + r.stderr.strip()
    try:
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        p = subprocess.run([sys.executable, os.path.abspath(__file__), '--print'],
                           cwd=wt, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
        if p.returncode != 0:
            return None, '기준 지문 계산 실패:\n' + p.stderr[-800:]
        return json.loads(p.stdout), None
    finally:
        subprocess.run(['git', '-C', REPO, 'worktree', 'remove', '--force', wt],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='HEAD')
    ap.add_argument('--run-only', action='store_true')
    ap.add_argument('--print', dest='dump', action='store_true')
    a = ap.parse_args()

    if a.dump:
        print(json.dumps(fingerprints(), ensure_ascii=False))
        return 0

    ok = True
    print('=' * 66)
    print('push 전 검증  ·  기준 ' + a.base)
    print('=' * 66)

    # 1) 신호 지문
    if a.run_only:
        print('\n[1/2] 신호 지문 — 건너뜀 (--run-only)')
    else:
        files = changed_py(a.base)
        if not files:
            print('\n[1/2] 신호 지문 — 비교 안 함. ' + a.base + ' 대비 바뀐 .py가 없다')
        else:
            print('\n[1/2] 신호 지문 — 바뀐 .py %d개: %s%s'
                  % (len(files), ', '.join(files[:6]), ' …' if len(files) > 6 else ''))
            base_fp, err = baseline_fingerprints(a.base)
            if err:
                print('  ⚠️ ' + err)
                ok = False
            else:
                cur = fingerprints()
                diff = [k for k in cur if base_fp.get(k) != cur[k]]
                errk = [k for k, v in cur.items() if str(v).startswith('ERR')]
                for k in sorted(cur):
                    mark = '💥' if k in errk else ('❗바뀜' if k in diff else '✓')
                    print('    %-6s %s' % (mark, k))
                if errk:
                    print('  💥 계산 자체가 실패한 항목 %d개 — 지문 비교가 무의미하다' % len(errk))
                    ok = False
                elif diff:
                    print('  ❗ **신호가 바뀌었다** (%d/%d개).' % (len(diff), len(cur)))
                    print('     의도한 전략 변경이면 사용자 확인을 받고 push한다.')
                    print('     의도한 게 아니면 push하지 않는다.')
                    ok = False
                else:
                    print('  ✅ %d개 지문 전건 일치 — 매매 신호가 바뀌지 않았다' % len(cur))

    # 2) 실행
    print('\n[2/2] 실행 — app.py + 켜져 있는 페이지')
    bad, rows = run_pages()
    for t, errs in rows:
        print('    %-6s %s%s' % ('💥' if errs else '✓', t,
                                 ('  ' + str(errs[:1])) if errs else ''))
    if bad:
        print('  💥 예외 %d건' % bad)
        ok = False
    else:
        print('  ✅ %d개 전부 예외 0건' % len(rows))

    print('\n' + '=' * 66)
    print('통과 — push해도 된다.' if ok else '실패 — push하지 않는다.')
    print('=' * 66)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
