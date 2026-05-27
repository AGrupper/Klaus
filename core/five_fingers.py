"""Five Fingers cron entry points — morning pre-practice and evening attendance flows.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/five-fingers-morning  (10:30 Sun/Mon/Wed/Thu Asia/Jerusalem)
  POST /cron/five-fingers-evening  (21:15 Sun/Wed Asia/Jerusalem)

Local smoke test:
  python -m core.five_fingers --dry-run --date 2026-05-14 --flow morning
  python -m core.five_fingers --dry-run --date 2026-05-14 --flow evening
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# isoweekday(): Mon=1 Tue=2 Wed=3 Thu=4 Fri=5 Sat=6 Sun=7
_PRACTICE_DAYS = {3, 7}      # Wednesday, Sunday
_MORNING_AFTER_DAYS = {1, 4}  # Monday (after Sun), Thursday (after Wed)


# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

def _telegram_user_id() -> int:
    raw = os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip()
    return int(raw)


def _get_ping_template() -> str:
    """Read the Hebrew ping template from the first code block in docs/USER.md §6."""
    user_md = Path(__file__).parent.parent / "docs" / "USER.md"
    text = user_md.read_text(encoding="utf-8")
    in_section = False
    in_block = False
    lines: list[str] = []
    for line in text.splitlines():
        if "## 6." in line:
            in_section = True
            continue
        if in_section and line.strip().startswith("```") and not in_block:
            in_block = True
            continue
        if in_block and line.strip().startswith("```"):
            break
        if in_block:
            lines.append(line)
    return "\n".join(lines).strip() or "מה אומר {name}? אתה בא היום?"


def _has_practice_today(today: str) -> bool:
    """Return True if a Five Fingers calendar event exists today between 09:00–22:00."""
    from core.tools import _get_calendar_tool

    try:
        events = _get_calendar_tool().list_events(
            f"{today}T09:00:00+03:00",
            f"{today}T22:00:00+03:00",
        )
    except Exception:
        logger.warning("Five Fingers: calendar fetch failed", exc_info=True)
        return False
        
    return any(
        any(k in (e.get("summary") or "").lower() for k in ["practice", "five fingers", "אימון"])
        for e in events
    )


def _build_stores():
    """Return (RosterStore, AttendanceStore) configured from env."""
    from memory.firestore_db import AttendanceStore, RosterStore

    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return (
        RosterStore(project_id=project_id, database=database),
        AttendanceStore(project_id=project_id, database=database),
    )


# ------------------------------------------------------------------ #
# Public entry points                                                #
# ------------------------------------------------------------------ #

async def run_morning_endpoint(bot: Bot, today: str) -> None:
    """Morning cron handler: pre-practice suggestions or morning-after follow-ups.

    Args:
        bot:   Telegram Bot instance (from _application.bot in web_server).
        today: YYYY-MM-DD calendar date in Jerusalem timezone.
    """
    day_num = date.fromisoformat(today).isoweekday()
    if day_num in _PRACTICE_DAYS:
        await _run_pre_practice(bot, today)
    elif day_num in _MORNING_AFTER_DAYS:
        await _run_morning_after(bot, today)
    else:
        logger.info(
            "Five Fingers morning: no-op for %s (isoweekday=%d)", today, day_num
        )


async def run_evening_endpoint(bot: Bot, today: str) -> None:
    """Evening cron handler: send attendance inline keyboard.

    Args:
        bot:   Telegram Bot instance.
        today: YYYY-MM-DD calendar date in Jerusalem timezone.
    """
    day_num = date.fromisoformat(today).isoweekday()
    if day_num not in _PRACTICE_DAYS:
        logger.info(
            "Five Fingers evening: no-op for %s (isoweekday=%d)", today, day_num
        )
        return
    await _run_evening_keyboard(bot, today)


# ------------------------------------------------------------------ #
# Internal flows                                                     #
# ------------------------------------------------------------------ #

async def _run_pre_practice(bot: Bot, today: str) -> None:
    """Check calendar and send WhatsApp ping suggestions for today's practice."""
    from mcp_tools.five_fingers.composer import (
        build_wa_link,
        render_captains_status,
        render_personal,
    )
    from mcp_tools.five_fingers.recommender import PracticeRecord, Teammate, recommend

    roster_store, attendance_store = _build_stores()
    chat_id = _telegram_user_id()

    if not _has_practice_today(today):
        # Ask Amit once — avoid re-asking if cron somehow fires twice.
        existing = attendance_store.get_practice(today)
        if not (existing and existing.get("asked_if_practice")):
            await bot.send_message(
                chat_id=chat_id,
                text="לא ראיתי אימון בלוח שנה היום — יש אימון?",
            )
            attendance_store.upsert_practice(today, asked_if_practice=True)
        return

    active = roster_store.list_active()
    recent = attendance_store.recent_practices(10)

    teammates = [
        Teammate(doc_id=m["doc_id"], name=m["name"], nickname=m.get("nickname"))
        for m in active
    ]
    records = [
        PracticeRecord(
            practice_date=p["practice_date"],
            attendance=p.get("attendance", {}),
            pinged_pre_practice=p.get("pinged_pre_practice", []),
        )
        for p in recent
    ]

    suggestions = recommend(teammates, records, today)
    if not suggestions:
        await bot.send_message(chat_id=chat_id, text="Five Fingers: אין המלצות להיום.")
        return

    template = _get_ping_template()
    lines = ["*Five Fingers — פינגים מוצעים להיום:*\n"]
    for s in suggestions:
        tm = s.teammate
        display_name = tm.nickname or tm.name
        msg_text = render_personal(template, display_name)
        member = next((m for m in active if m["doc_id"] == tm.doc_id), None)
        if member and member.get("phone_e164"):
            wa_link = build_wa_link(member["phone_e164"], msg_text)
            lines.append(f"• {tm.name} — [WhatsApp]({wa_link})")
        else:
            lines.append(f"• {tm.name}")

    suggested_names = [s.teammate.nickname or s.teammate.name for s in suggestions]
    lines.append(f"\n*קפטנים:*\n{render_captains_status(suggested_names)}")

    await bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="Markdown",
    )

    attendance_store.upsert_practice(
        today,
        pinged_pre_practice=[s.teammate.doc_id for s in suggestions],
    )
    logger.info(
        "Five Fingers pre-practice: sent %d suggestions for %s",
        len(suggestions), today,
    )


