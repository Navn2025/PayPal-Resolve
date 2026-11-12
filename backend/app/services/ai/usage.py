"""In-process cache and per-merchant daily token usage for promise extraction.

Held in memory only: everything resets when the API process restarts, and each
process counts separately. The daily budget is therefore a guard against
runaway use within one process, not an account-level spending limit.
"""

from collections import OrderedDict, deque
from datetime import UTC, datetime
from threading import Lock

CACHE_ENTRIES = 1000
CALLS_KEPT = 500


def today():
    return datetime.now(UTC).date().isoformat()


class ExtractionUsage:
    def __init__(self, clock=today):
        self._clock = clock
        self._lock = Lock()
        self._cache = OrderedDict()
        self._day = None
        self._merchants = {}

    def _usage(self, merchant_id):
        day = self._clock()
        if day != self._day:
            self._day, self._merchants = day, {}
        return self._merchants.setdefault(
            str(merchant_id),
            {
                "tokens": 0,
                "model_calls": 0,
                "cache_hits": 0,
                "skipped": {},
                "calls": deque(maxlen=CALLS_KEPT),
            },
        )

    def cached(self, merchant_id, key):
        """A stored result for this merchant's identical input, or None."""
        with self._lock:
            entry = self._cache.get((str(merchant_id), key))
            if entry is not None:
                self._cache.move_to_end((str(merchant_id), key))
            return entry

    def store(self, merchant_id, key, result):
        with self._lock:
            self._cache[(str(merchant_id), key)] = result
            self._cache.move_to_end((str(merchant_id), key))
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)

    def tokens_today(self, merchant_id):
        with self._lock:
            return self._usage(merchant_id)["tokens"]

    def record(
        self,
        merchant_id,
        *,
        case_id,
        tokens,
        cache_hit,
        skipped_reason,
        status,
        model_called,
    ):
        with self._lock:
            usage = self._usage(merchant_id)
            usage["tokens"] += tokens
            usage["model_calls"] += model_called
            usage["cache_hits"] += cache_hit
            if skipped_reason:
                usage["skipped"][skipped_reason] = (
                    usage["skipped"].get(skipped_reason, 0) + 1
                )
            usage["calls"].append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "case_id": str(case_id),
                    "tokens": tokens,
                    "cache_hit": cache_hit,
                    "skipped_reason": skipped_reason,
                    "status": status,
                }
            )

    def summary(self, merchant_id):
        with self._lock:
            usage = self._usage(merchant_id)
            return {
                "date": self._day,
                "tokens": usage["tokens"],
                "model_calls": usage["model_calls"],
                "cache_hits": usage["cache_hits"],
                "skipped": dict(usage["skipped"]),
                "calls": list(usage["calls"]),
            }
