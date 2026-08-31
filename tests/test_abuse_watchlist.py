"""Tests for the watchlist: who gets held, and how held material reaches a report."""

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
def env(abuse, tmp_path, monkeypatch):
    """Upload dir + a page password (the at-rest hold key needs one)."""
    from reverse_image_search_bot import settings

    updir = tmp_path / "uploads"
    updir.mkdir()
    monkeypatch.setattr(settings, "UPLOADER", {"uploader": "local", "configuration": {"path": str(updir)}})
    monkeypatch.setattr(settings, "REPORT_BASE_URL", "https://ris.naa.gg")
    monkeypatch.setattr(settings, "REPORT_PAGE_PASSWORD", "hold-key-pw")
    return abuse, updir


def test_hold_reason_covers_open_filed_deleted_and_ban(env):
    """Open, filed and deleted reports all put the uploader on the watchlist."""
    abuse, _updir = env
    for uid in (1, 2, 3, 4, 5):
        abuse.record_user(uid)
    # 1: untouched. 2: open round. 3: filed. 4: deleted. 5: cancelled (NOT watched).
    abuse.create_report("r2", 2, "")
    abuse.create_report("r3", 3, "")
    abuse.mark_report_filed("r3")
    abuse.create_report("r4", 4, "")
    abuse.set_report_status("r4", abuse.REPORT_DELETED)
    abuse.create_report("r5", 5, "")
    abuse.set_report_status("r5", abuse.REPORT_CANCELLED)

    assert abuse.hold_reason_for_user(1) is None
    assert abuse.hold_reason_for_user(2) == abuse.HOLD_INVESTIGATION
    assert abuse.hold_reason_for_user(3) == abuse.HOLD_INVESTIGATION
    assert abuse.hold_reason_for_user(4) == abuse.HOLD_INVESTIGATION
    # A cancelled report means the user did nothing wrong — they come back off.
    assert abuse.hold_reason_for_user(5) is None
    # An unknown user is not watched either.
    assert abuse.hold_reason_for_user(999) is None

    # A ban outranks everything: nothing of theirs is served again.
    abuse.set_banned(3, True)
    assert abuse.hold_reason_for_user(3) == abuse.HOLD_AFTER_BAN


def test_held_upload_is_encrypted_and_never_plaintext_on_disk(env):
    """A banned user's upload exists only as ciphertext under the served PVC."""
    from reverse_image_search_bot.abuse_report import hold

    abuse, updir = env
    abuse.record_user(7)
    abuse.set_banned(7, True)

    stored = hold.store(7, "H1", b"the-bad-bytes")
    assert stored is not None
    path, _nonce, _sha = stored
    abuse.record_file(
        "H1", saved_filename="H1.jpg", user_id=7, file_type="photo", hold_reason=abuse.HOLD_AFTER_BAN, hold=stored
    )

    # It is NOT reachable as a normal upload — the static sidecar serves updir.
    assert not (updir / "H1.jpg").exists()
    on_disk = (updir / path).read_bytes()
    assert on_disk != b"the-bad-bytes"  # ciphertext, not the file

    row = abuse.file_by_unique_id("H1")
    assert row["hold_reason"] == abuse.HOLD_AFTER_BAN
    assert hold.load(row) == b"the-bad-bytes"


def test_re_holding_a_known_file_keeps_the_row_and_ciphertext_in_step(env):
    """A banned user re-sends a file the bot has seen before.

    ``hold.store`` writes a FRESH nonce to the same path every time, but
    ``record_file`` is INSERT OR IGNORE — the pre-existing row keeps the OLD
    nonce, and the mismatch surfaces as ``cryptography.exceptions.InvalidTag``
    when the next report round tries to read the hold. The hold write must
    therefore always be applied to the row, not only on first insert.
    """
    from reverse_image_search_bot.abuse_report import hold

    abuse, _updir = env
    abuse.record_user(7)
    abuse.set_banned(7, True)

    # Seen once before the ban — an ordinary row, no hold.
    abuse.record_file("H1", saved_filename="H1.jpg", user_id=7, file_type="photo")
    assert abuse.file_by_unique_id("H1")["hold_path"] is None

    # Re-uploaded now that they are banned: held, with a brand-new nonce.
    stored = hold.store(7, "H1", b"the-bad-bytes")
    assert stored is not None
    abuse.record_file(
        "H1", saved_filename="H1.jpg", user_id=7, file_type="photo", hold_reason=abuse.HOLD_AFTER_BAN, hold=stored
    )
    abuse.set_file_hold("H1", abuse.HOLD_AFTER_BAN, stored)

    row = abuse.file_by_unique_id("H1")
    assert row["hold_path"] == stored[0]
    assert bytes(row["hold_nonce"]) == stored[1]  # the nonce actually on disk
    assert hold.load(row) == b"the-bad-bytes"  # would raise InvalidTag without the fix


