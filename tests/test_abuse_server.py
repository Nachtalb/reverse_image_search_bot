"""Tests for the report server handlers (auth gating, cleanup) with mocks."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web


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


def _req(headers=None, match=None, json_body=None, app=None):
    r = MagicMock(spec=web.Request)
    r.headers = headers or {}
    r.query = {}
    r.match_info = match or {}
    r.app = app if app is not None else {"bot": None}
    if json_body is not None:
        r.json = AsyncMock(return_value=json_body)
    return r


@pytest.mark.asyncio
async def test_unlock_requires_admin(abuse, monkeypatch):
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(server, "_admin_from_request", lambda req: None)
    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    with pytest.raises(web.HTTPUnauthorized):
        await server.api_unlock(_req(match={"uuid": "u"}))


@pytest.mark.asyncio
async def test_unlock_wrong_page_password(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "correct")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1, username="x")
    abuse.create_report("u", 1, "")
    req = _req(headers={"X-Page-Secret": "wrong"}, match={"uuid": "u"})
    with pytest.raises(web.HTTPForbidden):
        await server.api_unlock(req)


@pytest.mark.asyncio
async def test_unlock_ok_returns_meta(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "pw")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(7, username="baduser", first_name="Bad")
    abuse.create_report("u", 7, "")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    req = _req(headers={"X-Page-Secret": "pw"}, match={"uuid": "u"})
    resp = await server.api_unlock(req)
    import json

    data = json.loads(resp.text or "")
    assert data["user"]["id"] == 7
    assert data["user"]["username"] == "baduser"
    assert len(data["blobs"]) == 1


@pytest.mark.asyncio
async def test_status_needs_admin_but_not_secret(abuse, monkeypatch):
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    abuse.set_report_status("u", abuse.REPORT_READY)
    resp = await server.api_status(_req(match={"uuid": "u"}))
    import json

    assert json.loads(resp.text or "")["status"] == abuse.REPORT_READY


@pytest.mark.asyncio
async def test_select_persists(abuse, monkeypatch):
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1)
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    bid = abuse.blob_meta("u")[0]["id"]
    req = _req(headers={"X-Page-Secret": "pw"}, match={"uuid": "u"}, json_body={"selections": {str(bid): "A1"}})
    await server.api_select(req)
    sel = abuse.report_blobs("u", selected_only=True)
    assert len(sel) == 1 and sel[0]["classification"] == "A1"


@pytest.mark.asyncio
async def test_cancel_purges_blobs_but_keeps_files_and_relation(abuse, monkeypatch, tmp_path):
    """Cancel = user did nothing wrong: restore the files + keep the relation.

    Preparing took the plaintext off disk, so cancelling must decrypt it back;
    the files-table row (find_user_by_filename) must survive too.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import crypto, server

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1)
    # provenance relation: filename -> user
    abuse.record_file(file_unique_id="A", saved_filename="A.jpg", original_filename="orig.jpg", user_id=1)
    abuse.create_report("u", 1, "")
    p1 = "the-image-key"
    plaintext = b"plaintext image"
    nonce, ct = crypto.encrypt_file(plaintext, crypto.derive_key(p1))
    abuse.add_report_blob(
        "u",
        file_unique_id="A",
        saved_filename="A.jpg",
        nonce=nonce,
        ciphertext=ct,
        plaintext_sha256=crypto.sha256_hex(plaintext),
    )
    req = _req(headers={"X-Page-Secret": "pw"}, match={"uuid": "u"}, json_body={"image_key": p1})
    await server.api_cancel(req)

    # report cancelled, blobs gone
    assert abuse.get_report("u")["status"] == abuse.REPORT_CANCELLED
    assert abuse.blob_meta("u") == []
    # BUT: disk file restored, filename->user relation kept, user kept
    assert (updir / "A.jpg").read_bytes() == plaintext
    assert abuse.find_user_by_filename("A.jpg") == 1
    assert abuse.get_user(1) is not None


