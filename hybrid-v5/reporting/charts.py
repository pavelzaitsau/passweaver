import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np

LABELS=['10 с','30 с','2 мин','5 мин','10 мин','30 мин','1 ч','2 ч']
COLORS={'v3':'#2563eb','v5':'#0f766e','gain':'#0f766e','loss':'#dc2626'}

def fmt(value, digits=1):
    return '—' if value is None else f'{value:,.{digits}f}'.replace(',', ' ').replace('.', ',')

def charts(stats, output):
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.titleweight': 'bold', 'figure.facecolor': '#ffffff',
                         'axes.labelcolor': '#334155', 'text.color': '#0f172a',
                         'xtick.color': '#475569', 'ytick.color': '#475569'})
    rows = stats['checkpoints']
    seconds = np.array([r['seconds'] for r in rows])
    paths = []
    def save(fig, name):
        fig.savefig(output / (name + '.png'), dpi=190, bbox_inches='tight')
        fig.savefig(output / (name + '.svg'), bbox_inches='tight')
        plt.close(fig)
        paths.append(name)
    def xaxis(ax):
        ax.set_xscale('log')
        ax.set_xlim(seconds[0] / 1.15, seconds[-1] * 1.15)
        ax.set_xticks(seconds, LABELS)
        ax.set_xlabel(f'Отсечка активной проверки при {fmt(float(stats["rate"]), 0)} проверок/с')
        ax.grid(axis='y', color='#e2e8f0', linewidth=.8)
        ax.set_axisbelow(True)
        ax.axvspan(seconds[0]/1.15,600,color='#16a34a',alpha=.055,zorder=0)
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    for version, title in [('v3', 'V3, расширенный бюджет'), ('v5', 'V5')]:
        values = [r[version + '_percent'] for r in rows]
        ax.plot(seconds, values, 'o-', color=COLORS[version], lw=2.5, label=title)
        ax.annotate(f'{rows[-1][version]}/{stats["total"]}', (seconds[-1], values[-1]),
                    xytext=(-8, -19 if version == 'v3' else 10), textcoords='offset points',
                    ha='right', color=COLORS[version], weight='bold')
    xaxis(ax)
    ax.set_ylim(0, max(r[v + '_percent'] for r in rows for v in ('v3', 'v5')) + 7)
    ax.set_ylabel('Найдено, % от всех записей')
    ax.set_title('Охват при одинаковом числе попыток', loc='left', pad=16)
    ax.legend(loc='upper left', frameon=False)
    save(fig, 'coverage')
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    x = np.arange(len(rows))
    gains, losses = [r['gained'] for r in rows], [r['lost'] for r in rows]
    ax.bar(x, gains, color=COLORS['gain'], label='Нашла только V5')
    ax.bar(x, [-n for n in losses], color=COLORS['loss'], label='Нашла только V3')
    ax.plot(x, [r['net'] for r in rows], 'ko-', label='Чистая разница', lw=1.8)
    for i, (g, loss) in enumerate(zip(gains, losses)):
        ax.text(i, g + 2, f'+{g}', ha='center', color=COLORS['gain'], fontsize=10)
        ax.text(i, -loss - 3, f'−{loss}', va='top', ha='center', color=COLORS['loss'], fontsize=10)
    ax.axhline(0, color='#64748b', lw=.8)
    ax.set_xticks(x, LABELS)
    ax.set_ylabel('Количество записей')
    ax.set_title('Новые находки не отменяют потерянные', loc='left', pad=16)
    ax.set_ylim(-max(losses) - 16, max(gains) + 25)
    ax.legend(loc='upper left', frameon=False, ncol=3)
    save(fig, 'paired-gains-losses')
    datasets = list(stats['by_dataset'])
    matrix = np.array([[r['net_pp'] for r in stats['by_dataset'][d]] for d in datasets])
    span = max(1, float(np.abs(matrix).max()))
    cmap = LinearSegmentedColormap.from_list('paired', ['#b91c1c', '#fff7ed', '#0f766e'])
    fig, ax = plt.subplots(figsize=(13, 6.4), layout='constrained')
    im = ax.imshow(matrix, cmap=cmap, norm=TwoSlopeNorm(vmin=-span, vcenter=0, vmax=span), aspect='auto')
    for i, dataset in enumerate(datasets):
        for j, r in enumerate(stats['by_dataset'][dataset]):
            ax.text(j, i, f'{r["net"]:+d}\n{r["net_pp"]:+.1f} п.п.', ha='center', va='center',
                    color='white' if abs(r['net_pp']) > span * .55 else '#0f172a', fontsize=10)
    ax.set_xticks(np.arange(len(rows)), LABELS)
    ax.set_yticks(np.arange(len(datasets)), [f'{d} · n={stats["by_dataset"][d][0]["total"]}' for d in datasets])
    ax.set_title('Где V5 выигрывает и где теряет', loc='left', pad=16)
    fig.colorbar(im, ax=ax, label='Разница охвата V5 − V3, процентные пункты', shrink=.85)
    save(fig, 'datasets')
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    ratio = [r['cost_per_found_ratio_v5_v3'] for r in rows]
    finite = [value for value in ratio if value is not None]
    plotted = [value if value is not None else np.nan for value in ratio]
    ax.plot(seconds, plotted, 'o-', color=COLORS['v5'], lw=2.5)
    ax.axhline(1, color='#64748b', linestyle='--', label='Одинаковая стоимость')
    for sec, value in zip(seconds, ratio):
        if value is not None:
            ax.annotate(f'{value:.2f}×', (sec, value), xytext=(0, 8), textcoords='offset points', ha='center', fontsize=10)
    if not finite:
        ax.text(.5, .5, 'Недостаточно находок для отношения стоимости', transform=ax.transAxes, ha='center')
    xaxis(ax)
    ax.set_ylim(0, max(finite, default=1) * 1.25)
    ax.set_ylabel('Суммарные попытки / находку: V5 ÷ V3')
    ax.set_title('Цена результата с учётом неуспешных попыток', loc='left', pad=16)
    ax.legend(frameon=False)
    save(fig, 'cost')
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    point = np.array([r['net_pp'] for r in rows])
    low, high = [np.array([r[key] for r in rows]) for key in ('net_pp_ci_low', 'net_pp_ci_high')]
    ax.errorbar(np.arange(8), point, yerr=[point - low, high - point], fmt='o', color='#334155', capsize=5, lw=2)
    ax.axhline(0, color='#64748b', linestyle='--')
    ax.set_xticks(np.arange(8), LABELS)
    ax.set_ylabel('Разница охвата V5 − V3, п.п.')
    ax.set_title('Устойчивость разницы при пересэмплировании SSID', loc='left', pad=16)
    ax.grid(axis='y', color='#e2e8f0')
    fig.text(.02, -.025, 'Точечные 95% bootstrap-интервалы. Повторные данные; перенос на новые сети не доказан.', fontsize=10, color='#64748b')
    save(fig, 'stability')
    return paths