def test_held_files_are_pulled_into_the_next_report(env):
    """Preparing a report picks up held material and re-keys it under P1."""
    from reverse_image_search_bot.abuse_report import crypto, hold, prepare

    abuse, updir = env
    abuse.record_user(8)
    # One ordinary on-disk file, one held (arrived after the ban).
    abuse.record_file("N1", saved_filename="N1.jpg", user_id=8, file_type="photo")
    (updir / "N1.jpg").write_bytes(b"normal")
    stored = hold.store(8, "H2", b"held-bytes")
    abuse.record_file(
        "H2", saved_filename="H2.jpg", user_id=8, file_type="photo", hold_reason=abuse.HOLD_AFTER_BAN, hold=stored
    )

    result = prepare.prepare_report(8)
    assert result.ok
    assert result.encrypted == 2  # BOTH, not just the on-disk one

    key = crypto.derive_key(result.p1 or "")
    got = {}
    for b in abuse.report_blobs(result.report_uuid or ""):
        ct = prepare.blob_ciphertext(b)
        assert ct is not None
        got[b["saved_filename"]] = crypto.decrypt_file(bytes(b["nonce"]), ct, key)
    assert got == {"N1.jpg": b"normal", "H2.jpg": b"held-bytes"}

    # The hold copy is gone — the round owns those bytes now, under P1.
    assert stored is not None
    assert not (updir / stored[0]).exists()
    assert abuse.file_by_unique_id("H2")["hold_path"] is None
    # ...but WHY it was held is kept, as report provenance.
    assert abuse.file_by_unique_id("H2")["hold_reason"] == abuse.HOLD_AFTER_BAN


def test_cancelling_returns_held_files_to_the_hold_not_the_public_dir(env):
    """Cancelling must never publish material that was never public."""
    from reverse_image_search_bot.abuse_report import hold, prepare

    abuse, updir = env
    abuse.record_user(9)
    abuse.record_file("N2", saved_filename="N2.jpg", user_id=9, file_type="photo")
    (updir / "N2.jpg").write_bytes(b"normal")
    stored = hold.store(9, "H3", b"held-bytes")
    abuse.record_file(
        "H3", saved_filename="H3.jpg", user_id=9, file_type="photo", hold_reason=abuse.HOLD_AFTER_BAN, hold=stored
    )
    result = prepare.prepare_report(9)

    assert prepare.restore_report_files(result.report_uuid or "", result.p1 or "") is None
    # The ordinary file comes back online.
    assert (updir / "N2.jpg").read_bytes() == b"normal"
    # The held one does NOT — it went back into the hold.
    assert not (updir / "H3.jpg").exists()
    row = abuse.file_by_unique_id("H3")
    assert row["hold_path"] and hold.load(row) == b"held-bytes"


def test_held_uploaders_lists_waiting_counts_and_prior_outcome(env):
    """The waiting list says how much is queued per user and why they are on it."""
    abuse, _updir = env
    abuse.record_user(10, username="filed_one")
    abuse.record_user(11, username="deleted_one")
    abuse.create_report("rf", 10, "")
    abuse.mark_report_filed("rf")
    abuse.create_report("rd", 11, "")
    abuse.set_report_status("rd", abuse.REPORT_DELETED)
    for i in range(3):
        abuse.record_file(f"a{i}", saved_filename=f"a{i}.jpg", user_id=10, hold_reason=abuse.HOLD_AFTER_BAN)
    abuse.record_file("b0", saved_filename="b0.jpg", user_id=11, hold_reason=abuse.HOLD_INVESTIGATION)
    # A cleared held file does not keep a user in the queue.
    abuse.record_file("b1", saved_filename="b1.jpg", user_id=11, hold_reason=abuse.HOLD_INVESTIGATION)
    abuse.set_files_cleared(["b1"])

    waiting = {r["user_id"]: r for r in abuse.held_uploaders()}
    assert set(waiting) == {10, 11}
    assert waiting[10]["held"] == 3
    assert waiting[10]["last_status"] == "filed"
    assert waiting[11]["held"] == 1  # the cleared one is not waiting
    assert waiting[11]["last_status"] == "deleted"
    # Most files first, so the biggest backlog is dealt with first.
    assert [r["user_id"] for r in abuse.held_uploaders()] == [10, 11]