def test_finish_moves_reported_ciphertext_into_the_db(abuse, monkeypatch, tmp_path):
    """Filing is what earns a place in SQLite: disk ciphertext -> DB, dir purged."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import prepare, server

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"uploader": "local", "configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")

    abuse.record_user(1)
    for fid in ("A", "B"):
        abuse.record_file(fid, saved_filename=f"{fid}.jpg", user_id=1, file_type="photo")
        (updir / f"{fid}.jpg").write_bytes(b"bytes-" + fid.encode())
    result = prepare.prepare_report(1)
    uuid = result.report_uuid

    # Nothing in the DB yet — ciphertext is on disk only.
    assert all(bytes(b["ciphertext"]) == b"" for b in abuse.report_blobs(uuid))
    cdir = updir / "report_files" / uuid
    assert len(list(cdir.iterdir())) == 2

    ids = {m["file_unique_id"]: m["id"] for m in abuse.blob_meta(uuid)}
    abuse.set_blob_selection(uuid, {ids["A"]: "A1"})
    server._cleanup_after_finish(abuse.get_report(uuid))

    kept = abuse.report_blobs(uuid)
    assert [b["file_unique_id"] for b in kept] == ["A"]
    # The reported blob now carries its bytes in the DB and no disk dependency.
    assert bytes(kept[0]["ciphertext"]) != b""
    assert kept[0]["cipher_path"] is None
    assert not cdir.exists()  # whole ciphertext dir gone


def test_cleanup_after_finish_keeps_reported_purges_unselected(abuse, monkeypatch, tmp_path):
    """On finish: the reported files' blobs are KEPT, everything else is purged.

    No plaintext is on disk at this point — preparing the report removed it.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})

    abuse.record_user(1)
    abuse.create_report("u", 1, "h")
    abuse.add_report_blob(
        "u", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.add_report_blob(
        "u", file_unique_id="B", saved_filename="B.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="2"
    )
    # Report only A.
    ids = {m["file_unique_id"]: m["id"] for m in abuse.blob_meta("u")}
    abuse.set_blob_selection("u", {ids["A"]: "A1"})

    rep = abuse.get_report("u")
    server._cleanup_after_finish(rep)

    # A (reported): its encrypted blob is KEPT
    kept = {b["file_unique_id"] for b in abuse.report_blobs("u")}
    assert kept == {"A"}
    # Nothing of this round is left on disk.
    assert list(updir.iterdir()) == []
    # user + report survive
    assert abuse.get_user(1) is not None
    assert abuse.get_report("u") is not None


@pytest.mark.asyncio
async def test_submit_files_and_finishes_and_keeps_blobs(abuse, monkeypatch, tmp_path):
    """/api/submit does submit+finish in one shot, deletes disk, keeps blobs.

    NCMEC is mocked; the encryption round-trips a real blob so the P1 decrypt +
    hash-verify path is exercised.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import crypto, ncmec, server

    updir = tmp_path / "uploads"
    updir.mkdir()
    plaintext = b"the bad image bytes"
    (updir / "A.jpg").write_bytes(plaintext)
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}})

    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")  # gate open

    # NCMEC filed → returns a report id + hex file ids
    submitted = AsyncMock(return_value=(987654, ["3a1d4fd4106b82499b7c93442aa7dca4"]))
    monkeypatch.setattr(ncmec, "submit_and_finish", submitted)

    p1 = "test-image-key"
    key = crypto.derive_key(p1)
    nonce, ct = crypto.encrypt_file(plaintext, key)

    abuse.record_user(1, username="bad")
    abuse.record_file(
        "A", saved_filename="A.jpg", user_id=1, original_filename="evidence-original.jpg", file_type="photo"
    )
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u",
        file_unique_id="A",
        saved_filename="A.jpg",
        nonce=nonce,
        ciphertext=ct,
        plaintext_sha256=crypto.sha256_hex(plaintext),
    )
    bid = abuse.blob_meta("u")[0]["id"]
    abuse.set_blob_selection("u", {bid: "A1"})

    # Pass a live bot_data so the finish path can live-ban the uploader.
    bot_data: dict = {}
    req = _req(
        headers={"X-Page-Secret": ""},
        match={"uuid": "u"},
        json_body={"image_key": p1},
        app={"bot": None, "bot_data": bot_data},
    )
    resp = await server.api_submit(req)
    import json

    data = json.loads(resp.text or "")
    # Submit is async now: the endpoint returns immediately and the pipeline
    # runs as a background task the page polls. Await it directly here.
    assert data["status"] == abuse.REPORT_SUBMITTING
    task = server._submit_tasks.get("u")
    assert task is not None
    await task
    submitted.assert_awaited_once()
    # Per-file NCMEC fields: original_file_name keeps the uploader's original name,
    # location_of_file is our public copy's URL (two distinct facts, two fields).
    assert submitted.await_args is not None
    sent_files = submitted.await_args.args[0]
    assert len(sent_files) == 1
    assert sent_files[0]["filename"] == "evidence-original.jpg"
    assert "A.jpg" in sent_files[0]["location"]
    # report is filed, disk file gone, encrypted blob KEPT
    rep = abuse.get_report("u")
    assert rep["status"] == abuse.REPORT_FILED
    assert rep["ncmec_report_id"] == 987654
    assert not (updir / "A.jpg").exists()
    assert len(abuse.blob_meta("u")) == 1
    # Filing auto-bans the uploader: durable DB record AND the live in-memory list.
    assert abuse.is_banned(1)
    assert 1 in bot_data["banned_users"]


@pytest.mark.asyncio
async def test_reports_list(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1, username="bad")
    abuse.create_report("u1", 1, "")
    abuse.set_report_status("u1", abuse.REPORT_CANCELLED)  # cancelled reports still listed
    abuse.create_report("u2", 1, "")

    resp = await server.api_reports_list(_req(headers={"X-Page-Secret": ""}))
    import json

    data = json.loads(resp.text or "")
    uuids = {r["uuid"]: r["status"] for r in data["reports"]}
    assert uuids["u1"] == abuse.REPORT_CANCELLED
    assert uuids["u2"] == abuse.REPORT_PREPARING


@pytest.mark.asyncio
async def test_reports_create_by_username(abuse, monkeypatch, tmp_path):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"img")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(55, username="BadGuy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)

    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "@badguy"})  # case-insensitive
    resp = await server.api_reports_create(req)
    import json

    data = json.loads(resp.text or "")
    assert data["ok"] is True
    res = data["results"][0]
    assert res["user_id"] == 55
    assert res["encrypted"] == 1
    assert res["p1"]  # one-time key returned
    # a ready report now exists for the user
    assert abuse.active_report_for_user(55)["report_uuid"] == res["uuid"]


@pytest.mark.asyncio
async def test_reports_create_dms_p1(abuse, monkeypatch, tmp_path):
    """Creating a report via the app DMs the admin the P1 image key."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"img")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 4242)

    abuse.record_user(55, username="badguy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)

    bot = MagicMock()
    bot.send_message = AsyncMock()
    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "55"}, app={"bot": bot})
    resp = await server.api_reports_create(req)
    import json

    data = json.loads(resp.text or "")
    bot.send_message.assert_awaited_once()
    args, _kwargs = bot.send_message.call_args
    assert args[0] == 4242  # DMed the requesting admin
    assert data["results"][0]["p1"] in args[1]  # the P1 key is in the message body


