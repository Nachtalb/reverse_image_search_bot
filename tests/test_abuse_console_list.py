"""Tests for the reports console list: paging, search, and the status filter."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def abuse(tmp_path, monkeypatch):
    import reverse_image_search_bot.settings as settings

    db_path = tmp_path / "abuse.db"
    monkeypatch.setattr(settings, "ABUSE_DB_PATH", db_path)
    import reverse_image_search_bot.config.abuse as ab

    ab._local.__dict__.clear()
    ab._all_connections.clear()
    importlib.reload(ab)
    monkeypatch.setattr(ab, "ABUSE_DB_PATH", db_path)
    ab._local.__dict__.clear()
    ab._all_connections.clear()
    return ab


@pytest.fixture
def many(abuse):
    """25 reports, newest last-created, over three users."""
    abuse.record_user(1, username="alice", first_name="Alice")
    abuse.record_user(2, username="bob", first_name="Bob")
    abuse.record_user(3, first_name="Carol", last_name="Dane")
    conn = abuse._get_conn()
    for i in range(25):
        uid = [1, 2, 3][i % 3]
        abuse.create_report(f"uuid{i:02d}", uid, "")
        # Deterministic ordering — created_at defaults to "now" for all of them.
        conn.execute("UPDATE reports SET created_at = ? WHERE report_uuid = ?", (1000 + i, f"uuid{i:02d}"))
    conn.commit()
    return abuse


def test_paging_is_newest_first_and_does_not_repeat_or_skip(many):
    """Two pages of 20 + 5 cover every report exactly once."""
    page1, total = many.search_reports(limit=20, offset=0)
    page2, total2 = many.search_reports(limit=20, offset=20)
    assert total == total2 == 25
    assert len(page1) == 20
    assert len(page2) == 5
    seen = [r["report_uuid"] for r in page1 + page2]
    assert len(set(seen)) == 25
    # Newest first: uuid24 was created last.
    assert seen[0] == "uuid24"
    assert seen[-1] == "uuid00"


def test_search_matches_user_and_report_ids(many):
    """Search covers the uploader (id, @username, name) and the report ids."""
    by_username, n = many.search_reports("alice")
    assert n == 9 and all(r["user_id"] == 1 for r in by_username)
    # A leading @ is optional.
    assert many.search_reports("@alice")[1] == 9
    # A last name works too, and so does a bare user id.
    assert many.search_reports("Dane")[1] == 8
    assert many.search_reports("2")[1] >= 1
    # ...and the report's own uuid.
    assert [r["report_uuid"] for r in many.search_reports("uuid07")[0]] == ["uuid07"]
    assert many.search_reports("nothing-matches-this")[1] == 0


def test_search_filters_before_paging(many):
    """A filtered page must be a page of the MATCHES, not a filtered page."""
    page, total = many.search_reports("alice", limit=5, offset=0)
    assert total == 9
    assert len(page) == 5 and all(r["user_id"] == 1 for r in page)
    rest, _ = many.search_reports("alice", limit=5, offset=5)
    assert len(rest) == 4 and all(r["user_id"] == 1 for r in rest)


def test_status_filter_and_counts(many):
    many.mark_report_filed("uuid00")
    many.mark_report_filed("uuid01")
    many.set_report_status("uuid02", many.REPORT_CANCELLED)

    counts = many.report_status_counts()
    assert counts["filed"] == 2
    assert counts["cancelled"] == 1
    assert counts["preparing"] == 22

    filed, total = many.search_reports(status="filed")
    assert total == 2
    assert {r["report_uuid"] for r in filed} == {"uuid00", "uuid01"}
    # Status and query combine.
    assert many.search_reports("alice", status="filed")[1] == 1


@pytest.mark.asyncio
async def test_api_list_paginates_and_reports_totals(many, monkeypatch):
    import json

    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server
    from tests.test_abuse_server import _req

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    resp = await server.api_reports_list(_req(headers={"X-Page-Secret": ""}, query={"limit": "20", "offset": "0"}))
    data = json.loads(resp.text or "")
    assert data["total"] == 25
    assert len(data["reports"]) == 20
    assert data["statuses"]["preparing"] == 25

    resp = await server.api_reports_list(_req(headers={"X-Page-Secret": ""}, query={"offset": "20"}))
    assert len(json.loads(resp.text or "")["reports"]) == 5  # default limit is 20


@pytest.mark.asyncio
async def test_api_waiting_lists_held_uploaders(abuse, monkeypatch):
    import json

    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server
    from tests.test_abuse_server import _req

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(5, username="held_one")
    abuse.create_report("rf", 5, "")
    abuse.mark_report_filed("rf")
    abuse.set_banned(5, True)
    for i in range(2):
        abuse.record_file(f"h{i}", saved_filename=f"h{i}.jpg", user_id=5, hold_reason=abuse.HOLD_AFTER_BAN)

    resp = await server.api_reports_waiting(_req(headers={"X-Page-Secret": ""}))
    waiting = json.loads(resp.text or "")["waiting"]
    assert len(waiting) == 1
    assert waiting[0]["user_id"] == 5
    assert waiting[0]["held"] == 2
    assert waiting[0]["banned"] is True
    assert waiting[0]["last_status"] == "filed"
