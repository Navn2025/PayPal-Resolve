# Time to verified resolution (SYNTHETIC data)

All cases, amounts and delays are generated from a fixed seed; PayPal refunds are simulated.
These numbers describe the generator, not real merchants.

Seed 7, 40 cases. Definition: first promise_recorded event -> first PayPal-verified COMPLETED refunds covering the promise.

| Scenario | Cases | Resolved | Median (h) | p90 (h) |
|---|---|---|---|---|
| all | 40 | 24 | 86.49 | 124.47 |
| one_refund | 8 | 8 | 93.87 | 115.52 |
| two_refunds | 8 | 8 | 80.99 | 174.15 |
| partial_only | 8 | 0 | None | None |
| no_refund | 8 | 0 | None | None |
| pending_then_completed | 8 | 8 | 98.1 | 124.47 |
