"""New calculators: one file per kind, auto-discovered in sorted order.

Each file calls ``calckit.register(...)`` at import time. Import the kit relatively,
``from .. import calckit`` (never ``circuit_bench...``: the backend routes load bench_core under another package
name). ``calckit._ensure`` imports every module here whose name does not start with ``_``; a module that fails to
import is skipped and listed in ``calckit.problems()`` (a test keeps that list empty).

Minimal file ``calcs/ntc.py``::

    from .. import calckit

    @calckit.action("calc.ntc")
    def ntc(r25: object, beta: object, *, v_ref: object = 3.3) -> dict:
        r, b, v = calckit.num(r25, "Ω", "r25"), calckit.count(beta, "beta"), calckit.num(v_ref, "V", "v_ref")
        ...
        return calckit.envelope("calc.ntc", "…", {...}, sources=calckit.sources.resolve([...]))

    calckit.register("ntc", ntc, (("r25", "Ω", True, None), ("beta", "", True, None), ("v_ref", "V", False, 3.3)),
                     title="NTC thermistor divider", group="sensing", summary="…")
"""
