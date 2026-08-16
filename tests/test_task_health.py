"""The 2026-08-14 baseline is 17 real to-dos, 1 dated, 2 filed, median age 116."""
from scripts.active.task_health import summarize


def _task(**overrides) -> dict:
    base = {
        "title": "x", "due_date": None, "hard_deadline_at": None,
        "bucket": "inbox", "project_name": None, "area_name": None,
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_summarize_counts_the_success_criteria():
    tasks = [
        _task(due_date="2026-08-20"),
        _task(hard_deadline_at="2026-08-30"),
        _task(project_id="proj-1", project_name="Klaus"),
        _task(area_id="area-1", area_name="Shopping"),
        _task(),
    ]
    out = summarize(tasks, today="2026-08-14")
    assert out["total"] == 5
    assert out["dated"] == 1
    assert out["with_deadline"] == 1
    assert out["filed"] == 2


def test_summarize_counts_filed_by_id_even_when_the_name_is_missing():
    """normalize_task leaves project_name None when the container uuid is

    missing from the name index even though project_id is set — filed must
    not silently undercount those to-dos.
    """
    tasks = [_task(project_id="proj-1", project_name=None)]
    out = summarize(tasks, today="2026-08-14")
    assert out["filed"] == 1


def test_summarize_counts_inbox_items_by_bucket():
    tasks = [_task(bucket="inbox"), _task(bucket="anytime"), _task(bucket="someday")]
    out = summarize(tasks, today="2026-08-14")
    assert out["inbox"] == 1


def test_summarize_reports_age_from_created_at():
    tasks = [
        _task(created_at="2026-08-04T00:00:00+00:00"),   # 10 days
        _task(created_at="2026-07-15T00:00:00+00:00"),   # 30 days
        _task(created_at="2025-08-14T00:00:00+00:00"),   # 365 days
    ]
    out = summarize(tasks, today="2026-08-14")
    assert out["median_age_days"] == 30
    assert out["oldest_age_days"] == 365


def test_summarize_handles_an_empty_list_without_dividing_by_zero():
    out = summarize([], today="2026-08-14")
    assert out["total"] == 0
    assert out["median_age_days"] is None
    assert out["oldest_age_days"] is None


def test_summarize_tolerates_a_missing_created_at():
    """Things payloads are not guaranteed complete; never crash a report."""
    out = summarize([_task(created_at=None)], today="2026-08-14")
    assert out["total"] == 1
    assert out["median_age_days"] is None


def test_summarize_truncates_a_fractional_median_rather_than_rounding():
    """An even-length list gives a fractional median; report whole elapsed days.

    Two to-dos aged 39 and 40 days have a median of 39.5. Truncating reports 39;
    rounding would report 40, an age neither to-do has. These are whole days
    elapsed, so truncation is deliberate — this test exists to stop a later
    reader "fixing" it to round().
    """
    tasks = [
        _task(created_at="2026-07-06T00:00:00+00:00"),   # 39 days
        _task(created_at="2026-07-05T00:00:00+00:00"),   # 40 days
    ]
    out = summarize(tasks, today="2026-08-14")
    assert out["median_age_days"] == 39
