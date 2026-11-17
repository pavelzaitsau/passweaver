from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit, unquote
import zipfile


def create(output, destination, files, review):
    output = Path(output).resolve()
    copied = output / 'review/REVIEW.md'
    copied.parent.mkdir(exist_ok=True)
    shutil.copyfile(review, copied)
    files = [Path(p).resolve() for p in files] + [copied]
    allowed = set(files)
    for path in files:
        if output not in path.parents:
            raise ValueError('archive_path_outside_report')
        if path.name == 'FINAL-REVIEW.md':
            path.write_text(path.read_text().replace('../../../review/REVIEW.md', 'review/REVIEW.md'))
        if path.suffix == '.md':
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = (path.parent / unquote(parsed.path)).resolve()
                if target not in allowed:
                    raise ValueError('archive_local_link_missing')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(output))
