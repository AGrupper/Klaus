"""Klaus's deterministic tools — the actions and reads Claude can invoke.

Import path unchanged from when this was a single module: `core.tools.dispatch`,
`core.tools.get_all_schemas` and `core.tools.set_current_user_id` are what the
MCP server and the life snapshot call, and they still resolve here.

Each domain module registers its own tools on import via the `@tool` decorator,
so importing this package is what builds the catalog. Adding a domain means
adding it to the import list below; adding a tool means adding one decorated
function to the module where it belongs.
"""
from __future__ import annotations

from core.tools.registry import (  # noqa: F401
    DuplicateToolError,
    dispatch,
    get_all_schemas,
    registered_tools,
    tool,
)
from core.tools.state import _get_current_user_id, set_current_user_id  # noqa: F401

# Importing each domain module runs its @tool decorators. Order determines the
# order of the published catalog and nothing else.
from core.tools import (  # noqa: F401,E402
    calendar,
    tasks,
    habits,
    memory,
    status,
    followups,
    directives,
    coaching,
    garmin,
    nutrition,
    training_log,
    strength,
    blocks,
)


# ---------------------------------------------------------------------------
# Compatibility surface
# ---------------------------------------------------------------------------
# The handlers and their helpers are re-exported here because `core.tools` was
# a single module for most of this project's life and a great deal of the test
# suite calls them by that path. Reading or calling through these names works.
#
# PATCHING through them does not: a re-export binds the object, so replacing
# `core.tools._get_calendar_tool` leaves the calendar module still calling its
# own. Patch the module that defines the name — `core.tools.calendar` — which is
# where it is resolved at call time.

from core.tools.calendar import (  # noqa: F401,E402
    _auth_manager,
    _calendar_tool,
    _get_auth_manager,
    _get_calendar_tool,
)
from core.tools.tasks import (  # noqa: F401,E402
    _get_task_store,
    _handle_task_complete,
    _handle_task_create,
    _handle_task_delete,
    _handle_task_edit,
    _handle_task_list,
    _handle_task_reschedule,
    _task_today_iso,
)
from core.tools.habits import (  # noqa: F401,E402
    _get_habit_store,
    _habit_today_iso,
    _handle_get_habit_adherence,
)
from core.tools.memory import (  # noqa: F401,E402
    _memory_store,
    _memory_tool,
    _get_memory_store,
    _get_memory_tool,
    _handle_forget_memory,
    _handle_recall,
    _handle_remember,
)
from core.tools.status import (  # noqa: F401,E402
    _get_hub_settings_store,
    _get_push_subscription_store,
    _handle_fetch_garmin_today,
    _handle_fetch_weather,
    _handle_get_push_health,
    _handle_get_self_status,
)
from core.tools.followups import (  # noqa: F401,E402
    _handle_cancel_followup,
    _handle_list_followups,
    _handle_schedule_followup,
)
from core.tools.directives import (  # noqa: F401,E402
    _handle_cancel_standing_directive,
    _handle_list_standing_directives,
    _handle_set_standing_directive,
)
from core.tools.coaching import (  # noqa: F401,E402
    _handle_get_training_profile,
    _handle_read_coaching_guide,
    _handle_read_user_profile,
    _handle_update_plan,
    _handle_update_training_profile,
)
from core.tools.garmin import (  # noqa: F401,E402
    _handle_fetch_recent_activities,
    _handle_fetch_training_status,
    _handle_get_acwr,
)
from core.tools.nutrition import (  # noqa: F401,E402
    _NUTRITION_MACRO_KEYS,
    _compute_nutrition_averages,
    _handle_fetch_nutrition_trend,
    _handle_fetch_recent_meals,
    _nutrition_targets_and_protein_ratio,
)
from core.tools.training_log import (  # noqa: F401,E402
    _handle_get_training_history,
    _handle_log_training,
)
from core.tools.strength import (  # noqa: F401,E402
    _handle_get_run_detail,
    _handle_get_strength_progress,
    _handle_get_training_context,
    _handle_get_training_reality,
)
from core.tools.blocks import (  # noqa: F401,E402
    _PLAN_START_DEFAULT,
    _block_stores,
    _handle_end_block,
    _handle_get_benchmark_history,
    _handle_get_block_status,
    _handle_get_goal_projection,
    _handle_get_plan,
    _handle_log_benchmark,
    _handle_start_block,
)


# TOOL_SCHEMAS and _HANDLERS were hand-maintained lists that had to be kept in
# step with the handlers by hand. They are now derived from the registry, so the
# drift they used to permit is not expressible: there is one source, and these
# are two views onto it.
TOOL_SCHEMAS: list[dict] = get_all_schemas()
# Callables here take the argument DICT, matching the lambdas this dict used to
# hold. Tests invoke _HANDLERS[name]({...}) directly, so the calling convention
# is part of the compatibility surface even though the storage changed.
_HANDLERS: dict = {
    name: (lambda handler: lambda args: handler(**args))(handler)
    for name, handler in registered_tools().items()
}
