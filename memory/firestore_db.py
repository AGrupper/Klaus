"""Firestore-backed state storage — see `docs/ARCHITECTURE.md` for the data layer.

Every persistent Klaus record lives here, in one store class per domain
(profile, meals, training, tasks, habits, follow-ups, directives, approvals,
push subscriptions, portfolio, routine runs and reviews). Each store owns a
single top-level collection, builds its client through `_make_firestore_client`,
and returns JSON-safe documents via `_jsonsafe_doc` so Firestore timestamps and
Decimals never reach a caller that is about to serialise them.

Klaus is single-user, so collections are flat and unprefixed; `KLAUS_USER_ID`
namespaces the vector store, not this one.

**This module is now a facade.** The implementations live in `memory/stores/`,
one module per domain, and are re-exported here unchanged. That is deliberate
rather than transitional: consumers import lazily inside functions
(`from memory.firestore_db import MealStore`) and the test suite monkeypatches by
string (`"memory.firestore_db.MealStore"`) in ~51 places, so this path stays the
one address for the data layer. `_READ_CACHE` is re-exported as the same object,
which is what lets conftest clear it in place.

New code may import from `memory.stores.<domain>` directly.
"""
from __future__ import annotations

import logging
import os

from decimal import Decimal  # noqa: F401 — re-exported; part of this module's historical surface
from zoneinfo import ZoneInfo as _ZoneInfo  # noqa: F401 — re-exported, see below

from dotenv import load_dotenv
from google.cloud import firestore  # noqa: F401 — re-exported; tests reach for
# memory.firestore_db.firestore to assert on SERVER_TIMESTAMP and to monkeypatch
# `transactional`, so this name has to keep resolving to the same module object.
from google.api_core.exceptions import GoogleAPICallError

logger = logging.getLogger(__name__)

from memory.stores.base import (  # noqa: F401
    _DESCENDING,
    _READ_CACHE,
    _READ_CACHE_TTL_SEC,
    _cache_get,
    _cache_invalidate_prefix,
    _cache_put,
    _jsonsafe_doc,
    _jsonsafe_value,
    _make_firestore_client,
    _where,
    record_cron_run,
)

from memory.stores.profile import (  # noqa: F401
    HubSettingsStore,
    JournalStore,
    SelfStateStore,
    UserProfileStore,
)

from memory.stores.nutrition import (  # noqa: F401
    MealStore,
    _is_newer,
)

from memory.stores.training import (  # noqa: F401
    BenchmarkStore,
    BlockStore,
    TrainingLogStore,
    _BENCHMARK_FACETS,
    get_week_num,
)

from memory.stores.strength import (  # noqa: F401
    StrengthSessionStore,
)

from memory.stores.runs import (  # noqa: F401
    RunDetailStore,
)

from memory.stores.tasks import (  # noqa: F401
    TaskListStore,
    TaskStore,
    _TZ,
    _advance_once,
    _next_due_date,
    get_task_store,
    is_auto_schedule_candidate,
)

from memory.stores.habits import (  # noqa: F401
    HabitStore,
    RoutineStore,
    _is_scheduled,
    compute_routine_streak,
    compute_streak_and_grid,
)

from memory.stores.followups import (  # noqa: F401
    FollowupStore,
    StandingDirectiveStore,
)

from memory.stores.logs import (  # noqa: F401
    ActionLogStore,
    BehavioralFeedbackStore,
    OutreachLogStore,
)

from memory.stores.approvals import (  # noqa: F401
    ActionIdempotencyStore,
    PendingApprovalStore,
)

from memory.stores.push import (  # noqa: F401
    PushSubscriptionStore,
)

from memory.stores.portfolio import (  # noqa: F401
    PortfolioHoldingStore,
    PortfolioSnapshotStore,
)

from memory.stores.routines import (  # noqa: F401
    RoutineReviewStore,
    RoutineRunStore,
)

from memory.stores.embeddings import (  # noqa: F401
    EmbeddingUsageStore,
)


def _smoke_test() -> int:
    """Verify Firestore connectivity. Returns 0 on success, 1 on failure.

    Run with:  python -m memory.firestore_db
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv(override=True)

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        logger.error("GCP_PROJECT_ID is not set — check your .env file")
        return 1

    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    print(f"Connecting to Firestore project={project_id!r} database={database!r} …")
    try:
        client = _make_firestore_client(project_id, database)
        # Lightweight connectivity check — list collections (returns immediately).
        _ = list(client.collections())
        print("Firestore connection OK.")
    except GoogleAPICallError as exc:
        logger.error("Smoke test failed: %s", exc)
        return 1

    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
