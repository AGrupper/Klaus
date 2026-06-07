# Security Audit — Phase 24: Strict Coaching Integration + Nutrition Accountability

**Audited:** 2026-06-07
**ASVS Level:** 2
**block_on:** high (BLOCKER = OPEN threat)
**Auditor model:** claude-sonnet-4-6

---

## Verdict: SECURED

**Threats Closed:** 21/21
**Threats Open:** 0/21

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-24-01 | Tampering | mitigate | CLOSED | `memory/firestore_db.py:1492` — `firestore.ArrayUnion([topic_key])` stores plain string only; topic_key flows exclusively from cron-internal `_collect_detected_topics` logic, never from user input |
| T-24-02 | Tampering | accept | CLOSED | Notes reach `derive_session_quality` only via the Telegram path; `_router.py:90` enforces `TELEGRAM_ALLOWED_USER_IDS` before any handler; override keywords are module-level constants at `training_checkin.py:_QUALITY_STRONG_NOTES/_QUALITY_GRIND_NOTES` |
| T-24-03 | DoS | mitigate | CLOSED | `memory/firestore_db.py:1457-1465` — `has_topic` wraps in `try/except Exception`, returns `False` on error; `topics_today` at line 1516-1523 wraps identically, returns `[]` on error; neither method re-raises |
| T-24-04 | Info Disclosure | mitigate | CLOSED | `memory/firestore_db.py:1464,1499-1502,1522` — all CoachingTopicStore log calls emit only `date_str` and `topic_key` (`%r` format); no meal contents, no biometric values |
| T-24-05 | Tampering | mitigate | CLOSED | `proactive_alerts.py:383-392` — `_detect_slot_misses` iterates meals, checks `m.get("timestamp")` for falsiness (skip), then wraps `_to_naive_local(ts_raw)` in `try/except (ValueError, TypeError): continue`; malformed timestamps are skipped, cron cannot raise. CR-01 fix (`_to_naive_local`) converts timezone-aware datetimes to naive local before comparison — it does NOT remove the skip-on-error guard; the `except (ValueError, TypeError)` block remains intact around the parse call |
| T-24-06 | Info Disclosure | accept | CLOSED | Macro/slot flag descriptions expose only the authenticated user's own nutrition numbers; delivery gated by `TELEGRAM_ALLOWED_USER_IDS`; consistent with existing nutrition coaching trust model |
| T-24-07 | DoS | mitigate | CLOSED | `proactive_alerts.py:399` — `if am_anchor is not None:` guards slot #2; `proactive_alerts.py:406` — `if pm_anchor is not None:` guards slot #5; slot #6 always evaluates. Rest-day anchors return `None` from `_resolve_anchor_times` per docstring Pitfall-2 comment at line 205 |
| T-24-08 | Tampering | mitigate | CLOSED | `tools.py:1519-1520` — slug normalization (`strip().lower().replace(...)`) is present and unchanged from T-22-04. The WR-02 fix at lines 1531-1552 only narrows the fuzzy fallback; no filesystem path concatenation introduced |
| T-24-09 | Tampering | mitigate | CLOSED | `tools.py:1542-1544` — `candidate_anchors = anchor_re.findall(content)` followed by `if len(candidate_anchors) != 1: continue`; only a unique single-anchor match returns content; ambiguous or zero matches fall through to the not-found JSON at line 1554 |
| T-24-10 | EoP | accept | CLOSED | `main.py:47` — `MAX_TOOL_ITERATIONS = 12`; all entry points gated by `TELEGRAM_ALLOWED_USER_IDS` at `_router.py:90`; marginal per-turn cost increase for a single allowlisted user |
| T-24-11 | Spoofing | mitigate | CLOSED | `main.py:685-691` — `if last_response_text and len(last_response_text) > 100: return last_response_text`; the returned text is set only from `response["text"]` at line 590-591 (brain output, not synthesized here); the >100-char guard prevents trivially short fragments; anti-fabrication SC-1 preserved |
| T-24-12 | Tampering | mitigate | CLOSED | `proactive_alerts.py:847-857` — `send_and_inject` call at line 848; `add_topic` loop at lines 854-857 is lexically after the send; comment at line 850-852 documents the write-after-send discipline explicitly |
| T-24-13 | Spoofing | mitigate | CLOSED | `proactive_alert.md:90` — "Never invent a number; use only what the gathered data supplies"; `proactive_alert.md:76` — "no fabricated ... paces"; deficit units come from `_gather_nutrition_data` gather layer at `proactive_alerts.py:522-632`, not invented at compose time |
| T-24-14 | DoS | mitigate | CLOSED | `proactive_alerts.py:810-821` — nutrition gather wrapped in `try/except Exception` (fail-open, omit); dedup gate at lines 826-843 wrapped in separate `try/except Exception` (fail-open, all topics fire); anchor resolution at lines 605-614, slot detection at 617-622, macro gap at 625-630 each individually wrapped |
| T-24-15 | Info Disclosure | mitigate | CLOSED | `proactive_alerts.py` logger calls at lines 569, 597, 614, 621, 629, 820, 842, 859-863 log only operation names, dates, and topic keys; no meal contents, macro totals, or raw biometric values appear in log strings |
| T-24-16 | Repudiation | mitigate | CLOSED | `proactive_alert.md:144-149` — "Topics in `coaching_topics_already_raised` must not be repeated ... A topic from `already_raised` may be referenced once only if its underlying condition has materially worsened ... frame it as an escalation, not a repeat"; implements D-02 one-escalation rule |
| T-24-17 | Tampering | mitigate | CLOSED | `morning_briefing.py:142-158` — `add_topic` loop after `send_and_inject` at line 140; `weekly_training_review.py:372-391` — `add_topic` loop after `send_and_inject` at line 373; both wrapped best-effort; neither writes before send |
| T-24-18 | DoS | mitigate | CLOSED | `morning_briefing.py:323-343` — CoachingTopicStore gather wrapped in `try/except`, fail-open to `[]`; `weekly_training_review.py:232-250` — same pattern; `_compose_review` coaching guide injection at lines 295-300 wrapped in `try/except`, fail-open to `""` |
| T-24-19 | Spoofing | mitigate | CLOSED | `weekly_training_review.md:37` — "PHASE 25 FENCE — ABSOLUTELY FORBIDDEN: Do NOT compute, state, or imply any dated projection ... 'N weeks behind' ... That is Phase 25 work"; quality trend uses `training_log[].quality` enum values at lines 20, 70-79; `weekly_training_review.md:64` — "Never invent numbers — if the data is absent, say nothing" |
| T-24-20 | Info Disclosure | mitigate | CLOSED | `weekly_training_review.py` logger calls at lines 83, 110, 143, 147, 177, 190, 220, 239, 249, 299, 308, 343, 345, 391 log only operation names and generic failure descriptions; `quality` is a 3-value enum passed via `training_log` payload, not emitted to logs |
| T-24-21 | Repudiation | mitigate | CLOSED | `morning_briefing.md:192-207` — "D-08: Prior-Day Unresolved Miss" section instructs brain to surface `coaching_topics_yesterday` entries as "one low-priority contextual line"; data gathered at `morning_briefing.py:329-331` (`coaching_topics_yesterday = _cts.topics_today(yesterday_iso)`) |
| T-24-SC | Tampering | N/A | CLOSED | No new pip/npm/cargo packages introduced across any of the five plans |

