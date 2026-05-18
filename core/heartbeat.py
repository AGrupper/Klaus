"""Klaus self-monitoring heartbeat.

Runs one health-check tick: inspects Klaus's own crons, integration tokens,
runtime degradation, and deployment state, then sends tiered Telegram alerts.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/heartbeat  (hourly, 0 * * * *, Asia/Jerusalem)

Local smoke test:
  python -m core.heartbeat --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# Lazy import so tests can monkeypatch before the actual call
try:
    from core.scheduled_message import send_and_inject
except ImportError:
    send_and_inject = None  # type: ignore[assignment]

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_FYI = "fyi"


@dataclass
class Signal:
    """A single detected health problem.

    fingerprint: stable dedup key, e.g. "cron:morning-briefing:stale".
    severity:    SEVERITY_CRITICAL | SEVERITY_WARNING | SEVERITY_FYI.
    area:        "cron" | "token" | "degradation" | "deployment" | "code".
    title:       one-line human summary.
    detail:      specific evidence (numbers, timestamps).
    remediation: static fix hint.
    """
    fingerprint: str
    severity: str
    area: str
    title: str
    detail: str
    remediation: str


def _parse_hm(hm_str: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    try:
        h, m = hm_str.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        logger.warning("heartbeat: could not parse time %r", hm_str)
        return 0


def _in_quiet_hours(config: dict, now: datetime) -> bool:
    """Return True if `now` falls within the configured quiet window."""
    tz_name = config.get("timezone", "Asia/Jerusalem")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("heartbeat: unknown timezone %r — defaulting to UTC", tz_name)
        tz = ZoneInfo("UTC")

    local_now = now.astimezone(tz)
    now_hm = local_now.hour * 60 + local_now.minute

    quiet_start = _parse_hm(config.get("quiet_start", "22:00"))
    quiet_end = _parse_hm(config.get("quiet_end", "07:00"))

    if quiet_start <= quiet_end:
        return quiet_start <= now_hm < quiet_end
    else:
        return now_hm >= quiet_start or now_hm < quiet_end


def _tiers_for_now(config: dict, now: datetime) -> set[str]:
    """Return the severity tiers to check this tick.

    Critical always; Warning at the configured digest_hour; FYI additionally
    on the configured weekly_digest_day at digest_hour.
    """
    tz_name = config.get("timezone", "Asia/Jerusalem")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = now.astimezone(tz)
    tiers = {SEVERITY_CRITICAL}
    if local_now.hour == int(config.get("digest_hour", 9)):
        tiers.add(SEVERITY_WARNING)
        if local_now.isoweekday() == int(config.get("weekly_digest_day", 1)):
            tiers.add(SEVERITY_FYI)
    return tiers


_CRON_MAX_STALENESS_HOURS = {
    "morning-briefing": 26,
    "proactive-alerts": 26,
    "ingest-chats": 26,
    "ingest-chat-exports": 26,
}
_CRON_FAILURE_STREAK_THRESHOLD = 3


def _read_cron_ledger() -> dict:
    """Return {job_id: doc_dict} from the Firestore heartbeat_runs collection."""
    from memory.firestore_db import _make_firestore_client
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    client = _make_firestore_client(project_id, database)
    out: dict = {}
    for snap in client.collection("heartbeat_runs").stream():
        out[snap.id] = snap.to_dict() or {}
    return out


def check_cron_health() -> list[Signal]:
    """Critical-tier: each cron ran recently and is not in a failure streak."""
    signals: list[Signal] = []
    try:
        ledger = _read_cron_ledger()
    except Exception:
        logger.warning("heartbeat: cron ledger read failed", exc_info=True)
        return signals

    now = datetime.now(timezone.utc)
    for job_id, max_hours in _CRON_MAX_STALENESS_HOURS.items():
        doc = ledger.get(job_id)
        if doc is None:
            signals.append(Signal(
                fingerprint=f"cron:{job_id}:missing",
                severity=SEVERITY_CRITICAL, area="cron",
                title=f"{job_id} has never recorded a run",
                detail="No heartbeat_runs ledger entry exists.",
                remediation=f"Confirm the Cloud Scheduler job for {job_id} exists and is enabled.",
            ))
            continue
        last = doc.get("last_run_at")
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_h = (now - last).total_seconds() / 3600
            if age_h > max_hours:
                signals.append(Signal(
                    fingerprint=f"cron:{job_id}:stale",
                    severity=SEVERITY_CRITICAL, area="cron",
                    title=f"{job_id} has not run in {age_h:.0f}h",
                    detail=f"Last run {last.isoformat()}; expected within {max_hours}h.",
                    remediation=f"Check the Cloud Scheduler job for {job_id} and Cloud Run logs.",
                ))

    for job_id, doc in ledger.items():
        if doc.get("consecutive_failures", 0) >= _CRON_FAILURE_STREAK_THRESHOLD:
            signals.append(Signal(
                fingerprint=f"cron:{job_id}:failing",
                severity=SEVERITY_CRITICAL, area="cron",
                title=f"{job_id} failed {doc['consecutive_failures']}x in a row",
                detail=f"last_ok={doc.get('last_ok')}.",
                remediation=f"Inspect Cloud Run logs for the {job_id} endpoint.",
            ))
    return signals


def check_tokens() -> list[Signal]:
    """Token/integration health: Google OAuth and TickTick OAuth refresh probes."""
    signals: list[Signal] = []

    try:
        from core.auth_google import build_auth_manager_from_env
        build_auth_manager_from_env().get_credentials()
    except Exception as exc:
        signals.append(Signal(
            fingerprint="token:google:refresh-failed",
            severity=SEVERITY_CRITICAL, area="token",
            title="Google OAuth refresh failed",
            detail=str(exc)[:200],
            remediation="Re-run the Google OAuth bootstrap; refresh klaus-google-oauth-token.",
        ))

    try:
        from mcp_tools.ticktick_auth import get_valid_access_token
        get_valid_access_token()
    except Exception as exc:
        signals.append(Signal(
            fingerprint="token:ticktick:refresh-failed",
            severity=SEVERITY_CRITICAL, area="token",
            title="TickTick OAuth refresh failed",
            detail=str(exc)[:200],
            remediation="Run scripts/ticktick_oauth_bootstrap.py to re-issue the token pair.",
        ))

    return signals


_FALLBACK_WARN_THRESHOLD = 10
_CLOUD_RUN_5XX_WARN_THRESHOLD = 5


def _read_fallback_count_today() -> int:
    """Read today's Gemini->Haiku fallback count from Firestore heartbeat_metrics."""
    from memory.firestore_db import _make_firestore_client
    from datetime import date
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    client = _make_firestore_client(project_id, database)
    today = date.today().isoformat()
    snap = client.collection("heartbeat_metrics").document(today).get()
    if not snap.exists:
        return 0
    return (snap.to_dict() or {}).get("fallback_count", 0)