@pytest.mark.asyncio
async def test_reports_create_already_filed_message(abuse, monkeypatch, tmp_path):
    """Creating for a user whose files were already filed points at the NCMEC report."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()  # empty — no files on disk
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(55, username="badguy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)  # recorded but not on disk
    # a prior FILED report with a kept blob
    abuse.create_report("old", 55, "")
    abuse.add_report_blob(
        "old", file_unique_id="A", saved_filename="A.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="1"
    )
    abuse.set_report_ncmec_id("old", 700200)
    abuse.mark_report_filed("old")

    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "A.jpg"})
    resp = await server.api_reports_create(req)
    import json

    res = json.loads(resp.text or "")["results"][0]
    assert res["ncmec_report_id"] == 700200  # points at the NCMEC report id


@pytest.mark.asyncio
async def test_reports_create_existing_reported_per_result(abuse, monkeypatch, tmp_path):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    (updir / "A.jpg").write_bytes(b"img")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(55, username="badguy")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)
    abuse.create_report("existing", 55, "")
    abuse.set_report_status("existing", abuse.REPORT_READY)

    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": "55"})
    resp = await server.api_reports_create(req)
    import json

    assert resp.status == 200
    res = json.loads(resp.text or "")["results"][0]
    assert res["existing_uuid"] == "existing"


@pytest.mark.asyncio
async def test_reports_create_bulk_urls_one_report_per_uploader(abuse, monkeypatch, tmp_path):
    """A pasted Cloudflare report creates one round per unique uploader."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    updir = tmp_path / "uploads"
    updir.mkdir()
    for name in ("A.jpg", "B.jpg", "C.jpg"):
        (updir / name).write_bytes(b"img")
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://x/f"})
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)

    abuse.record_user(55, username="one")
    abuse.record_user(66, username="two")
    abuse.record_file("A", saved_filename="A.jpg", user_id=55)
    abuse.record_file("B", saved_filename="B.jpg", user_id=55)  # same uploader as A
    abuse.record_file("C", saved_filename="C.jpg", user_id=66)

    target = (
        "URLs: hxxps://ris.naa[.]gg/f/A.jpg, hxxps://ris.naa[.]gg/f/B.jpg, "
        "hxxps://ris.naa[.]gg/f/C.jpg, hxxps://ris.naa[.]gg/f/nope.jpg"
    )
    req = _req(headers={"X-Page-Secret": ""}, json_body={"target": target})
    resp = await server.api_reports_create(req)
    import json

    data = json.loads(resp.text or "")
    assert [r["user_id"] for r in data["results"]] == [55, 66]  # deduped, in order
    assert data["unknown"] == ["nope.jpg"]
    assert all(r["uuid"] for r in data["results"])


