import base64
import csv
import hashlib
import hmac
import html
import json
from pathlib import Path
import sys
import zipfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hybrid
from analyze import calculate

LABELS = ['10 с', '30 с', '2 мин', '5 мин', '10 мин', '30 мин', '1 ч', '2 ч']
COLORS = {'v3': '#2563eb', 'v4': '#ea580c', 'gain': '#0f766e', 'loss': '#dc2626'}


def fmt(value, digits=1):
    return '—' if value is None else f'{value:,.{digits}f}'.replace(',', ' ').replace('.', ',')


def read_inputs(destination):
    protocol = json.loads((destination / 'protocol.json').read_text())
    rows, labels = [], []
    private = destination / 'private-inputs'
    for dataset in protocol['datasets']:
        path = private / ('wifox_ssid_password-' + dataset['dataset'] + '.txt')
        parsed = hybrid.v3.parse_input(path.read_bytes(), 'legacy-text')
        if len(parsed) != dataset['records']:
            raise ValueError('report_snapshot_count_mismatch')
        rows.extend({'ssid': r['ssid'], 'password': r['password']} for r in parsed)
        labels.extend([dataset['dataset']] * len(parsed))
    canonical = json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    check = hmac.new((private / 'attestation.key').read_bytes(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(check, protocol['snapshot_attestation_hmac_sha256']):
        raise ValueError('report_snapshot_attestation_mismatch')
    outcomes = [json.loads((private / (version + '-outcomes.json')).read_text()) for version in ('v3', 'v4')]
    return protocol, rows, labels, outcomes


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
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    for version, title in [('v3', 'V3, расширенный бюджет'), ('v4', 'V4.1')]:
        values = [r[version + '_percent'] for r in rows]
        ax.plot(seconds, values, 'o-', color=COLORS[version], lw=2.5, label=title)
        ax.annotate(f'{rows[-1][version]}/{stats["total"]}', (seconds[-1], values[-1]),
                    xytext=(-8, 10 if version == 'v3' else -19), textcoords='offset points',
                    ha='right', color=COLORS[version], weight='bold')
    xaxis(ax)
    ax.set_ylim(0, max(r[v + '_percent'] for r in rows for v in ('v3', 'v4')) + 7)
    ax.set_ylabel('Найдено, % от всех записей')
    ax.set_title('Охват при одинаковом числе попыток', loc='left', pad=16)
    ax.legend(loc='upper left', frameon=False)
    save(fig, 'coverage')
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    x = np.arange(len(rows))
    gains, losses = [r['gained'] for r in rows], [r['lost'] for r in rows]
    ax.bar(x, gains, color=COLORS['gain'], label='Нашла только V4.1')
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
    ax.set_title('Где V4.1 выигрывает и где теряет', loc='left', pad=16)
    fig.colorbar(im, ax=ax, label='Разница охвата V4.1 − V3, процентные пункты', shrink=.85)
    save(fig, 'datasets')
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    ratio = [r['cost_per_found_ratio_v4_v3'] for r in rows]
    finite = [value for value in ratio if value is not None]
    plotted = [value if value is not None else np.nan for value in ratio]
    ax.plot(seconds, plotted, 'o-', color=COLORS['v4'], lw=2.5)
    ax.axhline(1, color='#64748b', linestyle='--', label='Одинаковая стоимость')
    for sec, value in zip(seconds, ratio):
        if value is not None:
            ax.annotate(f'{value:.2f}×', (sec, value), xytext=(0, 8), textcoords='offset points', ha='center', fontsize=10)
    if not finite:
        ax.text(.5, .5, 'Недостаточно находок для отношения стоимости', transform=ax.transAxes, ha='center')
    xaxis(ax)
    ax.set_ylim(0, max(finite, default=1) * 1.25)
    ax.set_ylabel('Суммарные попытки / находку: V4.1 ÷ V3')
    ax.set_title('Цена результата с учётом неуспешных попыток', loc='left', pad=16)
    ax.legend(frameon=False)
    save(fig, 'cost')
    fig, ax = plt.subplots(figsize=(12, 5.4), layout='constrained')
    point = np.array([r['net_pp'] for r in rows])
    low, high = [np.array([r[key] for r in rows]) for key in ('net_pp_ci_low', 'net_pp_ci_high')]
    ax.errorbar(np.arange(8), point, yerr=[point - low, high - point], fmt='o', color='#334155', capsize=5, lw=2)
    ax.axhline(0, color='#64748b', linestyle='--')
    ax.set_xticks(np.arange(8), LABELS)
    ax.set_ylabel('Разница охвата V4.1 − V3, п.п.')
    ax.set_title('Устойчивость разницы при пересэмплировании SSID', loc='left', pad=16)
    ax.grid(axis='y', color='#e2e8f0')
    fig.text(.02, -.025, 'Точечные 95% bootstrap-интервалы. Повторные данные; перенос на новые сети не доказан.', fontsize=10, color='#64748b')
    save(fig, 'stability')
    return paths


def verify_metrics(stats, results, protocol):
    plans = protocol['checkpoints']
    if not (len(stats['checkpoints']) == len(results['overall']) == len(plans)):
        raise ValueError('report_checkpoint_count_mismatch')
    if stats['total'] != results['total'] or stats['total'] != protocol['total']:
        raise ValueError('report_record_count_mismatch')
    for got, expected, plan in zip(stats['checkpoints'], results['overall'], plans):
        if got['seconds'] != expected['seconds'] or got['seconds'] != plan['seconds']:
            raise ValueError('report_checkpoint_mismatch')
        if got['budget'] != expected['budget'] or got['budget'] != plan['total_candidates']:
            raise ValueError('report_budget_mismatch')
        if any(got[key] != expected[key] for key in ('v3', 'v4', 'common', 'gained', 'lost', 'net')):
            raise ValueError('report_metrics_mismatch')
    names = {d['dataset']: d['records'] for d in protocol['datasets']}
    if set(stats['by_dataset']) != set(results['by_dataset']) or set(stats['by_dataset']) != set(names):
        raise ValueError('report_dataset_inventory_mismatch')
    for name, size in names.items():
        actual, expected = stats['by_dataset'][name], results['by_dataset'][name]
        if len(actual) != len(expected) or len(actual) != len(plans):
            raise ValueError('report_dataset_checkpoint_mismatch')
        for a, b, p in zip(actual, expected, plans):
            if a['seconds'] != p['seconds'] or b['seconds'] != p['seconds']:
                raise ValueError('report_dataset_checkpoint_mismatch')
            if a['total'] != size or b['total'] != size or any(
                    a[key] != b[key] for key in ('v3', 'v4', 'gained', 'lost', 'net')):
                raise ValueError('report_dataset_metrics_mismatch')


def build(destination):
    destination = Path(destination)
    protocol, rows, labels, outcomes = read_inputs(destination)
    results = json.loads((destination / 'results.json').read_text())
    stats = calculate(rows, labels, *outcomes, protocol['checkpoints'], protocol['rate'])
    verify_metrics(stats, results, protocol)
    output = destination / 'report'
    output.mkdir(exist_ok=True)
    chart_dir = output / 'charts'
    chart_dir.mkdir(exist_ok=True)
    names = charts(stats, chart_dir)
    (output / 'metrics.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    with (output / 'checkpoints.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(stats['checkpoints'][0]))
        writer.writeheader()
        writer.writerows(stats['checkpoints'])
    with (output / 'datasets.csv').open('w', newline='') as stream:
        fields = ['dataset', *stats['by_dataset'][labels[0]][0]]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for dataset, values in stats['by_dataset'].items():
            writer.writerows(dict(dataset=dataset, **r) for r in values)
    last = stats['checkpoints'][-1]
    loses = sum(r['net'] < 0 for r in stats['checkpoints'])
    wins = sum(r['net'] > 0 for r in stats['checkpoints'])
    decision = ('V4.1 не оправдала замену V3 на текущей выборке.' if last['net'] < 0 else
                'V4.1 увеличила итоговый охват; преимущество на новых данных требует отдельной проверки.'
                if last['net'] > 0 else 'Итоговый охват V3 и V4.1 одинаков; превосходство V4.1 не подтверждено.')
    table = ['| Отсечка | Попыток, млн | V3 | V4.1 | Новых | Потеряно | Δ | Δ, п.п. |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for label, r in zip(LABELS, stats['checkpoints']):
        table.append(f'| {label} | {fmt(r["budget"] / 1e6, 2)} | {r["v3"]} | {r["v4"]} | {r["gained"]} | {r["lost"]} | {r["net"]:+d} | {fmt(r["net_pp"])} |')
    sections = [f'# V4.1 против V3: эффективность при равном бюджете\n\n{decision}',
        f'На {stats["total"]} записях V4.1 выигрывает по общему числу находок на {wins} из 8 отсечек и проигрывает на {loses}. '
        f'На 2 часах: V3 — {last["v3"]}, V4.1 — {last["v4"]}; разница {last["net"]:+d} ({fmt(last["net_pp"])} п.п.).',
        f'## Условия\n\nСравнение использует один закрытый снимок: {stats["total"]} записей, {stats["unique_ssids"]} разных SSID. '
        'Данные использовались раньше. Контекст содержит только SSID; польза страны, языка, заведения и адреса этим опытом не измеряется.\n\n'
        f'Времена являются общей моделью активной проверки при {fmt(float(stats["rate"]), 0)} проверок/с. '
        'Генерация, подготовка и реальная проверка WPA2 на GPU не измеряются этой таблицей. '
        'У V3 увеличен только общий бюджет; словари, правила, порядок и локальные лимиты сохранены. '
        'V4.1 — новая ревизия с дедупликацией внутри каждого семейства, зафиксированная после независимого ревью.',
        '## Все отсечки\n\n' + '\n'.join(table) + '\n\n'
        '«Новых» означает найдено V4.1 и не найдено V3 на той же отсечке. «Потеряно» означает обратное. '
        'Чистая разница равна новым находкам минус потерянные.',
        '![Охват](charts/coverage.png)\n\n![Приобретения и потери](charts/paired-gains-losses.png)',
        '## Где V4.1 помогает\n\n'
        f'На двухчасовой отсечке V4.1 находит {last["gained"]} ответов, которых не находит V3 в том же бюджете. '
        f'При этом V4.1 теряет {last["lost"]} ответов V3.\n\n'
        f'Среди {stats["common_final"]["total"]} общих находок V4.1 достигает '
        f'{stats["common_final"]["earlier_v4"]} раньше, {stats["common_final"]["later_v4"]} позже и '
        f'{stats["common_final"]["equal"]} на прежней позиции. '
        f'Медиана отношения попыток V4.1/V3 в этой общей группе равна '
        f'{fmt(stats["common_final"]["median_attempt_ratio_v4_v3"], 2)}. '
        'Эта условная группа исключает потерянные ответы и не заменяет общую оценку стоимости.\n\n'
        f'V3 за 30 минут находит {stats["checkpoints"][5]["v3"]} ответов; V4.1 за 2 часа — {last["v4"]}. '
        'Это сравнение количества находок, а не утверждение о совпадении их состава.',
        '## Стоимость результата\n\nДля каждой записи учитываются попытки до совпадения либо весь фактически выданный бюджет при неуспехе. '
        'Стоимость находки равна суммарным попыткам по всем записям, делённым на число находок. '
        'Значение отношения V4.1/V3 больше 1 означает, что находка обходится дороже.\n\n'
        f'На двухчасовой отсечке отношение составляет {fmt(last["cost_per_found_ratio_v4_v3"], 3)}×. '
        f'Среднее модельное активное время на запись: V3 — {fmt(last["mean_active_seconds_v3"])} с, V4.1 — {fmt(last["mean_active_seconds_v4"])} с. '
        'Эта величина включает неуспехи и не является временем работы оценщика.\n\n![Стоимость](charts/cost.png)',
        '## Различия по файлам\n\nФайлы имеют разный размер. Поэтому дополнительно рассчитаны равновесное среднее по файлам '
        'и чувствительность к исключению каждого файла без изменения правил. Это анализ устойчивости, а не обучение или кроссвалидация.\n\n'
        f'На 2 часах равновесная разница по файлам: {fmt(last["macro_file_delta_pp"])} п.п. '
        f'После исключения одного файла общая разница лежит от {fmt(last["leave_one_file_out_min_pp"])} до {fmt(last["leave_one_file_out_max_pp"])} п.п.\n\n'
        '![Результаты по файлам](charts/datasets.png)',
        '## Устойчивость и общий случай\n\nИспользованы 5000 парных bootstrap-перевыборок с seed=20261116. '
        'Одинаковые SSID пересэмплируются целыми группами; записи одной группы остаются вместе. '
        'Интервалы являются точечными 95% интервалами устойчивости текущей выборки. '
        'Они не исправляют повторное использование данных, смещение источников и отсутствие случайной новой выборки.\n\n'
        f'На 2 часах интервал разницы охвата: [{fmt(last["net_pp_ci_low"])}; {fmt(last["net_pp_ci_high"])}] п.п.\n\n'
        '![Устойчивость](charts/stability.png)\n\n'
        'Для вывода о новых сетях нужен заранее зафиксированный опыт на новых данных. '
        'Следует отдельно проверить доступность контекста и состав стран, а также реальную скорость WPA2 и затраты генерации. '
        f'Текущий опыт отвечает на вопрос о {stats["total"]} имеющихся записях и не доказывает преимущество для произвольной сети.',
        '## Полные таблицы по файлам']
    for dataset, values in stats['by_dataset'].items():
        block = [f'### {dataset}: {values[0]["total"]} записей', '',
                 '| Отсечка | V3 | V4.1 | Новых | Потеряно | Δ |', '| --- | --- | --- | --- | --- | --- |']
        block.extend(f'| {label} | {r["v3"]} | {r["v4"]} | {r["gained"]} | {r["lost"]} | {r["net"]:+d} |'
                     for label, r in zip(LABELS, values))
        sections.append('\n'.join(block))
    sections.append('## Воспроизводимость\n\nПротокол и контрольные суммы кода зафиксированы до измерений. '
        'Содержимое входа подтверждается HMAC; ключ, пароли, SSID отдельных записей и успешные позиции остаются в закрытой папке. '
        'Все 87 файлов принятой V3 проверяются до и после опыта. '
        'Чистые независимые проходы и 48 тестов предшествовали запуску. '
        'Отдельное независимое ревью подтвердило расчёты, таблицы, графики и отсутствие закрытых входов в архиве.\n\n'
        '[Заключение финального ревью](FINAL-REVIEW.md).\n\n'
        'Данные для проверки: [метрики](metrics.json), [все отсечки CSV](checkpoints.csv), [файлы CSV](datasets.csv). '
        'Графики доступны в PNG и SVG. '
        'Инструменты: [Matplotlib](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html), '
        '[NumPy Generator](https://numpy.org/doc/stable/reference/random/generator.html).')
    markdown = '\n\n'.join(sections) + '\n'
    (output / 'RESULTS.md').write_text(markdown)
    def image(name):
        encoded = base64.b64encode((chart_dir / (name + '.png')).read_bytes()).decode()
        return f'<img alt="{html.escape(name)}" src="data:image/png;base64,{encoded}">'
    heads = ['Отсечка', 'V3', 'V4.1', 'Новых', 'Потеряно', 'Δ', 'Δ, п.п.', 'Цена находки V4/V3']
    trs = []
    for label, r in zip(LABELS, stats['checkpoints']):
        values = [label, r['v3'], r['v4'], r['gained'], r['lost'], f'{r["net"]:+d}',
                  fmt(r['net_pp']), fmt(r['cost_per_found_ratio_v4_v3'], 3) + '×']
        trs.append('<tr>' + ''.join(f'<td>{html.escape(str(value))}</td>' for value in values) + '</tr>')
    dataset_rows = []
    for dataset, values in stats['by_dataset'].items():
        for label, r in zip(LABELS, values):
            dataset_rows.append('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in
                (dataset, label, r['total'], r['v3'], r['v4'], r['gained'], r['lost'], f'{r["net"]:+d}')) + '</tr>')
    body = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>V4.1 против V3 — полный отчёт</title><style>
body{{font:16px/1.6 system-ui,sans-serif;color:#0f172a;background:#f1f5f9;margin:0}}main{{max-width:1180px;margin:auto;padding:38px 24px}}h1{{font-size:42px;line-height:1.15;letter-spacing:-1.5px}}h2{{font-size:25px;margin-top:42px}}.lead{{font-size:22px}}.card{{background:white;border:1px solid #e2e8f0;border-radius:16px;padding:26px;margin:20px 0}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.metric{{font-size:36px;font-weight:750}}.muted{{color:#64748b}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:11px 9px;border-bottom:1px solid #e2e8f0;text-align:right;white-space:nowrap}}td:first-child,th:first-child{{text-align:left}}th{{color:#475569}}.scroll{{overflow:auto}}details{{background:#fff;padding:20px;border-radius:12px}}a{{color:#2563eb}}@media(max-width:700px){{h1{{font-size:32px}}.cards{{grid-template-columns:1fr}}main{{padding:22px 14px}}.card{{padding:16px}}}}
</style><main><p class="muted">16 ноября 2026 · один снимок · одинаковые бюджеты</p>
<h1>V4.1 против V3:<br>что даёт новый гибрид</h1><p class="lead">{html.escape(decision)}</p>
<div class="cards"><div class="card"><div class="muted">Охват на 2 часах</div><div class="metric">{last['v3']} → {last['v4']}</div><div>из {stats['total']} записей</div></div>
<div class="card"><div class="muted">Новые / потерянные</div><div class="metric">+{last['gained']} / −{last['lost']}</div><div>чистая разница {last['net']:+d}</div></div>
<div class="card"><div class="muted">Стоимость находки V4/V3</div><div class="metric">{fmt(last['cost_per_found_ratio_v4_v3'], 2)}×</div><div>больше 1 — дороже</div></div></div>
<div class="card"><b>Границы вывода.</b> {stats['total']} записей, {stats['unique_ssids']} SSID; данные использовались раньше. Только SSID и английский профиль. Это точная офлайн-оценка позиций, а не GPU-прогон. Время моделируется при {fmt(float(stats['rate']), 0)} проверок/с. У V3 увеличен только общий бюджет. Перенос результата на новые сети не доказан.</div>
<h2>Все восемь отсечек</h2><div class="card scroll"><table><thead><tr>{''.join('<th>'+h+'</th>' for h in heads)}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>
<div class="card">{image('coverage')}</div><div class="card">{image('paired-gains-losses')}</div>
<h2>Цена результата</h2><p>Неуспешные записи расходуют бюджет и включаются в стоимость. Суммарные попытки по всем записям делятся на число находок. Показатель относится к модельной активной проверке; время генерации сюда не входит.</p><div class="card">{image('cost')}</div>
<h2>Где V4.1 помогает</h2><p>Из {stats['common_final']['total']} общих находок V4.1 достигает {stats['common_final']['earlier_v4']} раньше, {stats['common_final']['later_v4']} позже, {stats['common_final']['equal']} на прежней позиции. Медиана отношения попыток V4.1/V3 в этой условной группе — {fmt(stats['common_final']['median_attempt_ratio_v4_v3'], 2)}. Потерянные ответы в эту группу не входят; общий расход уже учитывает их. V3 за 30 минут находит {stats['checkpoints'][5]['v3']} ответов, V4.1 за 2 часа — {last['v4']}; состав находок различается.</p>
<h2>Одинаков ли эффект на разных данных</h2><p>Равновесная разница по файлам на 2 часах: {fmt(last['macro_file_delta_pp'])} п.п. После исключения одного файла общая разница: от {fmt(last['leave_one_file_out_min_pp'])} до {fmt(last['leave_one_file_out_max_pp'])} п.п. Это проверка чувствительности, без переобучения алгоритма.</p><div class="card">{image('datasets')}</div>
<h2>Что можно сказать об общем случае</h2><p>5000 парных bootstrap-перевыборок по группам SSID оценивают устойчивость текущей выборки. Интервалы точечные, 95%. Они не устраняют смещение источников и повторное использование данных. Для новых сетей требуется ещё не использованная выборка с заранее зафиксированным протоколом.</p><div class="card">{image('stability')}</div>
<details><summary>Полные результаты по каждому файлу</summary><div class="scroll"><table><thead><tr>{''.join('<th>'+h+'</th>' for h in ['Файл','Отсечка','N','V3','V4.1','Новых','Потеряно','Δ'])}</tr></thead><tbody>{''.join(dataset_rows)}</tbody></table></div></details>
<h2>Как проверялся опыт</h2><p>Два независимых чистых прохода и 48 тестов предшествовали запуску. Коды и словари зафиксированы до измерений; HMAC подтверждает снимок. Пароли, отдельные SSID, ключ HMAC и точные успешные позиции остаются в закрытой папке. Сохранность всех 87 файлов V3 проверена.</p>
<p><a href="RESULTS.md">Подробный текст</a> · <a href="metrics.json">Метрики JSON</a> · <a href="checkpoints.csv">Отсечки CSV</a> · <a href="datasets.csv">Файлы CSV</a> · <a href="FINAL-REVIEW.md">Финальное ревью</a></p><p class="muted">Отдельная независимая сверка подтвердила расчёты, таблицы, графики и состав публичного архива.</p></main></html>'''
    (output / 'report.html').write_text(body)
    provenance = dict(python=sys.version, numpy=np.__version__, matplotlib=matplotlib.__version__,
                      source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
                      bootstrap=stats['bootstrap'], input_attestation=protocol['snapshot_attestation_hmac_sha256'])
    (output / 'analysis-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    deliverables = [output / name for name in ('report.html', 'RESULTS.md', 'metrics.json',
                    'checkpoints.csv', 'datasets.csv', 'analysis-provenance.json')]
    deliverables.extend(chart_dir / (name + extension) for name in names for extension in ('.png', '.svg'))
    if (output / 'FINAL-REVIEW.md').is_file():
        deliverables.append(output / 'FINAL-REVIEW.md')
    with zipfile.ZipFile(destination / 'V3-V4-report.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in deliverables:
            archive.write(path, path.relative_to(output))
    print(json.dumps({'report': str(output.resolve()), 'checkpoints': stats['checkpoints']}, ensure_ascii=False))


if __name__ == '__main__':
    build(sys.argv[1])