async def _run_morning_after(bot: Bot, today: str) -> None:
    """Send WhatsApp follow-up links for players who missed yesterday and weren't pinged."""
    from mcp_tools.five_fingers.composer import build_wa_link, render_personal

    roster_store, attendance_store = _build_stores()
    chat_id = _telegram_user_id()

    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    practice = attendance_store.get_practice(yesterday)
    if not practice:
        logger.info(
            "Five Fingers morning-after: no practice record for %s", yesterday
        )
        return

    attendance: dict[str, str] = practice.get("attendance", {})
    pinged_pre: set[str] = set(practice.get("pinged_pre_practice", []))
    pinged_post: set[str] = set(practice.get("pinged_post_practice", []))
    template = _get_ping_template()

    to_ping: list[dict] = []
    for roster_id, status in attendance.items():
        if status != "missed":
            continue
        # Skip those already contacted (pre-practice or a prior morning-after run).
        if roster_id in pinged_pre or roster_id in pinged_post:
            continue
        member = roster_store.get(roster_id)
        if member:
            to_ping.append(member)

    if not to_ping:
        logger.info(
            "Five Fingers morning-after: nobody to follow up for %s", yesterday
        )
        return

    lines = [f"*Five Fingers — {yesterday} — חסרו ולא נפנגו:*\n"]
    for member in to_ping:
        display_name = member.get("nickname") or member["name"]
        msg_text = render_personal(template, display_name)
        if member.get("phone_e164"):
            wa_link = build_wa_link(member["phone_e164"], msg_text)
            lines.append(f"• {member['name']} — [WhatsApp]({wa_link})")
        else:
            lines.append(f"• {member['name']}")

    await bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="Markdown",
    )

    attendance_store.add_pinged_post(yesterday, [m["doc_id"] for m in to_ping])
    logger.info(
        "Five Fingers morning-after: sent follow-up for %d players for %s",
        len(to_ping), yesterday,
    )


async def _run_evening_keyboard(bot: Bot, today: str) -> None:
    """Send an inline attendance keyboard for tonight's practice."""
    roster_store, attendance_store = _build_stores()
    chat_id = _telegram_user_id()

    if not _has_practice_today(today):
        logger.info("Five Fingers evening: no practice in calendar for %s", today)
        return

    active = roster_store.list_active()
    if not active:
        logger.warning("Five Fingers evening: roster is empty — skipping")
        return

    rows = []
    for member in active:
        roster_id = member["doc_id"]
        name = member["name"]
        rows.append([
            InlineKeyboardButton(
                text=f"✅ {name}",
                callback_data=f"ff_att|{today}|{roster_id}|came",
            ),
            InlineKeyboardButton(
                text=f"❌ {name}",
                callback_data=f"ff_att|{today}|{roster_id}|missed",
            ),
        ])
    rows.append([
        InlineKeyboardButton(text="שמור ✓", callback_data=f"ff_save|{today}")
    ])

    attendance_store.upsert_practice(
        today, attendance={m["doc_id"]: "unknown" for m in active}
    )
    await bot.send_message(
        chat_id=chat_id,
        text=f"*Five Fingers — {today} — נוכחות:*",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )
    logger.info("Five Fingers evening: sent attendance keyboard for %s", today)


# ------------------------------------------------------------------ #
# CLI smoke test                                                     #
# ------------------------------------------------------------------ #

def _cli() -> None:
    import argparse
    import asyncio
    from dotenv import load_dotenv
    from datetime import datetime

    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Five Fingers local smoke test")
    parser.add_argument(
        "--date",
        default=datetime.now(_TZ).date().isoformat(),
        help="YYYY-MM-DD (default: today in Jerusalem time)",
    )
    parser.add_argument(
        "--flow",
        choices=["morning", "evening"],
        default="morning",
        help="Which flow to simulate",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without calling Telegram or Firestore",
    )
    args = parser.parse_args()

    if args.dry_run:
        day_num = date.fromisoformat(args.date).isoweekday()
        day_names = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
        flow_map = {
            "morning": (
                "pre-practice" if day_num in _PRACTICE_DAYS
                else "morning-after" if day_num in _MORNING_AFTER_DAYS
                else "no-op"
            ),
            "evening": "attendance-keyboard" if day_num in _PRACTICE_DAYS else "no-op",
        }
        print(
            f"[dry-run] date={args.date} ({day_names.get(day_num, '?')}) "
            f"flow={args.flow} → {flow_map[args.flow]}"
        )
        print(f"[dry-run] ping template: {_get_ping_template()!r}")
        return

    from telegram.ext import Application

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(bot_token).build()

    async def _run() -> None:
        await app.initialize()
        bot = app.bot
        if args.flow == "morning":
            await run_morning_endpoint(bot, args.date)
        else:
            await run_evening_endpoint(bot, args.date)
        await app.shutdown()

    asyncio.run(_run())
    print("Done.")


if __name__ == "__main__":
    _cli()