---

## Threat Flags from SUMMARY.md

No SUMMARY.md `## Threat Flags` section was found in any of the five plan summaries that introduced new attack surface not covered by the plan-time register.

---

## Unregistered Flags

None.

---

## CR-01 Fix Verification (T-24-05 Integrity)

The code-review fix that introduced `_to_naive_local` (`proactive_alerts.py:176-192`) converts timezone-aware ISO timestamps to naive Asia/Jerusalem datetimes before comparison with the slot windows. The T-24-05 malformed-timestamp guard is fully preserved:

- `_to_naive_local` is called inside the existing `try/except (ValueError, TypeError): continue` block at `proactive_alerts.py:389-392`
- A malformed ISO string that causes `datetime.fromisoformat()` to raise `ValueError` inside `_to_naive_local` propagates out and is caught by the outer `except (ValueError, TypeError)`, which skips the meal
- A `None` or non-string value caught at `ts_raw = m.get("timestamp")` with the `if not ts_raw: continue` guard at line 387 is handled before `_to_naive_local` is ever called
- The CR-01 fix did not weaken the guard

---

## Notes

- T-24-02 (accepted risk): the accept disposition is reasonable — worst-case impact is self-inflicted mislabeling of the allowlisted user's own session quality, with no data exfiltration or third-party impact.
- T-24-06 (accepted risk): the accept disposition is reasonable — the only recipient is the allowlisted Telegram user whose data is being surfaced.
- T-24-10 (accepted risk): the accept disposition is reasonable — a single allowlisted user, 8→12 marginal iteration increase, no external cost amplification surface.
- All `mitigate` dispositions confirmed present by direct grep match at the specific file:line cited; no mitigation accepted on structural inference alone.