def _read_cloud_run_5xx() -> int:
    """Query Cloud Monitoring for Cloud Run 5xx count in the last hour."""
    from google.cloud import monitoring_v3
    from google.protobuf.timestamp_pb2 import Timestamp
    import time

    project_id = os.environ["GCP_PROJECT_ID"]
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"

    now_sec = int(time.time())
    interval = monitoring_v3.TimeInterval(
        start_time=Timestamp(seconds=now_sec - 3600),
        end_time=Timestamp(seconds=now_sec),
    )
    aggregation = monitoring_v3.Aggregation(
        alignment_period={"seconds": 3600},
        per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
    )
    results = client.list_time_series(
        request={
            "name": project_name,
            "filter": (
                'metric.type="run.googleapis.com/request_count" '
                'AND resource.labels.service_name="klaus-agent" '
                'AND metric.labels.response_code_class="5xx"'
            ),
            "interval": interval,
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            "aggregation": aggregation,
        }
    )
    total = 0
    for series in results:
        for point in series.points:
            total += int(point.value.int64_value)
    return total


def check_degradation() -> list[Signal]:
    """Warning-tier: fallback-rate climbing, Cloud Run 5xx spikes."""
    signals: list[Signal] = []
    try:
        fallbacks = _read_fallback_count_today()
        if fallbacks >= _FALLBACK_WARN_THRESHOLD:
            signals.append(Signal(
                fingerprint="degradation:fallback-rate",
                severity=SEVERITY_WARNING, area="degradation",
                title=f"Gemini->Haiku fallback fired {fallbacks}x today",
                detail="Primary Smart Agent (Gemini 3) is erroring or rate-limited.",
                remediation="Check Gemini quota / API key; review Cloud Run logs for LLMError.",
            ))
    except Exception:
        logger.warning("heartbeat: fallback metric read failed", exc_info=True)
    try:
        errs = _read_cloud_run_5xx()
        if errs >= _CLOUD_RUN_5XX_WARN_THRESHOLD:
            signals.append(Signal(
                fingerprint="degradation:cloud-run-5xx",
                severity=SEVERITY_WARNING, area="degradation",
                title=f"{errs} Cloud Run 5xx responses in the last hour",
                detail="klaus-agent is returning server errors.",
                remediation="Inspect Cloud Run logs for unhandled exceptions / OOM.",
            ))
    except Exception:
        logger.warning("heartbeat: Cloud Monitoring read failed", exc_info=True)
    return signals


