"""Locate the external tools the pipeline shells out to."""
import shutil


class MissingDependency(Exception):
    """A required external tool is not on PATH."""


HINT = 'Install with: brew install hcxtools hashcat'

# hcxtools renamed the extractor from hcxpcaptool to hcxpcapngtool in v6.
HCX_NAMES = ('hcxpcapngtool', 'hcxpcaptool')


def find_hcx():
    """Return the path to the hcx pcap extractor, preferring the current name."""
    for name in HCX_NAMES:
        path = shutil.which(name)
        if path:
            return path
    raise MissingDependency('hcxpcapngtool not found on PATH. ' + HINT)


def find_hashcat():
    """Return the path to the hashcat binary."""
    path = shutil.which('hashcat')
    if path:
        return path
    raise MissingDependency('hashcat not found on PATH. ' + HINT)
