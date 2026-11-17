import base64
import csv
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import compare_v5
import charts

spec = importlib.util.spec_from_file_location('verified_analysis', ROOT.parent / 'hybrid-v4/reporting/analyze.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def rename(value):
    if isinstance(value, dict):
        return {key.replace('v4', 'v5'): rename(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rename(item) for item in value]
    return value


def build(destination=ROOT / 'results/comparison-v5'):
    destination = Path(destination)
    cached = compare_v5.read_cache()
    protocol = json.loads((destination / 'protocol.json').read_text())
    results = json.loads((destination / 'results.json').read_text())
    private = destination / 'private-inputs'
    main_bytes = (private / 'v5-outcomes.json').read_bytes()
    control_bytes = (private / 'v5-without-prince-outcomes.json').read_bytes()
    canonical = json.dumps(cached['rows'], ensure_ascii=False, separators=(',', ':')).encode()
    payload = json.dumps(protocol, sort_keys=True, separators=(',', ':')).encode()+b'\0'+main_bytes+b'\0'+control_bytes+b'\0'+canonical
    signature = json.loads((destination / 'outcome-attestation.json').read_text())
    calculated = hmac.new((private / 'outcome-attestation.key').read_bytes(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, signature['hmac_sha256']):
        raise ValueError('v5_outcome_attestation_failed')
    outcomes = json.loads(main_bytes)
    control_outcomes = json.loads(control_bytes)
    paired_control = compare_v5.legacy.paired_metrics(control_outcomes, outcomes, protocol['checkpoints'])
    expected_control = [dict(seconds=r['seconds'], budget=r['budget'], without_prince=r['v3'],
                             with_prince=r['v4'], gained_by_prince=r['gained'],
                             lost_to_prince=r['lost'], net=r['net']) for r in paired_control]
    if results['prince_ablation'] != expected_control:
        raise ValueError('report_prince_control_mismatch')
    stats = rename(analysis.calculate(cached['rows'], cached['labels'], cached['baseline'], outcomes,
                                     protocol['checkpoints'], protocol['rate']))
    if len(results['overall']) != 8:
        raise ValueError('report_cut_count_invalid')
    for point, actual, plan in zip(stats['checkpoints'], results['overall'], protocol['checkpoints']):
        if any(point[key] != actual[key] for key in ('v3', 'v5', 'gained', 'lost', 'net', 'seconds', 'budget')):
            raise ValueError('report_numeric_mismatch')
        if point['budget'] != plan['total_candidates']:
            raise ValueError('report_budget_mismatch')
    for dataset, values in stats['by_dataset'].items():
        if len(results['by_dataset'][dataset]) != 8:
            raise ValueError('report_dataset_cut_count_invalid')
        for a, b in zip(values, results['by_dataset'][dataset]):
            if any(a[key] != b[key] for key in ('v3', 'v5', 'gained', 'lost', 'net', 'total', 'seconds')):
                raise ValueError('report_dataset_mismatch')
    output = destination / 'report'
    output.mkdir(exist_ok=True)
    chart_dir = output / 'charts'
    chart_dir.mkdir(exist_ok=True)
    names = charts.charts(stats, chart_dir)
    f = charts.fmt
    last = stats['checkpoints'][-1]
    ablation = results['prince_ablation'][-1]
    first = ['| Отсечка | Попыток, млн | V3 | V5 | Новых | Потеряно | Δ |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for label, row in zip(charts.LABELS, stats['checkpoints']):
        first.append(f'| {label} | {f(row["budget"]/1e6,2)} | {row["v3"]} | {row["v5"]} | {row["gained"]} | {row["lost"]} | {row["net"]:+d} |')
    control = ['| Отсечка | Без PRINCE | С PRINCE | Новых | Потеряно | Δ |',
               '| --- | --- | --- | --- | --- | --- |']
    for label, row in zip(charts.LABELS, results['prince_ablation']):
        control.append(f'| {label} | {row["without_prince"]} | {row["with_prince"]} | {row["gained_by_prince"]} | {row["lost_to_prince"]} | {row["net"]:+d} |')
    decision = ('V5 увеличила итоговый охват на текущей выборке.' if last['net'] > 0 else
                'V5 не увеличила итоговый охват на текущей выборке.')
    parts = ['# V5: V3 с защищённым началом и поздним расширением\n\n'+decision,
             f'На 2 часах: V3 — {last["v3"]}, V5 — {last["v5"]} из {stats["total"]}. '
             f'Новых находок — {last["gained"]}, потерь — {last["lost"]}, чистая разница {last["net"]:+d}. '
             f'Относительное изменение числа находок: {f(last["relative_coverage_change_percent"])}%.',
             '## Что изменено\n\nПервые 141 000 000 попыток V5 — точный поток V3. '
             'Все 5 ранних отсечек до 10 минут включительно сохраняют кандидаты и ранги. '
             'Затем веса составляют 4/2/1/1: продолжение V3, компактные пары V4.1, маски 3/4 цифры, официальный native PRINCE. '
             'Новые источники не получают проверяемые ответы. Повторы между источниками расходуют попытки.',
             '## Одинаковые данные и бюджеты\n\nТот же снимок p01–p07: 852 уникальные пары, 814 SSID, только SSID-контекст и английский профиль. '
             'Все отсечки считаются при 235 000 проверок/с активной проверки. Это точная офлайн-оценка, а не GPU-прогон. '
             'V3 повторно пересчитана на полном диапазоне; исходные ранги подписаны HMAC вместе с методом, конфигурацией и входом. '
             'Новая V5 и контроль также имеют отдельную аттестацию результатов.',
             '## Все отсечки\n\n'+'\n'.join(first)+'\n\n![Охват](charts/coverage.png)\n\n![Приобретения и потери](charts/paired-gains-losses.png)',
             '## Стоимость\n\nВ расход включены попытки до совпадения и весь фактический бюджет неуспехов. '
             'Стоимость одной находки равна общему расходу по выборке, делённому на число находок. '
             f'На 2 часах отношение стоимости V5/V3 равно {f(last["cost_per_found_ratio_v5_v3"],3)}×. '
             'Значение ниже 1 означает меньшую стоимость результата. Время генерации не входит в эту модель.\n\n![Стоимость](charts/cost.png)',
             '## Контроль PRINCE\n\nКонтроль без PRINCE возвращает его долю продолжению V3: веса 5/2/1. '
             'Оба профиля объявлены до измерений и получили одинаковые бюджеты. '
             'Разница отражает политику выделения квоты PRINCE вместо V3, а не прямую атрибуцию каждой найденной строки.\n\n'+'\n'.join(control)+
             f'\n\nНа 2 часах без PRINCE найдено {ablation["without_prince"]}, с PRINCE — {ablation["with_prince"]}; чистая разница {ablation["net"]:+d}.',
             '## Где эффект устойчив\n\n![По файлам](charts/datasets.png)\n\n'
             f'Равновесная разница по файлам на 2 часах: {f(last["macro_file_delta_pp"])} п.п. '
             f'При исключении одного файла общая разница меняется от {f(last["leave_one_file_out_min_pp"])} до {f(last["leave_one_file_out_max_pp"])} п.п. '
             'Это проверка чувствительности без подстройки правил.',
             '## Ограничения общего вывода\n\n![Устойчивость](charts/stability.png)\n\n'
             f'Точечный 95% парный bootstrap-интервал разницы на 2 часах: [{f(last["net_pp_ci_low"])}; {f(last["net_pp_ci_high"])}] п.п. '
             'Использованы 5000 перевыборок целыми группами SSID, seed=20261116. '
             'Данные уже использовались при выборе подходов. Поэтому этот опыт не доказывает преимущество на новых сетях. '
             'Следующий подтверждающий опыт требует новой выборки и заранее зафиксированного метода.',
             '## Ревью и материалы\n\nНезависимые проходы алгоритма завершены до измерений. Итоговая независимая сверка чисел и графиков описана в FINAL-REVIEW.md. '
             'Пароли, отдельные SSID, исходные ранги и ключи не включаются в публичный архив.\n\n'
             '[Метрики](metrics.json) · [Все отсечки CSV](checkpoints.csv) · [Контроль PRINCE CSV](prince-control.csv)']
    for name, values in stats['by_dataset'].items():
        table = [f'## {name}: {values[0]["total"]} записей', '', '| Отсечка | V3 | V5 | Новых | Потеряно | Δ |', '| --- | --- | --- | --- | --- | --- |']
        table.extend(f'| {label} | {r["v3"]} | {r["v5"]} | {r["gained"]} | {r["lost"]} | {r["net"]:+d} |' for label, r in zip(charts.LABELS, values))
        parts.append('\n'.join(table))
    (output / 'RESULTS.md').write_text('\n\n'.join(parts)+'\n')
    (output / 'metrics.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    for filename, rows in [('checkpoints.csv', stats['checkpoints']), ('prince-control.csv', results['prince_ablation'])]:
        with (output / filename).open('w', newline='') as stream:
            writer=csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    def image(name):
        encoded=base64.b64encode((chart_dir/(name+'.png')).read_bytes()).decode()
        return f'<img alt="{name}" src="data:image/png;base64,{encoded}">'
    html_rows = ''.join('<tr>'+''.join(f'<td>{value}</td>' for value in
        (label,r['v3'],r['v5'],r['gained'],r['lost'],f'{r["net"]:+d}'))+'</tr>' for label,r in zip(charts.LABELS,stats['checkpoints']))
    control_rows=''.join('<tr>'+''.join(f'<td>{value}</td>' for value in
        (label,r['without_prince'],r['with_prince'],r['gained_by_prince'],r['lost_to_prince'],f'{r["net"]:+d}'))+'</tr>' for label,r in zip(charts.LABELS,results['prince_ablation']))
    page=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V5 — полный отчёт</title>
<style>body{{font:16px/1.6 system-ui;color:#0f172a;background:#f1f5f9;margin:0}}main{{max-width:1180px;margin:auto;padding:35px 24px}}h1{{font-size:40px;line-height:1.2}}h2{{margin-top:40px}}.card{{background:white;border:1px solid #e2e8f0;border-radius:15px;padding:24px;margin:20px 0}}img{{width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e2e8f0;padding:10px;text-align:right}}td:first-child,th:first-child{{text-align:left}}a{{color:#2563eb}}.scroll{{overflow:auto}}</style><main>
<h1>V5: сохранить начало V3<br>и расширить поздний поиск</h1><p>{decision}</p>
<div class="card"><b>Два часа:</b> V3 {last['v3']} → V5 {last['v5']}; новых {last['gained']}, потеряно {last['lost']}, разница {last['net']:+d}. Стоимость находки: {f(last['cost_per_found_ratio_v5_v3'],3)}× от V3.</div>
<p>Защищён точный поток V3 до 10 минут включительно. Далее: продолжение V3, компактные пары и маски V4, официальный PRINCE. 852 записи / 814 SSID. Одинаковые бюджеты при 235 000 проверок/с; это офлайн-модель активной проверки.</p>
<div class="card scroll"><table><tr><th>Отсечка</th><th>V3</th><th>V5</th><th>Новых</th><th>Потеряно</th><th>Δ</th></tr>{html_rows}</table></div>
<div class="card">{image('coverage')}</div><div class="card">{image('paired-gains-losses')}</div>
<h2>Цена результата</h2><p>Учтены неуспехи. Значение меньше 1 — меньше суммарных попыток на одну находку. Генерация и запуск GPU учитываются отдельно.</p><div class="card">{image('cost')}</div>
<h2>Что даёт квота PRINCE</h2><p>Контроль возвращает долю PRINCE продолжению V3. Измеряется политика распределения бюджета; это не прямая атрибуция всех новых ответов PRINCE.</p><div class="card scroll"><table><tr><th>Отсечка</th><th>Без PRINCE</th><th>С PRINCE</th><th>Новых</th><th>Потеряно</th><th>Δ</th></tr>{control_rows}</table></div>
<h2>Разные файлы и устойчивость</h2><div class="card">{image('datasets')}</div><div class="card">{image('stability')}</div>
<p>Данные использовались раньше. Bootstrap по SSID оценивает устойчивость этой выборки и не доказывает перенос на новые сети. На 2 часах интервал разницы [{f(last['net_pp_ci_low'])}; {f(last['net_pp_ci_high'])}] п.п. Польза страны/адреса этим снимком не проверена.</p>
<p><a href="RESULTS.md">Подробный отчёт</a> · <a href="metrics.json">Метрики</a> · <a href="checkpoints.csv">CSV</a> · <a href="prince-control.csv">PRINCE CSV</a></p></main></html>'''
    (output / 'report.html').write_text(page)
    provenance=dict(bootstrap=stats['bootstrap'], source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
                    shared_analysis_sha256=hashlib.sha256((ROOT.parent/'hybrid-v4/reporting/analyze.py').read_bytes()).hexdigest(),
                    input_attestation=protocol['input_attestation'])
    (output/'analysis-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    files=[output/n for n in ('report.html','RESULTS.md','metrics.json','checkpoints.csv','prince-control.csv','analysis-provenance.json')]
    files.extend(chart_dir/(name+ext) for name in names for ext in ('.png','.svg'))
    if (output/'FINAL-REVIEW.md').is_file():files.append(output/'FINAL-REVIEW.md')
    with zipfile.ZipFile(destination/'V5-report.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in files:archive.write(p,p.relative_to(output))
    print(json.dumps({'report':str(output),'last':last,'prince_last':ablation},ensure_ascii=False))


if __name__ == '__main__':
    build()
