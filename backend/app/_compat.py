"""Keep legacy imports bound to the exact canonical module (including patches)."""

from importlib import import_module
import sys


def redirect(legacy_name: str, canonical_name: str) -> None:
    sys.modules[legacy_name] = import_module(canonical_name)