def _latest_deploy_status() -> dict | None:
    """Return the latest GitHub Actions deploy.yml run status, or None on error."""
    import requests as _requests
    repo = os.getenv("KLAUS_GITHUB_REPO", "")
    token = os.getenv("KLAUS_GITHUB_TOKEN", "")
    if not repo or not token:
        logger.debug("heartbeat: KLAUS_GITHUB_REPO or KLAUS_GITHUB_TOKEN not set — skipping deploy check")
        return None
    url = f"https://api.github.com/repos/{repo}/actions/workflows/deploy.yml/runs?per_page=1"
    try:
        resp = _requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        resp.raise_for_status()
        runs = resp.json().get("workflow_runs", [])
        if not runs:
            return None
        run = runs[0]
        return {
            "conclusion": run.get("conclusion"),
            "status": run.get("status"),
            "head_sha": run.get("head_sha", ""),
        }
    except Exception:
        logger.warning("heartbeat: GitHub deploy status fetch failed", exc_info=True)
        return None


def _live_revision_sha() -> str | None:
    """Return the commit SHA of the currently-serving Cloud Run revision, or None on error."""
    try:
        from google.cloud import run_v2
        project_id = os.environ["GCP_PROJECT_ID"]
        client = run_v2.ServicesClient()
        service_name = f"projects/{project_id}/locations/me-west1/services/klaus-agent"
        service = client.get_service(name=service_name)
        traffic = service.traffic
        if not traffic:
            return None
        serving_revision = traffic[0].revision
        if not serving_revision:
            return None
        rev_client = run_v2.RevisionsClient()
        revision = rev_client.get_revision(name=serving_revision)
        image = revision.containers[0].image if revision.containers else ""
        # Image tag format: region-docker.pkg.dev/project/repo/agent:{sha}
        if ":" in image:
            return image.rsplit(":", 1)[-1]
        return None
    except Exception:
        logger.warning("heartbeat: Cloud Run revision check failed", exc_info=True)
        return None


def check_deployment() -> list[Signal]:
    """Deployment health: last deploy succeeded; live revision matches main."""
    signals: list[Signal] = []
    try:
        deploy = _latest_deploy_status()
        if deploy and deploy.get("conclusion") == "failure":
            signals.append(Signal(
                fingerprint="deployment:last-deploy-failed",
                severity=SEVERITY_CRITICAL, area="deployment",
                title="Last GitHub Actions deploy failed",
                detail=f"Workflow run for {deploy.get('head_sha', '?')[:8]} concluded 'failure'.",
                remediation="Open the Actions tab for the deploy.yml run and fix the failure.",
            ))
        live = _live_revision_sha()
        head = (deploy or {}).get("head_sha")
        if live and head and not head.startswith(live) and not live.startswith(head):
            signals.append(Signal(
                fingerprint="deployment:revision-behind",
                severity=SEVERITY_WARNING, area="deployment",
                title="Live Cloud Run revision is behind main",
                detail=f"Live={live[:8]}, latest main={head[:8]}.",
                remediation="Re-run the deploy workflow or push to main to trigger a deploy.",
            ))
    except Exception:
        logger.warning("heartbeat: deployment check failed", exc_info=True)
    return signals


