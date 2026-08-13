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
import sys

import pytest

gc.disable()


@pytest.fixture(autouse=True)
def _clear_firestore_read_cache():
    """Reset the module-level TTL read cache in memory.firestore_db.

    SelfStateStore/JournalStore reads are served from an in-process cache
    keyed by (store, project, database). Tests reuse the same project id with
    different mock data, so a value cached by one test must never leak into
    the next. Cleared on both sides of the test; tolerant of the module being
    re-imported (a fresh module object brings a fresh cache anyway).
    """
    mod = sys.modules.get("memory.firestore_db")
    if mod is not None and hasattr(mod, "_READ_CACHE"):
        mod._READ_CACHE.clear()
    yield
    mod = sys.modules.get("memory.firestore_db")
    if mod is not None and hasattr(mod, "_READ_CACHE"):
        mod._READ_CACHE.clear()


@pytest.fixture(autouse=True)
def _isolate_things_cloud(monkeypatch):
    """Keep the test suite off Amit's real Things account.

    ``TASK_BACKEND`` defaults to ``things``, so any test that exercises a task
    path without explicitly patching the store would otherwise build a real
    ``ThingsTaskStore`` and hit Things Cloud over the network — using whatever
    credentials happen to be in the developer's ``.env``. That actually happened:
    an autonomous-tick test asserting ``[]`` came back holding a live to-do
    pulled from the real account, and the suite behaved differently locally than
    in CI.

    Clearing the credentials makes an unpatched store raise ``ThingsAuthError``
    on the first call, before any socket is opened. Reads are documented never to
    raise, so they degrade to empty — exactly what those tests expect. Tests that
    genuinely want Things behaviour patch ``things_tool`` or set the env vars
    themselves, and both still work.

    The module-level mirror cache is cleared on both sides so state cannot leak
    between tests.
    """
    monkeypatch.delenv("THINGS_EMAIL", raising=False)
    monkeypatch.delenv("THINGS_PASSWORD", raising=False)
    monkeypatch.delenv("THINGS_WRITE_ENABLED", raising=False)

    def _reset():
        mod = sys.modules.get("memory.things_store")
        if mod is not None and hasattr(mod, "reset_cache"):
            mod.reset_cache()

    _reset()
    yield
    _reset()


@pytest.fixture
def isolated_modules():
    """Snapshot ``sys.modules``; on teardown drop keys the test added and restore
    keys it overwrote or deleted.

    Several test files stub heavy dependencies (``google.cloud.firestore``,
    ``googleapiclient``, ``telegram``, …) by writing into ``sys.modules`` and then
    importing the unit under test against those stubs. Done at module/collection
    time with no teardown, the first-collected file "wins" those slots for the
    whole session and later tests grab the leftover MagicMock — causing
    order-dependent failures and, with ``gc.disable()`` active, a cumulative
    MagicMock-cycle memory blow-up. Wrapping that stubbing in a fixture guarded by
    this one guarantees ``sys.modules`` is exactly as it was before the test.
    """
    snapshot = dict(sys.modules)
    try:
        yield
    finally:
        added = [k for k in sys.modules if k not in snapshot]
        for key in added:
            del sys.modules[key]
        for key, mod in snapshot.items():
            sys.modules[key] = mod
        # Re-align parent-package attributes with the restored submodules. A test
        # that does `sys.modules.pop("a.b"); importlib.import_module("a.b")` rebinds
        # the `b` attribute on package `a` to the new module object. Restoring
        # sys.modules alone leaves that attribute stale, so `import a.b as c` (reads
        # the parent attribute) and `from a.b import x` (reads sys.modules) diverge.
        # Restore snapshot submodules onto their parents, and drop attributes for
        # submodules that were added during the test.
        for key, mod in snapshot.items():
            parent, _, child = key.rpartition(".")
            if parent and parent in sys.modules and getattr(sys.modules[parent], child, None) is not mod:
                try:
                    setattr(sys.modules[parent], child, mod)
                except (AttributeError, TypeError):
                    pass
        for key in added:
            parent, _, child = key.rpartition(".")
            if parent and parent in sys.modules and hasattr(sys.modules[parent], child):
                try:
                    delattr(sys.modules[parent], child)
                except (AttributeError, TypeError):
                    pass
