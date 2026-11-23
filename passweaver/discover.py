"""Resolve the capture files named on the command line."""
import glob
import os
from pathlib import Path

# hcxpcapngtool reads all three container formats.
CAPTURE_SUFFIXES = ('.pcap', '.pcapng', '.cap')


def _is_capture(path):
    return path.suffix.lower() in CAPTURE_SUFFIXES


def resolve(patterns):
    """Expand files, directories and globs into a sorted list of capture paths.

    Accepts, in any mix:
      - a directory, walked recursively for capture files
      - a glob string such as '/caps/*.pcap' (quoted, so the shell left it intact)
      - an explicit file path, which is taken even without a capture suffix

    Returns (paths, missing) where paths is a de-duplicated sorted list and
    missing lists patterns that matched nothing.
    """
    found = {}
    missing = []
    for pattern in patterns:
        entry = Path(pattern)
        if entry.is_dir():
            matches = [p for p in sorted(entry.rglob('*')) if p.is_file() and _is_capture(p)]
        elif entry.is_file():
            matches = [entry]
        else:
            matches = [Path(m) for m in sorted(glob.glob(pattern, recursive=True))
                       if Path(m).is_file() and _is_capture(Path(m))]
        if not matches:
            missing.append(pattern)
            continue
        for match in matches:
            found[match.resolve()] = match
    return sorted(found.values(), key=lambda p: str(p)), missing
