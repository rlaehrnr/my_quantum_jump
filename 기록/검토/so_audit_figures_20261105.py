"""월말 자산·낙폭 그림. 실행: python 기록/검토/so_audit_figures_20261105.py"""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import PercentFormatter

root = Path(__file__).resolve().parents[2]
out = root / '기록/2026-11-05-스노우볼-전략실사'
font = Path('C:/Windows/Fonts/malgun.ttf')
if font.exists():
    plt.rcParams['font.family'] = FontProperties(fname=str(font)).get_name()
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 10
fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True, gridspec_kw={'height_ratios': [1.2, 1]})
series = [('base', '기존 상위 2종', '#b43d36'), ('vol20', '연변동성 목표 20%', '#1a6f9c'),
          ('top4', '상위 4종', '#6e62a7'), ('cash50', '기존 전략 50% · 현금 50%', '#737b80')]
x = np.arange(11)
for key, label, color in series:
    bt = pd.read_csv(out / f'so__{key}__monthly.csv', index_col=0)
    r = bt.loc['2026-01':'2026-10', 'net'].to_numpy()
    nav = np.r_[1., np.cumprod(1 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1
    axes[0].plot(x, nav * 100, label=label, color=color, linewidth=2.3, marker='o', markersize=3)
    axes[1].plot(x, dd, label=label, color=color, linewidth=2.3, marker='o', markersize=3)
axes[0].set_title('맘·쏘 삼성: 연초 수익이 남아 있어도 고점 손실은 커질 수 있다', loc='left', fontsize=15, pad=16)
axes[0].set_ylabel('2025년 말 자산 = 100')
axes[0].legend(frameon=False, ncol=2, loc='upper left', fontsize=9)
axes[1].set_ylabel('올해 월말 고점 대비 낙폭')
axes[1].yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
axes[1].set_ylim(-.365, .02)
axes[1].annotate('기존 -32.68%', (10, -.3268272187), xytext=(8.2, -.35), color='#b43d36', fontsize=11)
axes[1].set_xticks(x, ['2025.12'] + [f'{m}월' for m in range(1, 11)])
for ax in axes:
    ax.axvspan(6, 10, alpha=.055, color='#b43d36')
    ax.grid(axis='y', alpha=.2)
    ax.spines[['top', 'right']].set_visible(False)
fig.text(.08, .025, '2011.08~2026.10 월봉 검증 중 2026년 경로 · USD 기준 · 매수 증가분 비용 0.25% · 현금 수익 0%\n'
         '대안은 손실을 본 뒤 검토한 가상 결과이며 미래 성과·낙폭 상한을 보장하지 않는다.', fontsize=9, color='#555')
fig.subplots_adjust(left=.1, right=.96, top=.91, bottom=.12, hspace=.17)
fig.savefig(out / 'so_2026_wealth_drawdown.png', dpi=160)
print(out / 'so_2026_wealth_drawdown.png')