def check_code(repo_root: Path | None = None) -> list[Signal]:
    """Weekly FYI: docs drift, stale TODOs, repeated-fix clusters."""
    import subprocess
    import re

    signals: list[Signal] = []
    root = repo_root or Path(__file__).parent.parent

    # --- Docs drift: paths mentioned in CLAUDE.md text block vs disk ---
    try:
        claude_md = root / "CLAUDE.md"
        if claude_md.exists():
            content = claude_md.read_text(encoding="utf-8")
            # Extract lines inside fenced ```text blocks
            in_block = False
            missing_paths: list[str] = []
            for line in content.splitlines():
                if line.strip().startswith("```text"):
                    in_block = True
                    continue
                if in_block and line.strip().startswith("```"):
                    in_block = False
                    continue
                if in_block:
                    # Strip tree-drawing chars and extract a path-like token
                    cleaned = re.sub(r"[│├└─ \t]+", "", line).strip()
                    # Skip the root line (e.g. "Klaus/")
                    if not cleaned or "/" not in cleaned and not cleaned.endswith(".py"):
                        # Try as plain filename
                        if cleaned and "." in cleaned:
                            candidate = root / cleaned
                            if not candidate.exists():
                                missing_paths.append(cleaned)
                    else:
                        # Remove trailing comments
                        path_part = cleaned.split("#")[0].strip()
                        if path_part:
                            candidate = root / path_part
                            if not candidate.exists():
                                missing_paths.append(path_part)
            if missing_paths:
                signals.append(Signal(
                    fingerprint="code:docs-drift",
                    severity=SEVERITY_FYI, area="code",
                    title="CLAUDE.md references paths that don't exist",
                    detail=f"{len(missing_paths)} missing: {', '.join(missing_paths[:3])}{'…' if len(missing_paths) > 3 else ''}",
                    remediation="Update the directory tree in CLAUDE.md to match the current codebase.",
                ))
    except Exception:
        logger.warning("heartbeat: docs-drift check failed", exc_info=True)

    # --- Stale TODOs: grep core/mcp_tools/interfaces/memory ---
    try:
        result = subprocess.run(
            ["grep", "-rn", "TODO\\|FIXME",
             str(root / "core"), str(root / "mcp_tools"),
             str(root / "interfaces"), str(root / "memory")],
            capture_output=True, text=True, timeout=15,
        )
        count = len([l for l in result.stdout.splitlines() if l.strip()])
        if count > 15:
            examples = result.stdout.splitlines()[:3]
            signals.append(Signal(
                fingerprint="code:stale-todos",
                severity=SEVERITY_FYI, area="code",
                title=f"{count} TODO/FIXME comments in source",
                detail="; ".join(e.split(":", 2)[-1].strip() for e in examples),
                remediation="Review and resolve or file tickets for stale TODOs.",
            ))
    except Exception:
        logger.warning("heartbeat: stale-todo check failed", exc_info=True)

    # --- Repeated-fix clusters: git log ---
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "--since=60 days ago", "--pretty=%s"],
            capture_output=True, text=True, timeout=15,
        )
        scope_counts: dict[str, int] = {}
        for line in result.stdout.splitlines():
            m = re.match(r"fix\(([^)]+)\)", line.strip())
            if m:
                scope = m.group(1)
                scope_counts[scope] = scope_counts.get(scope, 0) + 1
        for scope, count in scope_counts.items():
            if count >= 4:
                signals.append(Signal(
                    fingerprint=f"code:fix-cluster:{scope}",
                    severity=SEVERITY_FYI, area="code",
                    title=f"fix({scope}) appears {count}x in last 60 days",
                    detail=f"Scope '{scope}' is a churn hotspot.",
                    remediation=f"Investigate root cause of repeated fixes in '{scope}'.",
                ))
    except Exception:
        logger.warning("heartbeat: fix-cluster check failed", exc_info=True)

    # --- SELF.md SHA staleness: embedded hash vs fresh tool-schema hash ---
    try:
        import hashlib as _hashlib
        import re as _re_sha

        self_md = root / "docs" / "SELF.md"
        if self_md.exists():
            content = self_md.read_text(encoding="utf-8")

            # Extract the embedded SHA from the <!-- sha: <hex> --> comment line.
            sha_match = _re_sha.search(r"<!--\s*sha:\s*([0-9a-f]{40})\s*-->", content)
            stored_sha = sha_match.group(1) if sha_match else None

            # Recompute SHA using the same algorithm as core/self_manifest._compute_schema_hash.
            # Must stay in sync with self_manifest.py — if one changes, update the other.
            fragments: list[str] = []
            tools_file = root / "core" / "tools.py"
            if tools_file.exists():
                tools_text = tools_file.read_text(encoding="utf-8")
                names = sorted(_re_sha.findall(r'"name":\s*"([^"]+)"', tools_text))
                fragments.extend(names)
            web_file = root / "interfaces" / "web_server.py"
            if web_file.exists():
                web_text = web_file.read_text(encoding="utf-8")
                routes = sorted(_re_sha.findall(r'"/cron/[^"]*"', web_text))
                fragments.extend(routes)
            fresh_sha = _hashlib.sha1("\n".join(fragments).encode()).hexdigest()

            if stored_sha and stored_sha != fresh_sha:
                signals.append(Signal(
                    fingerprint="code:self-md-stale",
                    severity=SEVERITY_FYI,
                    area="code",
                    title="SELF.md SHA is stale — tool schemas or cron routes may have changed",
                    detail=f"stored={stored_sha[:8]} fresh={fresh_sha[:8]}",
                    remediation=(
                        "Run 'python core/self_manifest.py' or redeploy "
                        "(deploy.yml regenerates SELF.md before docker build)."
                    ),
                ))
    except Exception:
        logger.warning("heartbeat: self-md-sha check failed", exc_info=True)

    return signals