def test_filed_report_stats_filed_only_with_language_and_times(abuse):
    """Stats are FILED-only, carry the user's language + reported files' upload times."""
    import time

    # User A (lang 'en') → one filed report over two files. User B (lang 'de') →
    # a CANCELLED report (must be excluded). User C (no lang) → filed.
    abuse.record_user(1, username="a", language_code="en")
    abuse.record_user(2, username="b", language_code="de")
    abuse.record_user(3, username="c")
    # f2 is a sticker (a STATIC IMAGE, must NOT be counted as a video).
    for uid, fid, ftype in [(1, "f1", "photo"), (1, "f2", "sticker"), (2, "f3", "photo"), (3, "f4", "video")]:
        abuse.record_file(fid, saved_filename=f"{fid}.jpg", user_id=uid, file_type=ftype)

    conn = abuse._get_conn()
    # Deterministic upload_time per file so the heatmap has known inputs.
    base = int(time.time())
    for fid, t in [("f1", base), ("f2", base + 10), ("f3", base + 20), ("f4", base + 30)]:
        conn.execute("UPDATE files SET upload_time = ? WHERE file_unique_id = ?", (t, fid))
    conn.commit()

    # Filed report for user 1 with two blobs.
    abuse.create_report("rA", 1, "")
    for fid in ("f1", "f2"):
        abuse.add_report_blob(
            "rA", file_unique_id=fid, saved_filename=f"{fid}.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="h"
        )
    abuse.mark_report_filed("rA")
    # CANCELLED report for user 2 (excluded).
    abuse.create_report("rB", 2, "")
    abuse.add_report_blob(
        "rB", file_unique_id="f3", saved_filename="f3.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="h"
    )
    abuse.set_report_status("rB", abuse.REPORT_CANCELLED)
    # Filed report for user 3.
    abuse.create_report("rC", 3, "")
    abuse.add_report_blob(
        "rC", file_unique_id="f4", saved_filename="f4.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="h"
    )
    abuse.mark_report_filed("rC")

    recs = abuse.filed_report_stats()
    by_user = {r["user_id"]: r for r in recs}
    # Only the two FILED reports — the cancelled one is gone.
    assert set(by_user) == {1, 3}
    assert len(recs) == 2
    assert by_user[1]["language"] == "en"
    assert by_user[3]["language"] is None
    # User 1's report carries BOTH reported files' upload times.
    assert sorted(by_user[1]["upload_times"]) == [base, base + 10]
    assert by_user[3]["upload_times"] == [base + 30]
    # finished_at is populated (drives the year/month dropdowns).
    assert by_user[1]["finished_at"] and by_user[3]["finished_at"]
    # File-type breakdown reflects the ACTUAL recorded types — a sticker stays a
    # sticker (NOT a video). User 1: one photo + one sticker. User 3: one video.
    assert by_user[1]["file_types"] == {"photo": 1, "sticker": 1}
    assert by_user[3]["file_types"] == {"video": 1}


