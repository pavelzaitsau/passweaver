from collections import Counter

import numpy as np


def calculate(rows, labels, left, right, plans, rate, repetitions=5000, seed=20261116):
    n, cuts = len(rows), len(plans)
    if n == 0 or not (n == len(labels) == len(left) == len(right)):
        raise ValueError('analysis_record_count_mismatch')
    flags = np.zeros((2, n, cuts), dtype=bool)
    work = np.zeros((2, n, cuts), dtype=np.int64)
    for model, outcomes in enumerate((left, right)):
        for i, outcome in enumerate(outcomes):
            for phase, p in enumerate(plans):
                hit = outcome['hit']
                found = hit is not None and hit[0] <= phase and hit[1] <= p['total_candidates']
                flags[model, i, phase] = found
                work[model, i, phase] = hit[1] if found else min(outcome['emitted'][phase], p['total_candidates'])
    delta = flags[1].astype(np.int64) - flags[0].astype(np.int64)
    groups, group_ids = {}, []
    for row in rows:
        if row['ssid'] not in groups:
            groups[row['ssid']] = len(groups)
        group_ids.append(groups[row['ssid']])
    sizes = np.bincount(group_ids)
    grouped = np.zeros((len(groups), cuts), dtype=np.int64)
    np.add.at(grouped, group_ids, delta)
    rng = np.random.default_rng(seed)
    draws = np.empty((repetitions, cuts))
    for start in range(0, repetitions, 100):
        stop = min(start + 100, repetitions)
        indexes = rng.integers(0, len(groups), size=(stop - start, len(groups)))
        draws[start:stop] = 100 * grouped[indexes].sum(axis=1) / sizes[indexes].sum(axis=1)[:, None]
    intervals = np.quantile(draws, [0.025, 0.975], axis=0)
    datasets = sorted(set(labels))
    dataset_results = {name: [] for name in datasets}
    checkpoints = []
    for phase, p in enumerate(plans):
        a, b = flags[:, :, phase]
        v3, v4 = int(a.sum()), int(b.sum())
        total3, total4 = [int(value) for value in work[:, :, phase].sum(axis=1)]
        cp3 = total3 / v3 if v3 else None
        cp4 = total4 / v4 if v4 else None
        macro, exclusions = [], []
        for name in datasets:
            mask = np.asarray([label == name for label in labels])
            count = int(mask.sum())
            net = int(delta[mask, phase].sum())
            dataset_results[name].append(dict(seconds=p['seconds'], total=count,
                v3=int(a[mask].sum()), v4=int(b[mask].sum()), net=net,
                net_pp=100 * net / count,
                gained=int((~a[mask] & b[mask]).sum()), lost=int((a[mask] & ~b[mask]).sum())))
            macro.append(100 * net / count)
            if count < n:
                exclusions.append(100 * int(delta[~mask, phase].sum()) / (n - count))
        checkpoints.append(dict(seconds=p['seconds'], budget=p['total_candidates'], total=n,
            v3=v3, v4=v4, v3_percent=100 * v3 / n, v4_percent=100 * v4 / n,
            common=int((a & b).sum()), gained=int((~a & b).sum()), lost=int((a & ~b).sum()),
            net=v4 - v3, net_pp=100 * (v4 - v3) / n,
            relative_coverage_change_percent=100 * (v4 / v3 - 1) if v3 else None,
            net_pp_ci_low=float(intervals[0, phase]), net_pp_ci_high=float(intervals[1, phase]),
            macro_file_delta_pp=float(np.mean(macro)),
            leave_one_file_out_min_pp=min(exclusions) if exclusions else None,
            leave_one_file_out_max_pp=max(exclusions) if exclusions else None,
            sum_checks_v3=total3, sum_checks_v4=total4,
            mean_active_seconds_v3=total3 / (n * float(rate)),
            mean_active_seconds_v4=total4 / (n * float(rate)),
            active_seconds_per_found_v3=cp3 / float(rate) if cp3 is not None else None,
            active_seconds_per_found_v4=cp4 / float(rate) if cp4 is not None else None,
            cost_per_found_ratio_v4_v3=cp4 / cp3 if cp3 and cp4 is not None else None))
    common = flags[0, :, -1] & flags[1, :, -1]
    rank3 = np.asarray([left[i]['hit'][1] for i in range(n) if common[i]], dtype=np.int64)
    rank4 = np.asarray([right[i]['hit'][1] for i in range(n) if common[i]], dtype=np.int64)
    ratios = rank4 / rank3 if len(rank3) else np.asarray([])
    return dict(total=n, unique_ssids=len(groups), rate=str(rate), checkpoints=checkpoints,
                by_dataset=dataset_results,
                common_final=dict(total=int(common.sum()), earlier_v4=int((rank4 < rank3).sum()),
                                  equal=int((rank4 == rank3).sum()), later_v4=int((rank4 > rank3).sum()),
                                  median_attempt_ratio_v4_v3=float(np.median(ratios)) if len(ratios) else None),
                bootstrap=dict(method='paired percentile cluster bootstrap by exact SSID',
                               repetitions=repetitions, seed=seed, clusters=len(groups),
                               interval='pointwise 95%; conditional sample stability, not population generalization'))
