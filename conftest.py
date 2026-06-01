"""Pytest session configuration.

Disable CPython's automatic cyclic garbage collector for the whole test session.

Running the full suite in a single process otherwise segfaults inside the cyclic
collector (`gc_collect_main -> deduce_unreachable -> dict_traverse`, fault addr
0xa9) when the grpcio (`cygrpc`) + protobuf (`_message.abi3.so`) C extensions —
pulled in transitively by google-cloud-firestore — are loaded. The crash is a
native-wheel/GC binary-compat issue, not a Klaus code bug, and it reproduces on
both Python 3.13 and 3.14. Disabling the automatic collector keeps the cyclic
collector from traversing that object graph mid-run; reference counting still
reclaims the vast majority of objects, and any genuine cycles are released at
interpreter exit. Memory growth across a ~670-test suite is negligible.

We intentionally do NOT re-enable GC at session end — the crash also fires at
interpreter shutdown, so the collector stays off through teardown.
"""
import gc

gc.disable()
