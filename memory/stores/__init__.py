"""Firestore repositories, one module per domain.

Import from `memory.firestore_db`, which re-exports every name here —
that facade is what keeps the existing call sites and test patch targets
working. Import from a store module directly only in new code that has no
reason to care about the old path.
"""
