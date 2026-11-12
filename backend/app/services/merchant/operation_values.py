"""Shared serialization and monetary formatting for merchant workflows."""

from decimal import Decimal
import json


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))
