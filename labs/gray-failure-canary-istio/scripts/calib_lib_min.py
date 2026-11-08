"""Intervalos de Clopper-Pearson unicaudais de 95%, do mesmo código usado na análise (code/triage/calib_lib.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "code", "triage"))
from calib_lib import clopper_pearson  # noqa: E402


def cp_lower(k, n):
    return clopper_pearson(k, n, two_sided=False)[0]


def cp_upper(k, n):
    return clopper_pearson(k, n, two_sided=False)[1]
