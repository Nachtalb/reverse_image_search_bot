"""SQLite backend for chat configuration with typed columns."""
import json
import sqlite3
import threading
from pathlib import Path

from reverse_image_search_bot.settings import CONFIG_DB_PATH

_local = threading.local()

# Column definitions: (name, sql_type, default_value)
# list/dict columns are stored as JSON text
COLUMNS = [
    ("show_buttons", "INTEGER", True),
    ("show_best_match", "INTEGER", True),
    ("show_link", "INTEGER", True),
    ("auto_search_enabled", "INTEGER", True),
    ("auto_search_engines", "TEXT", None),       # JSON list or NULL
    ("button_engines", "TEXT", None),             # JSON list or NULL
    ("engine_empty_counts", "TEXT", "{}"),         # JSON dict
    ("onboarded", "INTEGER", False),
    ("failures_in_a_row", "INTEGER", 0),
]

# Fields stored as JSON text that need serialization
_JSON_FIELDS = {"auto_search_engines", "button_engines", "engine_empty_counts"}
# Fields stored as INTEGER that are actually booleans
_BOOL_FIELDS = {"show_buttons", "show_best_match", "show_link", "auto_search_enabled", "onboarded"}


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection with WAL mode."""
    if not hasattr(_local, "conn") or _local.conn is None:
        CONFIG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(CONFIG_DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _ensure_schema(conn)
        _local.conn = conn
    return _local.conn


def _ensure_schema(conn: sqlite3.Connection):
    """Create or migrate the config table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_config (
            chat_id INTEGER PRIMARY KEY
        )
    """)
    # Add any missing columns (try/except for concurrent thread safety)
    for name, sql_type, default in COLUMNS:
        try:
            default_sql = _to_sql_default(default)
            conn.execute(f"ALTER TABLE chat_config ADD COLUMN {name} {sql_type} DEFAULT {default_sql}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
    conn.commit()


def _to_sql_default(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return f"'{value}'"
    return "NULL"


def _to_python(name: str, value):
    """Convert a SQLite value back to its Python type."""
    if value is None:
        if name in _JSON_FIELDS:
            # engine_empty_counts defaults to {} not None
            if name == "engine_empty_counts":
                return {}
            return None
        return None
    if name in _BOOL_FIELDS:
        return bool(value)
    if name in _JSON_FIELDS:
        return json.loads(value)
    return value


def _to_sql(name: str, value):
    """Convert a Python value to its SQLite storage form."""
    if value is None:
        return None
    if name in _BOOL_FIELDS:
        return 1 if value else 0
    if name in _JSON_FIELDS:
        return json.dumps(value)
    return value


def load_config(chat_id: int) -> dict | None:
    """Load config dict for a chat_id, or None if not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM chat_config WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    if row is None:
        return None
    col_names = [name for name, _, _ in COLUMNS]
    return {name: _to_python(name, row[name]) for name in col_names if name in row.keys()}


def save_config(chat_id: int, config: dict) -> None:
    """Insert or update config for a chat_id."""
    conn = _get_conn()
    col_names = [name for name, _, _ in COLUMNS]
    present = {k: v for k, v in config.items() if k in set(col_names)}

    cols = ["chat_id"] + list(present.keys())
    vals = [chat_id] + [_to_sql(k, v) for k, v in present.items()]
    placeholders = ", ".join(["?"] * len(cols))
    col_str = ", ".join(cols)
    update_str = ", ".join(f"{c} = excluded.{c}" for c in present.keys())

    conn.execute(
        f"INSERT INTO chat_config ({col_str}) VALUES ({placeholders}) "
        f"ON CONFLICT(chat_id) DO UPDATE SET {update_str}",
        vals,
    )
    conn.commit()


def save_field(chat_id: int, name: str, value) -> None:
    """Insert or update a single field for a chat_id."""
    valid_columns = {col for col, _, _ in COLUMNS}
    if name not in valid_columns:
        raise ValueError(f"Unknown config column: {name!r}")
    conn = _get_conn()
    sql_val = _to_sql(name, value)
    conn.execute(
        f"INSERT INTO chat_config (chat_id, {name}) VALUES (?, ?) "
        f"ON CONFLICT(chat_id) DO UPDATE SET {name} = excluded.{name}",
        (chat_id, sql_val),
    )
    conn.commit()


def migrate_json_files(config_dir: Path) -> int:
    """Migrate existing JSON config files to SQLite. Returns count migrated."""
    count = 0
    migrated_files = []

    # Chat configs: {chat_id}_chat.json
    for f in config_dir.glob("*_chat.json"):
        try:
            chat_id = int(f.stem.replace("_chat", ""))
            data = json.loads(f.read_text())
            if load_config(chat_id) is None:
                save_config(chat_id, data)
                count += 1
                migrated_files.append(f)
        except (ValueError, json.JSONDecodeError):
            continue

    # User configs: {user_id}.json — old per-user settings are dropped.
    # failures_in_a_row is now tracked per-chat (starts fresh at 0).
    # Rename old user config files to .bak so they don't clutter the directory.
    for f in config_dir.glob("*.json"):
        if "_chat" in f.stem or f.stem == "pixiv":
            continue
        try:
            int(f.stem)  # validate it's a user config file
            migrated_files.append(f)
        except ValueError:
            continue

    # Rename migrated files to .bak so migration doesn't re-run
    for f in migrated_files:
        f.rename(f.with_suffix(f.suffix + ".bak"))

    return count