_SEVERITY_ORDER = [SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_FYI]
_SEVERITY_HEADER = {
    SEVERITY_CRITICAL: "CRITICAL",
    SEVERITY_WARNING: "Warnings",
    SEVERITY_FYI: "FYI",
}


def _plain_text_fallback(signals: list[Signal]) -> str:
    """Deterministic grouped message used when the LLM composer is unavailable."""
    lines: list[str] = []
    for severity in _SEVERITY_ORDER:
        group = [s for s in signals if s.severity == severity]
        if not group:
            continue
        lines.append(f"[{_SEVERITY_HEADER[severity]}]")
        for s in group:
            lines.append(f"• {s.title} — {s.detail}")
            lines.append(f"  → {s.remediation}")
        lines.append("")
    return "\n".join(lines).strip() or "Heartbeat: all systems nominal."


def _compose_message(signals: list[Signal]) -> str:
    """Compose the Telegram message via the worker LLM, with plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "heartbeat.md"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8")
    except OSError:
        return _plain_text_fallback(signals)

    payload = json.dumps([{
        "severity": s.severity, "area": s.area, "title": s.title,
        "detail": s.detail, "remediation": s.remediation,
    } for s in signals], ensure_ascii=False, indent=2)

    try:
        from core.llm_client import LLMClient
        client = LLMClient(
            backend=os.environ["WORKER_AGENT_BACKEND"],
            model=os.environ["WORKER_AGENT_MODEL"],
            api_key=os.environ["WORKER_AGENT_API_KEY"],
        )
        response = client.chat(
            messages=[{"role": "user", "content": payload}],
            system=system_prompt,
        )
        text = (response.get("text") or "").strip()
        if text:
            return text
    except Exception:
        logger.warning("heartbeat: LLM composition failed", exc_info=True)

    return _plain_text_fallback(signals)


def _load_config() -> dict:
    """Load heartbeat config from Firestore. Returns defaults on error."""
    try:
        from memory.firestore_db import HeartbeatConfigStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        store = HeartbeatConfigStore(project_id=project_id, database=database)
        return store.get()
    except Exception:
        logger.warning("heartbeat: config load failed — using defaults", exc_info=True)
        from memory.firestore_db import _HEARTBEAT_CONFIG_DEFAULTS
        return dict(_HEARTBEAT_CONFIG_DEFAULTS)


def _collect_signals(*, tiers: set[str], weekly: bool = False) -> list[Signal]:
    """Run all checkers, then keep only signals whose severity is in `tiers`."""
    raw: list[Signal] = []
    for checker in (check_cron_health, check_tokens, check_degradation, check_deployment):
        try:
            raw.extend(checker())
        except Exception:
            logger.warning("heartbeat: checker %s crashed", checker.__name__, exc_info=True)
    if weekly:
        try:
            raw.extend(check_code())
        except Exception:
            logger.warning("heartbeat: check_code crashed", exc_info=True)
    return [s for s in raw if s.severity in tiers]


def _register_incidents(critical_signals: list[Signal], config: dict) -> list[Signal]:
    """Record open incidents; return those that should trigger a ping."""
    from memory.firestore_db import IncidentStore
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    reping = int(config.get("reping_interval_hours", 24))
    to_ping: list[Signal] = []
    try:
        store = IncidentStore(project_id=project_id, database=database)
        for signal in critical_signals:
            should_ping = store.record_open(signal, reping_interval_hours=reping)
            if should_ping:
                to_ping.append(signal)
    except Exception:
        logger.warning("heartbeat: incident registration failed", exc_info=True)
        to_ping = critical_signals
    return to_ping


def _resolve_absent(active_fingerprints: set) -> None:
    """Resolve Firestore incidents that are no longer signalling."""
    from memory.firestore_db import IncidentStore
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    try:
        store = IncidentStore(project_id=project_id, database=database)
        store.resolve_absent(active_fingerprints)
    except Exception:
        logger.warning("heartbeat: resolve_absent failed", exc_info=True)


def _queue_signals(signals: list[Signal]) -> None:
    """Append signals to the quiet-hours queue in Firestore."""
    from memory.firestore_db import _make_firestore_client
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    try:
        client = _make_firestore_client(project_id, database)
        payload = [{"fingerprint": s.fingerprint, "severity": s.severity, "area": s.area,
                    "title": s.title, "detail": s.detail, "remediation": s.remediation}
                   for s in signals]
        client.collection("heartbeat_queue").document("pending").set(
            {"signals": payload}, merge=True)
    except Exception:
        logger.warning("heartbeat: _queue_signals failed", exc_info=True)


def _drain_quiet_queue(bot, now: datetime, config: dict) -> None:
    """If not in quiet hours, drain any queued signals from previous quiet period."""
    if _in_quiet_hours(config, now):
        return
    from memory.firestore_db import _make_firestore_client
    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    try:
        client = _make_firestore_client(project_id, database)
        doc_ref = client.collection("heartbeat_queue").document("pending")
        snap = doc_ref.get()
        if not snap.exists:
            return
        data = snap.to_dict() or {}
        queued = data.get("signals", [])
        if not queued:
            doc_ref.delete()
            return
        signals = [Signal(**s) for s in queued]
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            send_and_inject(bot, _compose_message(signals), inject_into_conversation=True)
        )
        doc_ref.delete()
    except Exception:
        logger.warning("heartbeat: drain_quiet_queue failed", exc_info=True)


def _run_tick_brain_pass(signals: list[Signal], *, weekly: bool) -> str | None:
    """Run the tick-brain over collected signals. Returns an insight string or None.

    Gate: only runs when signals exist or it is a weekly digest tick.
    On any error (import, LLMError, parse failure), returns None without raising.
    """
    if not signals and not weekly:
        return None  # quiet tick — skip, 0 cost

    try:
        from core.tick_brain import TickBrain
        brain = TickBrain()
    except Exception as exc:
        # TICK_BRAIN_API_KEY not set in this env, or import error — skip gracefully
        logger.debug("tick-brain: skipped (init failed: %s)", exc)
        return None

    signal_summary = "\n".join(
        f"- [{s.severity.upper()}] {s.area}: {s.title} — {s.detail}"
        for s in signals
    ) or "(no active signals)"

    prompt = (
        f"Heartbeat tick — {'weekly digest' if weekly else 'regular tick'}.\n"
        f"Active signals:\n{signal_summary}\n\n"
        "Is there a pattern here, something the checklist can't see, or an action worth taking?"
    )
    try:
        result = brain.think(prompt)
    except Exception as exc:
        logger.debug("tick-brain: think() failed: %s", exc)
        return None

    if result.get("should_act") and result.get("draft"):
        return result["draft"]
    if result.get("reason") and result["reason"] not in ("parse_failure", "llm_error"):
        return result["reason"]
    return None


async def run_tick(bot, now: datetime | None = None) -> list[Signal]:
    """Run one heartbeat tick. Returns the signals collected."""
    now = now or datetime.now(_TZ)
    config = _load_config()
    if not config.get("enabled", True):
        logger.info("heartbeat: disabled in config")
        return []

    _drain_quiet_queue(bot, now, config)

    tiers = _tiers_for_now(config, now)
    signals = _collect_signals(tiers=tiers, weekly=SEVERITY_FYI in tiers)
    logger.info("heartbeat: %d signal(s) in tiers %s", len(signals), sorted(tiers))

    # Tick-brain reasoning pass — interprets signals, spots patterns.
    # Gate: only when signals exist or weekly digest. Non-blocking.
    is_weekly = SEVERITY_FYI in tiers
    tick_insight = _run_tick_brain_pass(signals, weekly=is_weekly)
    if tick_insight:
        logger.info("tick-brain insight: %s", tick_insight)

    active_fps = {s.fingerprint for s in signals}
    critical = [s for s in signals if s.severity == SEVERITY_CRITICAL]
    warnings = [s for s in signals if s.severity == SEVERITY_WARNING]
    fiys = [s for s in signals if s.severity == SEVERITY_FYI]

    to_ping = _register_incidents(critical, config)
    if to_ping:
        msg = _compose_message(to_ping)
        if tick_insight:
            msg = f"{msg}\n\n_Insight: {tick_insight}_"
        if not _in_quiet_hours(config, now):
            await send_and_inject(bot, msg, inject_into_conversation=True)
        else:
            _queue_signals(to_ping)

    if SEVERITY_WARNING in tiers and warnings:
        await send_and_inject(bot, _compose_message(warnings), inject_into_conversation=True)

    if SEVERITY_FYI in tiers and fiys:
        fyi_msg = _compose_message(fiys)
        if tick_insight and not to_ping and not warnings:
            fyi_msg = f"{fyi_msg}\n\n_Insight: {tick_insight}_"
        await send_and_inject(bot, fyi_msg, inject_into_conversation=True)

    _resolve_absent(active_fps)

    deadman_url = os.getenv("HEARTBEAT_DEADMAN_URL", "")
    if deadman_url:
        try:
            import requests as _requests
            _requests.get(deadman_url, timeout=10)
        except Exception:
            logger.warning("heartbeat: dead-man ping failed", exc_info=True)

    return signals


def _cli() -> None:
    from dotenv import load_dotenv
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Klaus heartbeat smoke test")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run all checkers, print signals; no send/write.")
    args = parser.parse_args()
    if args.dry_run:
        signals = _collect_signals(
            tiers={SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_FYI}, weekly=True)
        print(f"[dry-run] {len(signals)} signal(s):")
        for s in signals:
            print(f"  [{s.severity}] {s.title} — {s.detail} -> {s.remediation}")
        if signals:
            print("\n[dry-run] Composed message:")
            print(_compose_message(signals))
        return
    print("Use --dry-run for local testing.")


if __name__ == "__main__":
    _cli()