@pytest.mark.asyncio
async def test_api_stats_gated_and_shaped(abuse, monkeypatch):
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(1, username="a", language_code="en")
    abuse.record_file("f1", saved_filename="f1.jpg", user_id=1)
    abuse.create_report("rA", 1, "")
    abuse.add_report_blob(
        "rA", file_unique_id="f1", saved_filename="f1.jpg", nonce=b"n", ciphertext=b"c", plaintext_sha256="h"
    )
    abuse.mark_report_filed("rA")

    resp = await server.api_reports_stats(_req(headers={"X-Page-Secret": ""}))
    import json

    data = json.loads(resp.text or "")
    assert len(data["records"]) == 1
    assert data["records"][0]["language"] == "en"


def test_report_meta_includes_language(abuse, tmp_path, monkeypatch):
    """The report page meta payload surfaces the uploader's language_code."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import server

    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    abuse.record_user(77, username="x", language_code="pt-BR")
    abuse.create_report("rM", 77, "")

    user = abuse.get_user(77)
    assert user["language_code"] == "pt-BR"


@pytest.mark.asyncio
async def test_review_returns_payload_without_filing(abuse, tmp_path, monkeypatch):
    """/api/review builds the real NCMEC payload (files + reporter) and files NOTHING."""
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import crypto, ncmec, server

    updir = tmp_path / "uploads"
    updir.mkdir()
    plaintext = b"\xff\xd8\xff the bad image bytes"
    (updir / "A.jpg").write_bytes(plaintext)
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://ris.naa.gg/f"})
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "NCMEC_REPORTER_EMAIL", "report@nachtalb.io")

    # If review ever called the network, this would blow up — it must NOT.
    boom = AsyncMock(side_effect=AssertionError("review must not file"))
    monkeypatch.setattr(ncmec, "submit_and_finish", boom)

    p1 = "test-image-key"
    key = crypto.derive_key(p1)
    nonce, ct = crypto.encrypt_file(plaintext, key)
    abuse.record_user(1, username="bad", first_name="B", last_name="G")
    abuse.record_file("A", saved_filename="A.jpg", user_id=1, original_filename="evidence.jpg", file_type="photo")
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u",
        file_unique_id="A",
        saved_filename="A.jpg",
        nonce=nonce,
        ciphertext=ct,
        plaintext_sha256=crypto.sha256_hex(plaintext),
    )
    bid = abuse.blob_meta("u")[0]["id"]
    abuse.set_blob_selection("u", {bid: "A1"})

    req = _req(
        headers={"X-Page-Secret": ""},
        match={"uuid": "u"},
        json_body={"image_key": p1},
        app={"bot": None, "bot_data": {}},
    )
    resp = await server.api_review(req)
    import json

    data = json.loads(resp.text or "")
    # Reporter email surfaced; one file with full hashes + classification; nothing filed.
    assert data["reporter"]["reporting_person"]["email"][0]["value"] == "report@nachtalb.io"
    assert len(data["files"]) == 1
    f = data["files"][0]
    # A photo upload (is_video unset) is an "image", not an extracted "frame".
    assert f["kind"] == "image"
    assert f["filename"] == "evidence.jpg"
    assert f["classification"] == "A1"
    assert {"MD5", "SHA1", "SHA256"} <= {h["hash_type"] for h in f["hashes"]}
    # file_details mirrors what submit sends (industry_classification A1 present)
    assert data["file_details"][0]["industry_classification"] == "A1"
    boom.assert_not_called()
    # report status untouched (still preparing/ready, NOT filed)
    assert abuse.get_report("u")["status"] != abuse.REPORT_FILED


@pytest.mark.asyncio
async def test_review_video_piece_labeled_frame(abuse, tmp_path, monkeypatch):
    """A real video upload yields a 'frame' still piece plus a 'video' piece.

    Counterpart to the image case: when the source IS a video, the extracted
    still is correctly labeled 'frame' (not 'image'), and the source video is a
    separate 'video' piece.
    """
    from reverse_image_search_bot import settings
    from reverse_image_search_bot.abuse_report import crypto, ncmec, server

    updir = tmp_path / "uploads"
    (updir / "report_videos").mkdir(parents=True)
    frame_plain = b"\xff\xd8\xff extracted-frame"
    (updir / "V.jpg").write_bytes(frame_plain)
    monkeypatch.setattr(settings, "UPLOADER", {"configuration": {"path": str(updir)}, "url": "https://ris.naa.gg/f"})
    monkeypatch.setattr(server, "_admin_from_request", lambda req: 42)
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "")
    monkeypatch.setattr(settings, "NCMEC_REPORTER_EMAIL", "report@nachtalb.io")
    monkeypatch.setattr(ncmec, "submit_and_finish", AsyncMock(side_effect=AssertionError("review must not file")))

    p1 = "vid-key"
    key = crypto.derive_key(p1)
    nonce, ct = crypto.encrypt_file(frame_plain, key)
    # Encrypt a stand-in "video" on disk and attach it to the blob.
    video_plain = b"\x00\x00\x00 ftypmp42 the-source-video"
    vnonce, vct = crypto.encrypt_file(video_plain, key)
    (updir / "report_videos" / "V.mp4.enc").write_bytes(vct)

    abuse.record_user(1, username="bad", first_name="B", last_name="G")
    abuse.record_file(
        "V", saved_filename="V.jpg", user_id=1, original_filename="clip.mp4", file_type="video", is_video=True
    )
    abuse.create_report("u", 1, "")
    abuse.add_report_blob(
        "u",
        file_unique_id="V",
        saved_filename="V.jpg",
        nonce=nonce,
        ciphertext=ct,
        plaintext_sha256=crypto.sha256_hex(frame_plain),
    )
    bid = abuse.blob_meta("u")[0]["id"]
    abuse.set_blob_selection("u", {bid: "A1"})
    abuse.set_blob_video(
        bid,
        video_path="report_videos/V.mp4.enc",
        video_nonce=vnonce,
        video_sha256=crypto.sha256_hex(video_plain),
        video_filename="clip.mp4",
    )

    req = _req(
        headers={"X-Page-Secret": ""},
        match={"uuid": "u"},
        json_body={"image_key": p1},
        app={"bot": None, "bot_data": {}},
    )
    resp = await server.api_review(req)
    import json

    data = json.loads(resp.text or "")
    kinds = {f["kind"]: f["filename"] for f in data["files"]}
    assert kinds.get("frame") == "clip.mp4"  # the extracted still — labeled frame, not image
    assert "video" in kinds  # the source video is its own piece
