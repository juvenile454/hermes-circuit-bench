"""Hermes-independent core of Circuit Bench.

Rules for every module in this package:
- only relative imports inside bench_core (never ``from ..``): dashboard/plugin_api.py loads bench_core on its own;
- no third-party imports at module level (schemdraw, serial are imported inside functions);
- public action functions return the result envelope of contracts.py, helpers raise BenchError.
"""
