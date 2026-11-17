import hybrid


def numeric_oracle(targets):
    widths = (8, 9, 10)
    hits = {}
    for answer, target in targets.items():
        if len(answer) in widths and answer.isascii() and answer.isdigit():
            hits[target] = sum(10 ** width for width in widths if width < len(answer)) + int(answer) + 1
    length = sum(10 ** width for width in widths)
    return dict(length=length, scanned=length, hits=hits, exact_analytic=True)


def mask_oracle(words, width, targets):
    if type(width) is not int or not 2 <= width <= 6:
        raise ValueError('invalid_mask_width')
    columns, owners, factors = 10 ** width, {}, []
    for wi, word in enumerate(words[:30000]):
        forms = [form for form in hybrid.forms(word)[:3] if hybrid.audit.valid(form + '0' * width)]
        for fi, form in enumerate(forms):
            if any(c in '0123456789' for c in form) or form in owners:
                return None
            owners[form] = (wi, fi)
        factors.append(2 * len(forms))
    hits = {}
    for answer, target in targets.items():
        if not hybrid.audit.valid(answer) or len(answer) <= width:
            continue
        possibilities = []
        tail, head = answer[-width:], answer[:width]
        if tail.isascii() and tail.isdigit() and answer[:-width] in owners:
            possibilities.append((answer[:-width], int(tail), 0))
        if head.isascii() and head.isdigit() and answer[width:] in owners:
            possibilities.append((answer[width:], int(head), 1))
        for form, number, direction in possibilities:
            wi, fi = owners[form]
            score = (wi + 1) * (number + 1)
            before = 0
            for j, factor in enumerate(factors):
                if factor:
                    lesser = min(columns, (score - 1) // (j + 1))
                    tied = j < wi and score % (j + 1) == 0 and score // (j + 1) <= columns
                    before += factor * (lesser + int(tied))
            rank = before + 2 * fi + direction + 1
            hits[target] = min(hits.get(target, rank), rank)
    length = columns * sum(factors)
    return dict(length=length, scanned=length, hits=hits, exact_analytic=True)
