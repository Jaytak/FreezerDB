from __future__ import annotations

import html
import base64
import binascii
import ctypes
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import tempfile
import traceback
import zipfile
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "freezer.db"
AUTH_DB_PATH = ROOT / "webuser_auth.db"
CONFIG_PATH = ROOT / "config.yml"
STATIC_DIR = ROOT / "static"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
HOST = DEFAULT_HOST
PORT = DEFAULT_PORT
LOG_PATH = ROOT / "server.log"
DEFAULT_LOG_MAX_MB = 64
LOG_LOCK = threading.Lock()
NETWORK_LOCK = threading.Lock()
APP_NETWORK_BYTES = 0
RENDER_CONTEXT = threading.local()
SERVER_INSTANCE: ThreadingHTTPServer | None = None
SESSION_COOKIE = "freezer_stock_session"
PBKDF2_ITERATIONS = 260_000
AUTH_OPTIONS = {"NONE", "EDIT", "VIEW"}

CATEGORIES = [
    "Meat",
    "Seafood",
    "Vegetables",
    "Fruit",
    "Prepared meal",
    "Baked goods",
    "Dessert",
    "Other",
]

DEFAULT_FREEZERS = [
    "Kitchen freezer",
    "Garage freezer",
    "Chest freezer",
]

DEFAULT_UNITS = [
    "item",
    "tub",
    "ml",
    "bag",
]

DEFAULT_ACCENT_COLOR = "#2f6f4f"
DEFAULT_DATE_FORMAT = "YYYY-MM-DD"
DEFAULT_APP_TITLE = "Freezer Stock"
DEFAULT_APP_EYEBROW = "SQLite freezer database"
DEFAULT_AUDIT_COLORS = {
    "Added": "#2f6f4f",
    "Updated": "#2f5d7c",
    "Removed": "#a53d36",
    "Stock adjusted": "#a4661b",
    "Buy listed": "#7b5ba7",
    "Buy cleared": "#657173",
    "Events archived": "#7b5ba7",
    "Stats reset": "#4b78a8",
    "User created": "#2f6f4f",
    "User updated": "#2f5d7c",
    "User deleted": "#a53d36",
}
SERVER_LOG_THEMES = {
    "midnight": ("Midnight", "#121716", "#e7eee9"),
    "terminal": ("Terminal Green", "#07130c", "#79f29a"),
    "ocean": ("Ocean Blue", "#071522", "#8fd3ff"),
    "controller": ("Controller", "#17131f", "#d8c7ff"),
    "matrix": ("Matrix", "#000000", "#00ff66"),
    "paper": ("Light Paper", "#f7f8f6", "#182023"),
    "soft-gray": ("Soft Gray", "#eef2f1", "#273133"),
    "solarized-dark": ("Solarized Dark", "#002b36", "#93a1a1"),
    "solarized-light": ("Solarized Light", "#fdf6e3", "#586e75"),
    "amber": ("Amber Console", "#1b1408", "#ffc766"),
}
DEFAULT_SERVER_LOG_PREFERENCES = {
    "history_length": 18,
    "background": SERVER_LOG_THEMES["midnight"][1],
    "text": SERVER_LOG_THEMES["midnight"][2],
    "theme": "midnight",
}
DATE_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD-MM-YYYY": "%d-%m-%Y",
    "MM-DD-YYYY": "%m-%d-%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_auth_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def read_config() -> dict[str, str]:
    defaults = {"AUTH_OPT": "NONE", "PORT": str(DEFAULT_PORT), "IP": DEFAULT_HOST}
    if not CONFIG_PATH.exists():
        write_config(defaults)
        return defaults.copy()
    config = defaults.copy()
    for raw_line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line or raw_line.strip().startswith("#"):
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in config:
            config[key] = value
    config["AUTH_OPT"] = config["AUTH_OPT"].upper()
    if config["AUTH_OPT"] not in AUTH_OPTIONS:
        config["AUTH_OPT"] = "NONE"
    try:
        port = int(config["PORT"])
        if port < 1 or port > 65535:
            raise ValueError
    except ValueError:
        config["PORT"] = str(DEFAULT_PORT)
    if not config["IP"]:
        config["IP"] = DEFAULT_HOST
    return config


def write_config(config: dict[str, str]) -> None:
    auth_opt = config.get("AUTH_OPT", "NONE").upper()
    if auth_opt not in AUTH_OPTIONS:
        auth_opt = "NONE"
    try:
        port = str(int(config.get("PORT", str(DEFAULT_PORT))))
    except ValueError:
        port = str(DEFAULT_PORT)
    ip = config.get("IP", DEFAULT_HOST) or DEFAULT_HOST
    CONFIG_PATH.write_text(
        f'AUTH_OPT="{auth_opt}"\nPORT="{port}"\nIP="{ip}"\n',
        encoding="utf-8",
    )


def load_server_config() -> dict[str, str]:
    global HOST, PORT
    config = read_config()
    HOST = config["IP"]
    PORT = int(config["PORT"])
    return config


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS freezers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                notes TEXT,
                batch_number INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS freezer_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Other',
                quantity REAL NOT NULL DEFAULT 1,
                unit TEXT NOT NULL DEFAULT 'item',
                location TEXT NOT NULL DEFAULT 'Kitchen freezer',
                freezer_id INTEGER,
                frozen_on TEXT NOT NULL,
                use_by TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (freezer_id) REFERENCES freezers(id) ON DELETE SET NULL
            )
            """
        )
        ensure_column(conn, "freezer_items", "freezer_id", "INTEGER")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS item_people (
                item_id INTEGER NOT NULL,
                person_id INTEGER NOT NULL,
                PRIMARY KEY (item_id, person_id),
                FOREIGN KEY (item_id) REFERENCES freezer_items(id) ON DELETE CASCADE,
                FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                item_name TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                device_name TEXT,
                username TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        ensure_column(conn, "audit_events", "ip_address", "TEXT")
        ensure_column(conn, "audit_events", "user_agent", "TEXT")
        ensure_column(conn, "audit_events", "device_name", "TEXT")
        ensure_column(conn, "audit_events", "username", "TEXT")
        ensure_column(conn, "freezer_items", "house_staple", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "freezer_items", "staple_threshold", "REAL NOT NULL DEFAULT 1")
        ensure_column(conn, "freezer_items", "buy_requested", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "freezer_items", "batch_number", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(conn, "freezer_items", "archived", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "freezer_items", "ingredient", "INTEGER NOT NULL DEFAULT 0")
        migrate_ingredient_people(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                item_name TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity_before REAL,
                quantity_after REAL,
                unit TEXT,
                delta REAL,
                ip_address TEXT,
                user_agent TEXT,
                device_name TEXT,
                username TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cpu_percent REAL NOT NULL,
                ram_percent REAL NOT NULL,
                disk_percent REAL NOT NULL,
                disk_io_bytes INTEGER NOT NULL DEFAULT 0,
                app_storage_bytes INTEGER NOT NULL DEFAULT 0,
                ram_bytes INTEGER NOT NULL DEFAULT 0,
                network_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        ensure_column(conn, "system_metrics", "disk_io_bytes", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "system_metrics", "app_storage_bytes", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "system_metrics", "ram_bytes", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "stock_events", "username", "TEXT")
        ensure_column(conn, "stock_events", "archive_batch", "TEXT")
        ensure_column(conn, "stock_events", "archived_at", "TEXT")
        ensure_column(conn, "stock_events", "archived_by", "TEXT")
        ensure_column(conn, "stock_events", "archived_ip", "TEXT")
        ensure_column(conn, "stock_events", "archived_device", "TEXT")
        conn.execute(
            "DELETE FROM stock_events WHERE archived_at IS NOT NULL AND datetime(archived_at) < datetime('now', '-90 days')"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_reset_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reset_at TEXT NOT NULL,
                reset_by TEXT,
                reset_ip TEXT,
                reset_device TEXT,
                snapshot_json TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                event_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "DELETE FROM stats_reset_history WHERE datetime(reset_at) < datetime('now', '-90 days')"
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("log_max_mb", str(DEFAULT_LOG_MAX_MB)),
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("accent_color", DEFAULT_ACCENT_COLOR),
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("date_format", DEFAULT_DATE_FORMAT),
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("app_title", DEFAULT_APP_TITLE),
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("app_eyebrow", DEFAULT_APP_EYEBROW),
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("audit_colors", json.dumps(DEFAULT_AUDIT_COLORS)),
        )
        for table in ("freezers", "people", "units", "categories", "freezer_items"):
            conn.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table}_updated_at
                AFTER UPDATE ON {table}
                BEGIN
                    UPDATE {table} SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
                END
                """
            )
        seed_and_migrate_freezers(conn)
        normalize_units(conn)
        seed_units(conn)
        seed_categories(conn)
        initialize_batch_numbers(conn)
        default_icon = ROOT / "freezer-icon.png"
        installed_icon = STATIC_DIR / "default_favicon.png"
        if default_icon.exists():
            if not installed_icon.exists() or installed_icon.read_bytes() != default_icon.read_bytes():
                installed_icon.write_bytes(default_icon.read_bytes())
            conn.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                ("favicon_path", "/static/default_favicon.png"),
            )


def init_auth_db() -> None:
    with get_auth_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webusers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('ADMIN', 'USER')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS web_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES webusers(id) ON DELETE CASCADE
            )
            """
        )
        ensure_column(conn, "web_sessions", "last_ip", "TEXT")
        ensure_column(conn, "web_sessions", "user_agent", "TEXT")
        ensure_column(conn, "webusers", "must_change_password", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webuser_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (user_id, key),
                FOREIGN KEY (user_id) REFERENCES webusers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS webusers_updated_at
            AFTER UPDATE ON webusers
            BEGIN
                UPDATE webusers SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
            """
        )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migrate_ingredient_people(conn: sqlite3.Connection) -> None:
    ingredient_people = list(
        conn.execute(
            "SELECT id FROM people WHERE LOWER(TRIM(name)) IN ('ingredient', 'ingredients')"
        )
    )
    for person in ingredient_people:
        conn.execute(
            """
            UPDATE freezer_items
            SET ingredient = 1
            WHERE id IN (
                SELECT item_id
                FROM item_people
                WHERE person_id = ?
            )
            """,
            (person["id"],),
        )
        conn.execute("DELETE FROM item_people WHERE person_id = ?", (person["id"],))
        conn.execute("DELETE FROM people WHERE id = ?", (person["id"],))


def seed_and_migrate_freezers(conn: sqlite3.Connection) -> None:
    freezer_count = conn.execute("SELECT COUNT(*) AS count FROM freezers").fetchone()["count"]
    if freezer_count == 0:
        for name in DEFAULT_FREEZERS:
            conn.execute("INSERT INTO freezers (name) VALUES (?)", (name,))

    locations = [
        row["location"]
        for row in conn.execute(
            """
            SELECT DISTINCT location
            FROM freezer_items
            WHERE freezer_id IS NULL
                AND location IS NOT NULL
                AND TRIM(location) != ''
                AND location != 'Unassigned'
            """
        )
    ]
    for location in locations:
        conn.execute("INSERT OR IGNORE INTO freezers (name) VALUES (?)", (location,))

    conn.execute(
        """
        UPDATE freezer_items
        SET freezer_id = (
            SELECT freezers.id FROM freezers WHERE freezers.name = freezer_items.location
        )
        WHERE freezer_id IS NULL
        """
    )


def seed_units(conn: sqlite3.Connection) -> None:
    unit_count = conn.execute("SELECT COUNT(*) AS count FROM units").fetchone()["count"]
    if unit_count == 0:
        for unit in DEFAULT_UNITS:
            conn.execute("INSERT INTO units (name) VALUES (?)", (unit,))


def normalize_units(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE freezer_items SET unit = LOWER(TRIM(unit)) WHERE unit IS NOT NULL")
    conn.execute("UPDATE stock_events SET unit = LOWER(TRIM(unit)) WHERE unit IS NOT NULL")
    rows = list(conn.execute("SELECT id, name, notes FROM units ORDER BY id"))
    canonical: dict[str, sqlite3.Row] = {}
    for row in rows:
        normalized = row["name"].strip().lower()
        if not normalized:
            conn.execute("DELETE FROM units WHERE id = ?", (row["id"],))
            continue
        existing = canonical.get(normalized)
        if existing:
            if not existing["notes"] and row["notes"]:
                conn.execute("UPDATE units SET notes = ? WHERE id = ?", (row["notes"], existing["id"]))
            conn.execute("DELETE FROM units WHERE id = ?", (row["id"],))
            continue
        canonical[normalized] = row
        if row["name"] != normalized:
            conn.execute("UPDATE units SET name = ? WHERE id = ?", (normalized, row["id"]))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS units_name_nocase ON units(name COLLATE NOCASE)")


def seed_categories(conn: sqlite3.Connection) -> None:
    category_count = conn.execute("SELECT COUNT(*) AS count FROM categories").fetchone()["count"]
    if category_count == 0:
        for category in CATEGORIES:
            conn.execute("INSERT INTO categories (name) VALUES (?)", (category,))
    for row in conn.execute(
        "SELECT DISTINCT category FROM freezer_items WHERE category IS NOT NULL AND TRIM(category) != ''"
    ):
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (row["category"],))


def initialize_batch_numbers(conn: sqlite3.Connection) -> None:
    initialized = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        ("batch_numbers_initialized",),
    ).fetchone()
    if initialized:
        return
    conn.execute(
        """
        WITH numbered AS (
            SELECT id,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(TRIM(name))
                    ORDER BY date(frozen_on), date(use_by), id
                ) AS number
            FROM freezer_items
        )
        UPDATE freezer_items
        SET batch_number = (
            SELECT number FROM numbered WHERE numbered.id = freezer_items.id
        )
        """
    )
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)",
        ("batch_numbers_initialized", "1"),
    )


def normalize_role(role: str) -> str:
    role = role.strip().upper()
    return role if role in ("ADMIN", "USER") else "USER"


def generate_password() -> str:
    consonants = "bcdfghjkmnprstvwxyz"
    vowels = "aeiou"
    readable = "".join(
        secrets.choice(consonants if index % 2 == 0 else vowels)
        for index in range(8)
    ).capitalize()
    return f"{readable}{secrets.randbelow(90) + 10}"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, raw_iterations, raw_salt, raw_digest = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        salt = base64.b64decode(raw_salt)
        expected = base64.b64decode(raw_digest)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def create_webuser(role: str, username: str, password: str | None = None) -> tuple[list[str], str | None]:
    username = username.strip()
    role = normalize_role(role)
    generated_password = None
    errors: list[str] = []
    if not username:
        return ["Username is required."], None
    if not password:
        password = generate_password()
        generated_password = password
    try:
        with get_auth_connection() as conn:
            conn.execute(
                "INSERT INTO webusers (username, password_hash, role) VALUES (?, ?, ?)",
                (username, hash_password(password), role),
            )
    except sqlite3.IntegrityError:
        errors.append("A webuser with that username already exists.")
    return errors, generated_password


def update_webuser(user_id: int, role: str, username: str, password: str | None = None) -> tuple[list[str], str | None]:
    username = username.strip()
    role = normalize_role(role)
    generated_password = None
    if not username:
        return ["Username is required."], None
    try:
        with get_auth_connection() as conn:
            if password == "__generate__":
                password = generate_password()
                generated_password = password
            if password:
                conn.execute(
                    "UPDATE webusers SET username = ?, role = ?, password_hash = ? WHERE id = ?",
                    (username, role, hash_password(password), user_id),
                )
            else:
                conn.execute(
                    "UPDATE webusers SET username = ?, role = ? WHERE id = ?",
                    (username, role, user_id),
                )
    except sqlite3.IntegrityError:
        return ["A webuser with that username already exists."], None
    return [], generated_password


def delete_webuser(user_id: int) -> None:
    with get_auth_connection() as conn:
        conn.execute("DELETE FROM webusers WHERE id = ?", (user_id,))


def fetch_webusers() -> list[sqlite3.Row]:
    with get_auth_connection() as conn:
        return list(conn.execute("SELECT id, username, role, must_change_password, created_at, updated_at FROM webusers ORDER BY username COLLATE NOCASE"))


def fetch_webuser(user_id: int) -> sqlite3.Row | None:
    with get_auth_connection() as conn:
        return conn.execute("SELECT id, username, role, must_change_password FROM webusers WHERE id = ?", (user_id,)).fetchone()


def authenticate_user(username: str, password: str) -> sqlite3.Row | None:
    with get_auth_connection() as conn:
        user = conn.execute("SELECT * FROM webusers WHERE username = ?", (username.strip(),)).fetchone()
        if user and verify_password(password, user["password_hash"]):
            return user
    return None


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with get_auth_connection() as conn:
        conn.execute("INSERT INTO web_sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    return token


def delete_session(token: str) -> None:
    if token:
        with get_auth_connection() as conn:
            conn.execute("DELETE FROM web_sessions WHERE token = ?", (token,))


def session_user(token: str, ip_address: str = "", user_agent: str = "") -> sqlite3.Row | None:
    if not token:
        return None
    with get_auth_connection() as conn:
        row = conn.execute(
            """
            SELECT webusers.id, webusers.username, webusers.role, webusers.must_change_password
            FROM web_sessions
            JOIN webusers ON webusers.id = web_sessions.user_id
            WHERE web_sessions.token = ?
            """,
            (token,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE web_sessions SET last_seen_at = CURRENT_TIMESTAMP, last_ip = ?, user_agent = ? WHERE token = ?",
                (ip_address, user_agent[:240], token),
            )
        return row


def fetch_active_sessions() -> list[sqlite3.Row]:
    with get_auth_connection() as conn:
        return list(
            conn.execute(
                f"""
                SELECT webusers.id AS user_id, webusers.username, webusers.role,
                    web_sessions.last_ip, MAX(web_sessions.last_seen_at) AS last_seen_at,
                    COUNT(*) AS session_count
                FROM web_sessions
                JOIN webusers ON webusers.id = web_sessions.user_id
                WHERE datetime(web_sessions.last_seen_at) >= datetime('now', '-15 minutes')
                GROUP BY webusers.id, web_sessions.last_ip
                ORDER BY datetime(last_seen_at) DESC
                """
            )
        )


def get_user_setting(user_id: int, key: str, default: str) -> str:
    with get_auth_connection() as conn:
        row = conn.execute(
            "SELECT value FROM webuser_settings WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
    return row["value"] if row else default


def set_user_setting(user_id: int, key: str, value: str) -> None:
    with get_auth_connection() as conn:
        conn.execute(
            """
            INSERT INTO webuser_settings (user_id, key, value) VALUES (?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
            """,
            (user_id, key, value),
        )


def user_palette(user_id: int) -> dict[str, str]:
    defaults = {
        "accent": get_setting("accent_color", DEFAULT_ACCENT_COLOR),
        "info": get_setting("info_color", "#2f5d7c"),
        "warning": get_setting("warning_color", "#a4661b"),
        "danger": get_setting("danger_color", "#a53d36"),
    }
    try:
        saved = json.loads(get_user_setting(user_id, "palette", "{}"))
    except json.JSONDecodeError:
        saved = {}
    return {
        key: normalize_hex_color(str(saved.get(key, default))) or default
        for key, default in defaults.items()
    }


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def icon(name: str, label: str = "") -> str:
    return f'<img class="ui-icon" src="/static/icon-{esc(name)}.svg" alt="{esc(label)}">'


def today_iso() -> str:
    return date.today().isoformat()


def next_year_iso() -> str:
    return (date.today() + timedelta(days=365)).isoformat()


def parse_form(body: bytes) -> dict[str, str]:
    values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: vals[0].strip() for key, vals in values.items()}


def parse_form_multi(body: bytes) -> dict[str, list[str]]:
    return {
        key: [value.strip() for value in vals if value.strip()]
        for key, vals in parse_qs(body.decode("utf-8"), keep_blank_values=True).items()
    }


def scalar_values(values: dict[str, list[str]]) -> dict[str, str]:
    return {key: vals[0] if vals else "" for key, vals in values.items()}


def int_or_none(value: str | None) -> int | None:
    try:
        return int(value or "")
    except ValueError:
        return None


def selected_people_from_form(values: dict[str, list[str]]) -> list[int]:
    ids: list[int] = []
    for raw in values.get("person_ids", []):
        person_id = int_or_none(raw)
        if person_id is not None:
            ids.append(person_id)
    return ids


def fetch_freezers() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(conn.execute("SELECT * FROM freezers ORDER BY name COLLATE NOCASE"))


def fetch_people() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(conn.execute("SELECT * FROM people ORDER BY name COLLATE NOCASE"))


def fetch_people_with_stats() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                """
                SELECT people.*,
                    COUNT(DISTINCT freezer_items.id) AS food_count,
                    COALESCE(SUM(freezer_items.quantity), 0) AS total_quantity
                FROM people
                LEFT JOIN item_people ON item_people.person_id = people.id
                LEFT JOIN freezer_items ON freezer_items.id = item_people.item_id
                GROUP BY people.id
                ORDER BY people.name COLLATE NOCASE
                """
            )
        )


def fetch_units() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(conn.execute("SELECT * FROM units ORDER BY name COLLATE NOCASE"))


def fetch_categories() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(conn.execute("SELECT * FROM categories ORDER BY name COLLATE NOCASE"))


def fetch_person_ids() -> set[int]:
    return {row["id"] for row in fetch_people()}


def fetch_freezer(freezer_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM freezers WHERE id = ?", (freezer_id,)).fetchone()


def fetch_person(person_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()


def fetch_unit(unit_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()


def fetch_category(category_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()


def next_batch_number(name: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(batch_number), 0) + 1 AS next_number
            FROM freezer_items
            WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))
            """,
            (name,),
        ).fetchone()
    return int(row["next_number"]) if row else 1


def fetch_food_suggestions(search: str) -> list[dict[str, object]]:
    search = search.strip()
    if not search:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT freezer_items.*,
                    COALESCE(freezers.name, freezer_items.location, 'Unassigned') AS freezer_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY LOWER(TRIM(freezer_items.name))
                        ORDER BY freezer_items.batch_number DESC, freezer_items.id DESC
                    ) AS rank
                FROM freezer_items
                LEFT JOIN freezers ON freezers.id = freezer_items.freezer_id
                WHERE freezer_items.name LIKE ? COLLATE NOCASE
            )
            SELECT id, name, category, unit, freezer_name, batch_number, use_by, ingredient
            FROM ranked
            WHERE rank = 1
            ORDER BY
                CASE WHEN LOWER(name) LIKE LOWER(?) THEN 0 ELSE 1 END,
                name COLLATE NOCASE
            LIMIT 8
            """,
            (f"%{search}%", f"{search}%"),
        ).fetchall()
        suggestions = [dict(row) for row in rows]
        known_names = {str(row["name"]).strip().lower() for row in rows}
        archived_events = conn.execute(
            """
            SELECT item_name, details
            FROM audit_events
            WHERE action = 'Removed'
                AND item_name LIKE ? COLLATE NOCASE
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 30
            """,
            (f"%{search}%",),
        ).fetchall()
    for event in archived_events:
        normalized = str(event["item_name"]).strip().lower()
        if normalized in known_names:
            continue
        details = str(event["details"] or "")
        match = re.search(
            r" batch (\d+): [\d.]+ (.*?), (.*?), (.*?), people: (.*?), use by: (.*?)(?:, ingredient: (yes|no))?$",
            details,
        )
        suggestions.append(
            {
                "id": None,
                "name": event["item_name"],
                "category": match.group(3) if match else "Other",
                "unit": match.group(2).lower() if match else "item",
                "freezer_name": match.group(4) if match else "Unassigned",
                "people_names": match.group(5) if match else "",
                "batch_number": int(match.group(1)) if match else 1,
                "use_by": match.group(6) if match and match.group(6) != "Not set" else "",
                "ingredient": 1 if match and match.group(7) == "yes" else 0,
            }
        )
        known_names.add(normalized)
        if len(suggestions) >= 8:
            break
    return suggestions[:8]


def predict_food_defaults(name: str) -> dict[str, str]:
    text = name.strip().lower()
    rules = [
        (("ice cream", "gelato", "sorbet"), "Dessert", "tub"),
        (("pizza", "pie", "meal", "lasagne", "lasagna", "soup", "curry"), "Prepared meal", "item"),
        (("chicken", "beef", "pork", "lamb", "sausage", "bacon", "steak", "mince"), "Meat", "bag"),
        (("fish", "salmon", "tuna", "prawn", "shrimp", "seafood"), "Seafood", "bag"),
        (("bread", "bun", "roll", "croissant", "muffin", "cake"), "Baked goods", "bag"),
        (("berry", "berries", "apple", "banana", "mango", "fruit"), "Fruit", "bag"),
        (("corn", "pea", "bean", "broccoli", "carrot", "vegetable", "chips", "fries"), "Vegetables", "bag"),
        (("milk", "stock", "juice", "sauce"), "Other", "ml"),
    ]
    for keywords, category, unit in rules:
        if any(keyword in text for keyword in keywords):
            return {"category": category, "unit": unit}
    return {"category": "Other", "unit": "item"}


def validate_item(form: dict[str, str], person_ids: list[int]) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    name = form.get("name", "")
    unit = (form.get("unit_custom") or form.get("unit") or "").lower()
    quantity_raw = form.get("quantity", "1")
    threshold_raw = form.get("staple_threshold", "1")
    frozen_on = form.get("frozen_on", today_iso())
    use_by = form.get("use_by", next_year_iso())
    freezer_id = int_or_none(form.get("freezer_id"))
    house_staple = 1 if form.get("house_staple") == "on" else 0
    ingredient = 1 if form.get("ingredient") == "on" else 0
    batch_number = int_or_none(form.get("batch_number")) or 1
    if batch_number < 1:
        batch_number = 1

    if not name:
        errors.append("Name is required.")

    try:
        quantity = float(quantity_raw)
        if quantity <= 0:
            errors.append("Quantity must be greater than zero.")
    except ValueError:
        quantity = 1.0
        errors.append("Quantity must be a number.")

    try:
        staple_threshold = float(threshold_raw)
        if staple_threshold < 0:
            errors.append("Staple threshold cannot be negative.")
    except ValueError:
        staple_threshold = 1.0
        errors.append("Staple threshold must be a number.")

    for label, value in (("Frozen on", frozen_on), ("Use by", use_by)):
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                errors.append(f"{label} must be a valid date.")

    if not unit:
        errors.append("Unit is required.")

    freezer_name = ""
    if freezer_id:
        freezer = fetch_freezer(freezer_id)
        if freezer:
            freezer_name = freezer["name"]
        else:
            errors.append("Selected freezer does not exist.")

    known_person_ids = fetch_person_ids()
    unknown_people = [person_id for person_id in person_ids if person_id not in known_person_ids]
    if unknown_people:
        errors.append("One or more selected people no longer exist.")

    category = (form.get("category_custom") or form.get("category") or "Other").strip()
    item = {
        "name": name,
        "category": category,
        "quantity": quantity,
        "unit": unit,
        "freezer_id": freezer_id,
        "location": freezer_name or "Unassigned",
        "frozen_on": frozen_on or today_iso(),
        "use_by": use_by or next_year_iso(),
        "notes": form.get("notes", ""),
        "batch_number": batch_number,
        "house_staple": house_staple,
        "ingredient": ingredient,
        "staple_threshold": staple_threshold,
        "buy_requested": 0 if house_staple else int(form.get("buy_requested", "0") or 0),
        "person_ids": sorted(set(person_ids)),
    }
    return item, errors


def filter_values(filters: dict[str, object], key: str) -> list[str]:
    value = filters.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if value else []


def filter_scalar(filters: dict[str, object], key: str) -> str:
    values = filter_values(filters, key)
    return values[0] if values else ""


def fetch_items(filters: dict[str, object]) -> list[sqlite3.Row]:
    query = """
        SELECT freezer_items.*,
            COALESCE(freezers.name, freezer_items.location, 'Unassigned') AS freezer_name,
            GROUP_CONCAT(people.name, ', ') AS people_names,
            CASE
                WHEN use_by IS NULL OR use_by = '' THEN 99999
                ELSE CAST(julianday(use_by) - julianday('now') AS INTEGER)
            END AS days_left
        FROM freezer_items
        LEFT JOIN freezers ON freezers.id = freezer_items.freezer_id
        LEFT JOIN item_people ON item_people.item_id = freezer_items.id
        LEFT JOIN people ON people.id = item_people.person_id
        WHERE freezer_items.quantity > 0
    """
    params: list[object] = []

    search = filter_scalar(filters, "q")
    if search:
        ingredient_search = search.strip().lower() in ("ingredient", "ingredients")
        query += " AND (freezer_items.name LIKE ? OR freezer_items.notes LIKE ?"
        if ingredient_search:
            query += " OR freezer_items.ingredient = 1"
        query += ")"
        like = f"%{search}%"
        params.extend([like, like])

    categories = filter_values(filters, "category")
    if categories:
        query += f" AND freezer_items.category IN ({','.join('?' for _ in categories)})"
        params.extend(categories)

    ingredient_values = filter_values(filters, "ingredient")
    if ingredient_values:
        ingredient_clauses = []
        if "yes" in ingredient_values:
            ingredient_clauses.append("freezer_items.ingredient = 1")
        if "no" in ingredient_values:
            ingredient_clauses.append("freezer_items.ingredient = 0")
        if ingredient_clauses:
            query += f" AND ({' OR '.join(ingredient_clauses)})"

    freezer_ids = filter_values(filters, "freezer_id")
    if freezer_ids:
        include_unassigned = "unassigned" in freezer_ids
        numeric_freezers = [value for value in freezer_ids if value != "unassigned"]
        clauses = []
        if numeric_freezers:
            clauses.append(f"freezer_items.freezer_id IN ({','.join('?' for _ in numeric_freezers)})")
            params.extend(numeric_freezers)
        if include_unassigned:
            clauses.append("freezer_items.freezer_id IS NULL")
        query += f" AND ({' OR '.join(clauses)})"

    person_ids = filter_values(filters, "person_id")
    if person_ids:
        placeholders = ",".join("?" for _ in person_ids)
        if filter_scalar(filters, "person_match") == "all":
            query += f"""
                AND (
                    SELECT COUNT(DISTINCT ip.person_id)
                    FROM item_people ip
                    WHERE ip.item_id = freezer_items.id
                        AND ip.person_id IN ({placeholders})
                ) = ?
            """
        else:
            query += f"""
                AND EXISTS (
                    SELECT 1 FROM item_people ip
                    WHERE ip.item_id = freezer_items.id
                        AND ip.person_id IN ({placeholders})
                )
            """
        params.extend(person_ids)
        if filter_scalar(filters, "person_match") == "all":
            params.append(len(set(person_ids)))

    query += """
        GROUP BY freezer_items.id
        ORDER BY
            freezer_items.name COLLATE NOCASE,
            freezer_items.batch_number ASC,
            date(freezer_items.frozen_on) ASC,
            freezer_items.id ASC
    """

    with get_connection() as conn:
        return list(conn.execute(query, params))


def fetch_item(item_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT freezer_items.*,
                COALESCE(freezers.name, freezer_items.location, 'Unassigned') AS freezer_name
            FROM freezer_items
            LEFT JOIN freezers ON freezers.id = freezer_items.freezer_id
            WHERE freezer_items.id = ?
            """,
            (item_id,),
        ).fetchone()


def fetch_item_people(item_id: int) -> list[int]:
    with get_connection() as conn:
        return [
            row["person_id"]
            for row in conn.execute("SELECT person_id FROM item_people WHERE item_id = ?", (item_id,))
        ]


def item_snapshot(conn: sqlite3.Connection, item_id: int) -> str:
    row = conn.execute(
        """
        SELECT freezer_items.*,
            COALESCE(freezers.name, freezer_items.location, 'Unassigned') AS freezer_name,
            GROUP_CONCAT(people.name, ', ') AS people_names
        FROM freezer_items
        LEFT JOIN freezers ON freezers.id = freezer_items.freezer_id
        LEFT JOIN item_people ON item_people.item_id = freezer_items.id
        LEFT JOIN people ON people.id = item_people.person_id
        WHERE freezer_items.id = ?
        GROUP BY freezer_items.id
        """,
        (item_id,),
    ).fetchone()
    if not row:
        return ""
    people = row["people_names"] or "No one"
    use_by = row["use_by"] or "Not set"
    return (
        f'{row["name"]} batch {row["batch_number"]}: {float(row["quantity"]):g} {row["unit"]}, '
        f'{row["category"]}, {row["freezer_name"]}, people: {people}, use by: {use_by}, '
        f'ingredient: {"yes" if row["ingredient"] else "no"}'
    )


def log_audit(
    conn: sqlite3.Connection,
    action: str,
    item_id: int | None,
    item_name: str,
    details: str,
    actor: dict[str, str] | None = None,
) -> None:
    actor = actor or {}
    conn.execute(
        """
        INSERT INTO audit_events
            (item_id, item_name, action, details, ip_address, user_agent, device_name, username)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            item_name,
            action,
            details,
            actor.get("ip_address", ""),
            actor.get("user_agent", ""),
            actor.get("device_name", ""),
            actor.get("username", ""),
        ),
    )


def log_user_audit(
    action: str,
    username: str,
    details: str,
    actor: dict[str, str] | None = None,
) -> None:
    with get_connection() as conn:
        log_audit(conn, action, None, f"Webuser: {username}", details, actor)


def log_stock_event(
    conn: sqlite3.Connection,
    item_id: int | None,
    item_name: str,
    action: str,
    before: float | None,
    after: float | None,
    unit: str,
    delta: float | None,
    actor: dict[str, str] | None = None,
) -> None:
    actor = actor or {}
    conn.execute(
        """
        INSERT INTO stock_events
            (item_id, item_name, action, quantity_before, quantity_after, unit, delta, ip_address, user_agent, device_name, username)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            item_name,
            action,
            before,
            after,
            unit,
            delta,
            actor.get("ip_address", ""),
            actor.get("user_agent", ""),
            actor.get("device_name", ""),
            actor.get("username", ""),
        ),
    )


def insert_item(item: dict[str, object], actor: dict[str, str] | None = None) -> None:
    person_ids = item.pop("person_ids", [])
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO freezer_items
                (name, category, quantity, unit, location, freezer_id, frozen_on, use_by, notes, batch_number, house_staple, ingredient, staple_threshold, buy_requested)
            VALUES
                (:name, :category, :quantity, :unit, :location, :freezer_id, :frozen_on, :use_by, :notes, :batch_number, :house_staple, :ingredient, :staple_threshold, :buy_requested)
            """,
            item,
        )
        set_item_people(conn, cursor.lastrowid, person_ids)  # type: ignore[arg-type]
        ensure_unit(conn, item["unit"])
        ensure_category(conn, item["category"])
        log_audit(conn, "Added", cursor.lastrowid, str(item["name"]), item_snapshot(conn, cursor.lastrowid), actor)
        log_stock_event(conn, cursor.lastrowid, str(item["name"]), "Added", None, float(item["quantity"]), str(item["unit"]), float(item["quantity"]), actor)


def update_item(item_id: int, item: dict[str, object], actor: dict[str, str] | None = None) -> None:
    person_ids = item.pop("person_ids", [])
    with get_connection() as conn:
        before = item_snapshot(conn, item_id)
        conn.execute(
            """
            UPDATE freezer_items
            SET name = :name,
                category = :category,
                quantity = :quantity,
                unit = :unit,
                location = :location,
                freezer_id = :freezer_id,
                frozen_on = :frozen_on,
                use_by = :use_by,
                notes = :notes,
                batch_number = :batch_number,
                house_staple = :house_staple,
                ingredient = :ingredient,
                staple_threshold = :staple_threshold,
                buy_requested = :buy_requested
            WHERE id = :id
            """,
            {**item, "id": item_id},
        )
        set_item_people(conn, item_id, person_ids)  # type: ignore[arg-type]
        ensure_unit(conn, item["unit"])
        ensure_category(conn, item["category"])
        after = item_snapshot(conn, item_id)
        log_audit(conn, "Updated", item_id, str(item["name"]), f"Before: {before}\nAfter: {after}", actor)
        log_stock_event(conn, item_id, str(item["name"]), "Updated", None, float(item["quantity"]), str(item["unit"]), None, actor)


def set_item_people(conn: sqlite3.Connection, item_id: int, person_ids: list[int]) -> None:
    conn.execute("DELETE FROM item_people WHERE item_id = ?", (item_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO item_people (item_id, person_id) VALUES (?, ?)",
        [(item_id, person_id) for person_id in sorted(set(person_ids))],
    )


def ensure_unit(conn: sqlite3.Connection, unit: object) -> None:
    unit_name = str(unit).strip().lower()
    if unit_name:
        conn.execute("INSERT OR IGNORE INTO units (name) VALUES (?)", (unit_name,))


def ensure_category(conn: sqlite3.Connection, category: object) -> None:
    category_name = str(category).strip()
    if category_name:
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category_name,))


def delete_item(item_id: int, actor: dict[str, str] | None = None) -> None:
    with get_connection() as conn:
        existing = conn.execute("SELECT name, quantity, unit FROM freezer_items WHERE id = ?", (item_id,)).fetchone()
        snapshot = item_snapshot(conn, item_id)
        conn.execute(
            "UPDATE freezer_items SET quantity = 0, archived = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (item_id,),
        )
        if existing:
            log_audit(conn, "Removed", item_id, existing["name"], snapshot, actor)
            log_stock_event(conn, item_id, existing["name"], "Removed", float(existing["quantity"]), 0, existing["unit"], -float(existing["quantity"]), actor)


def adjust_stock(item_id: int, amount: float, direction: str, actor: dict[str, str] | None = None) -> dict[str, object]:
    if amount <= 0:
        return {"ok": False}
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, quantity, unit, house_staple, buy_requested FROM freezer_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return {"ok": False}
        before = float(row["quantity"])
        delta = amount if direction == "add" else -amount
        after = before + delta
        ask_buy = direction == "remove" and after == 1 and not row["house_staple"] and not row["buy_requested"]
        if after <= 0:
            snapshot = item_snapshot(conn, item_id)
            conn.execute("UPDATE freezer_items SET quantity = 0 WHERE id = ?", (item_id,))
            log_audit(
                conn,
                "Removed",
                item_id,
                row["name"],
                f"Stock reduced by {amount:g} {row['unit']} from {before:g}; batch depleted and retained as a reusable template.\n{snapshot}",
                actor,
            )
            log_stock_event(conn, item_id, row["name"], "Removed", before, 0, row["unit"], -before, actor)
            return {"ok": True, "ask_buy": False, "quantity": 0}
        conn.execute("UPDATE freezer_items SET quantity = ? WHERE id = ?", (after, item_id))
        log_audit(
            conn,
            "Stock adjusted",
            item_id,
            row["name"],
            f"{'Added' if direction == 'add' else 'Removed'} {amount:g} {row['unit']}; {before:g} -> {after:g}.",
            actor,
        )
        log_stock_event(conn, item_id, row["name"], "Stock adjusted", before, after, row["unit"], delta, actor)
        return {"ok": True, "ask_buy": ask_buy, "quantity": after, "item_id": item_id, "item_name": row["name"]}


def save_freezer(form: dict[str, str], freezer_id: int | None = None) -> list[str]:
    name = form.get("name", "").strip()
    notes = form.get("notes", "").strip()
    errors = []
    if not name:
        errors.append("Freezer name is required.")
        return errors
    try:
        with get_connection() as conn:
            if freezer_id:
                conn.execute("UPDATE freezers SET name = ?, notes = ? WHERE id = ?", (name, notes, freezer_id))
                conn.execute(
                    """
                    UPDATE freezer_items
                    SET location = ?
                    WHERE freezer_id = ?
                    """,
                    (name, freezer_id),
                )
            else:
                conn.execute("INSERT INTO freezers (name, notes) VALUES (?, ?)", (name, notes))
    except sqlite3.IntegrityError:
        errors.append("A freezer with that name already exists.")
    return errors


def save_person(form: dict[str, str], person_id: int | None = None) -> list[str]:
    name = form.get("name", "").strip()
    notes = form.get("notes", "").strip()
    errors = []
    if not name:
        errors.append("Person name is required.")
        return errors
    try:
        with get_connection() as conn:
            if person_id:
                conn.execute("UPDATE people SET name = ?, notes = ? WHERE id = ?", (name, notes, person_id))
            else:
                conn.execute("INSERT INTO people (name, notes) VALUES (?, ?)", (name, notes))
    except sqlite3.IntegrityError:
        errors.append("A person with that name already exists.")
    return errors


def save_unit(form: dict[str, str], unit_id: int | None = None) -> list[str]:
    name = form.get("name", "").strip().lower()
    notes = form.get("notes", "")
    errors = []
    if not name:
        errors.append("Unit name is required.")
        return errors
    try:
        with get_connection() as conn:
            if unit_id:
                old = conn.execute("SELECT name FROM units WHERE id = ?", (unit_id,)).fetchone()
                duplicate = conn.execute(
                    "SELECT id, name FROM units WHERE name = ? COLLATE NOCASE AND id != ?",
                    (name, unit_id),
                ).fetchone()
                if duplicate:
                    if old:
                        conn.execute(
                            "UPDATE freezer_items SET unit = ? WHERE unit = ? COLLATE NOCASE",
                            (duplicate["name"], old["name"]),
                        )
                        conn.execute(
                            "UPDATE stock_events SET unit = ? WHERE unit = ? COLLATE NOCASE",
                            (duplicate["name"], old["name"]),
                        )
                    conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))
                    return []
                conn.execute("UPDATE units SET name = ?, notes = ? WHERE id = ?", (name, notes, unit_id))
                if old:
                    conn.execute("UPDATE freezer_items SET unit = ? WHERE unit = ? COLLATE NOCASE", (name, old["name"]))
                    conn.execute("UPDATE stock_events SET unit = ? WHERE unit = ? COLLATE NOCASE", (name, old["name"]))
            else:
                conn.execute("INSERT INTO units (name, notes) VALUES (?, ?)", (name, notes))
    except sqlite3.IntegrityError:
        errors.append("A unit with that name already exists.")
    return errors


def save_category(form: dict[str, str], category_id: int | None = None) -> list[str]:
    name = form.get("name", "").strip()
    notes = form.get("notes", "")
    errors = []
    if not name:
        return ["Category name is required."]
    try:
        with get_connection() as conn:
            if category_id:
                old = conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
                conn.execute("UPDATE categories SET name = ?, notes = ? WHERE id = ?", (name, notes, category_id))
                if old:
                    conn.execute("UPDATE freezer_items SET category = ? WHERE category = ?", (name, old["name"]))
            else:
                conn.execute("INSERT INTO categories (name, notes) VALUES (?, ?)", (name, notes))
    except sqlite3.IntegrityError:
        errors.append("A category with that name already exists.")
    return errors


def quick_add(kind: str, form: dict[str, str]) -> tuple[dict[str, object] | None, list[str]]:
    handlers = {
        "freezer": (save_freezer, "freezers"),
        "person": (save_person, "people"),
        "unit": (save_unit, "units"),
        "category": (save_category, "categories"),
    }
    if kind not in handlers:
        return None, ["Unknown item type."]
    handler, table = handlers[kind]
    raw_name = form.get("name", "").strip()
    lookup_name = raw_name.lower() if kind == "unit" else raw_name
    if lookup_name:
        with get_connection() as conn:
            existing = conn.execute(
                f"SELECT id, name, notes FROM {table} WHERE name = ? COLLATE NOCASE",
                (lookup_name,),
            ).fetchone()
        if existing:
            return dict(existing), []
    errors = handler(form)
    if errors:
        return None, errors
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT id, name, notes FROM {table} WHERE name = ? COLLATE NOCASE",
            (lookup_name,),
        ).fetchone()
    return (dict(row) if row else None), ([] if row else ["The new entry could not be loaded."])


def delete_freezer(freezer_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE freezer_items SET freezer_id = NULL, location = 'Unassigned' WHERE freezer_id = ?", (freezer_id,))
        conn.execute("DELETE FROM freezers WHERE id = ?", (freezer_id,))


def delete_person(person_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM people WHERE id = ?", (person_id,))


def delete_unit(unit_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))


def delete_category(category_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def mark_buy_requested(item_id: int, actor: dict[str, str] | None = None) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT id, name FROM freezer_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return
        conn.execute("UPDATE freezer_items SET buy_requested = 1 WHERE id = ?", (item_id,))
        log_audit(conn, "Buy listed", item_id, row["name"], "Added to Buy list.", actor)


def clear_buy_requested(item_id: int, actor: dict[str, str] | None = None) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT id, name FROM freezer_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return
        conn.execute("UPDATE freezer_items SET buy_requested = 0 WHERE id = ?", (item_id,))
        log_audit(conn, "Buy cleared", item_id, row["name"], "Removed from Buy list.", actor)


def fetch_buy_items() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                f"""
                SELECT freezer_items.*,
                    COALESCE(freezers.name, freezer_items.location, 'Unassigned') AS freezer_name,
                    GROUP_CONCAT(people.name, ', ') AS people_names,
                    CASE
                        WHEN house_staple = 1 AND quantity < staple_threshold THEN 'Low staple'
                        WHEN buy_requested = 1 THEN 'Requested'
                        ELSE 'Ready'
                    END AS buy_reason
                FROM freezer_items
                LEFT JOIN freezers ON freezers.id = freezer_items.freezer_id
                LEFT JOIN item_people ON item_people.item_id = freezer_items.id
                LEFT JOIN people ON people.id = item_people.person_id
                WHERE quantity > 0
                    AND (buy_requested = 1 OR (house_staple = 1 AND quantity < staple_threshold))
                GROUP BY freezer_items.id
                ORDER BY buy_reason, freezer_items.name COLLATE NOCASE
                """
            )
        )


def normalize_hex_color(value: str) -> str | None:
    value = value.strip()
    if not value.startswith("#"):
        value = f"#{value}"
    if len(value) != 7:
        return None
    if all(char in "0123456789abcdefABCDEF" for char in value[1:]):
        return value.lower()
    return None


def server_log_preferences(user: sqlite3.Row | None = None) -> dict[str, object]:
    default_json = json.dumps(DEFAULT_SERVER_LOG_PREFERENCES)
    raw = (
        get_user_setting(user["id"], "server_log_preferences", default_json)
        if user
        else get_setting("server_log_preferences", default_json)
    )
    try:
        saved = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        saved = {}
    try:
        history_length = int(saved.get("history_length", DEFAULT_SERVER_LOG_PREFERENCES["history_length"]))
    except (TypeError, ValueError):
        history_length = int(DEFAULT_SERVER_LOG_PREFERENCES["history_length"])
    theme = str(saved.get("theme", DEFAULT_SERVER_LOG_PREFERENCES["theme"]))
    if theme not in SERVER_LOG_THEMES and theme != "custom":
        theme = str(DEFAULT_SERVER_LOG_PREFERENCES["theme"])
    return {
        "history_length": max(5, min(1000, history_length)),
        "background": normalize_hex_color(str(saved.get("background", "")))
        or str(DEFAULT_SERVER_LOG_PREFERENCES["background"]),
        "text": normalize_hex_color(str(saved.get("text", "")))
        or str(DEFAULT_SERVER_LOG_PREFERENCES["text"]),
        "theme": theme,
    }


def save_server_log_preferences(form: dict[str, str], user: sqlite3.Row | None = None) -> dict[str, object]:
    try:
        history_length = int(form.get("history_length", "18"))
    except ValueError:
        history_length = 18
    preferences = {
        "history_length": max(5, min(1000, history_length)),
        "background": normalize_hex_color(form.get("background", ""))
        or str(DEFAULT_SERVER_LOG_PREFERENCES["background"]),
        "text": normalize_hex_color(form.get("text", ""))
        or str(DEFAULT_SERVER_LOG_PREFERENCES["text"]),
        "theme": form.get("theme", "custom") if form.get("theme") in {*SERVER_LOG_THEMES, "custom"} else "custom",
    }
    encoded = json.dumps(preferences)
    if user:
        set_user_setting(user["id"], "server_log_preferences", encoded)
    else:
        set_setting("server_log_preferences", encoded)
    return preferences


def reset_server_log_preferences(user: sqlite3.Row | None = None) -> None:
    if user:
        set_user_setting(user["id"], "server_log_preferences", "{}")
    else:
        set_setting("server_log_preferences", json.dumps(DEFAULT_SERVER_LOG_PREFERENCES))


def update_own_profile(user_id: int, username: str, current_password: str, new_password: str) -> list[str]:
    username = username.strip()
    if not username:
        return ["Username is required."]
    with get_auth_connection() as conn:
        user = conn.execute("SELECT * FROM webusers WHERE id = ?", (user_id,)).fetchone()
        if not user or not verify_password(current_password, user["password_hash"]):
            return ["Current password is incorrect."]
        try:
            if new_password:
                conn.execute(
                    "UPDATE webusers SET username = ?, password_hash = ?, must_change_password = 0 WHERE id = ?",
                    (username, hash_password(new_password), user_id),
                )
            else:
                conn.execute("UPDATE webusers SET username = ? WHERE id = ?", (username, user_id))
        except sqlite3.IntegrityError:
            return ["A webuser with that username already exists."]
    return []


def set_force_password_change(user_id: int, required: bool) -> None:
    with get_auth_connection() as conn:
        conn.execute("UPDATE webusers SET must_change_password = ? WHERE id = ?", (1 if required else 0, user_id))
        if required:
            conn.execute("DELETE FROM web_sessions WHERE user_id = ?", (user_id,))


def invalidate_user_sessions(user_id: int | None = None) -> None:
    with get_auth_connection() as conn:
        if user_id is None:
            conn.execute("DELETE FROM web_sessions")
        else:
            conn.execute("DELETE FROM web_sessions WHERE user_id = ?", (user_id,))


def signup_user(username: str, password: str, actor: dict[str, str] | None = None) -> list[str]:
    if len(password) < 8:
        return ["Password must be at least 8 characters."]
    errors, _generated = create_webuser("USER", username, password)
    if not errors:
        log_user_audit(
            "User created",
            username.strip(),
            "USER account created through public signup.",
            actor,
        )
    return errors


def save_log_settings(form: dict[str, str]) -> list[str]:
    errors: list[str] = []
    accent_color = normalize_hex_color(form.get("accent_color", DEFAULT_ACCENT_COLOR))
    if not accent_color:
        errors.append("Accent colour must be a valid hex colour.")
        return errors
    date_format = form.get("date_format", DEFAULT_DATE_FORMAT)
    if date_format not in DATE_FORMATS:
        errors.append("Date format is not valid.")
        return errors
    set_setting("accent_color", accent_color)
    set_setting("date_format", date_format)
    return errors


def reset_appearance_defaults() -> None:
    set_setting("accent_color", DEFAULT_ACCENT_COLOR)
    set_setting("date_format", DEFAULT_DATE_FORMAT)


def save_server_config(form: dict[str, str]) -> tuple[list[str], bool]:
    errors: list[str] = []
    config = read_config()
    auth_opt = form.get("auth_opt", config["AUTH_OPT"]).upper()
    ip = form.get("ip", config["IP"]).strip() or DEFAULT_HOST
    port_raw = form.get("port", config["PORT"])
    title = form.get("app_title", DEFAULT_APP_TITLE).strip()
    eyebrow = form.get("app_eyebrow", DEFAULT_APP_EYEBROW).strip()
    raw_log_mb = form.get("log_max_mb", str(DEFAULT_LOG_MAX_MB)).strip()
    favicon_data = form.get("favicon_data", "")
    if auth_opt not in AUTH_OPTIONS:
        errors.append("Auth option must be NONE, EDIT, or VIEW.")
    try:
        port = int(port_raw)
        if port < 1 or port > 65535:
            raise ValueError
    except ValueError:
        port = int(config["PORT"])
        errors.append("Port must be between 1 and 65535.")
    try:
        log_mb = int(raw_log_mb)
        if log_mb < 1 or log_mb > 1024:
            raise ValueError
    except ValueError:
        log_mb = DEFAULT_LOG_MAX_MB
        errors.append("Log size must be between 1 and 1024 MB.")
    if not title:
        errors.append("Application title is required.")
    if not eyebrow:
        errors.append("Header text is required.")
    favicon_path = ""
    if favicon_data:
        match = re.fullmatch(r"data:image/(png|x-icon|vnd\.microsoft\.icon);base64,(.+)", favicon_data, re.DOTALL)
        if not match:
            errors.append("Favicon must be a PNG or ICO file.")
        else:
            try:
                payload = base64.b64decode(match.group(2), validate=True)
                if len(payload) > 512 * 1024:
                    errors.append("Favicon must be smaller than 512 KB.")
                else:
                    extension = "png" if match.group(1) == "png" else "ico"
                    favicon_path = f"/static/custom_favicon.{extension}"
                    (STATIC_DIR / f"custom_favicon.{extension}").write_bytes(payload)
            except (ValueError, OSError):
                errors.append("Favicon could not be saved.")
    if errors:
        return errors, False
    changed_bind = ip != config["IP"]
    write_config({"AUTH_OPT": auth_opt, "PORT": str(port), "IP": ip})
    set_setting("log_max_mb", str(log_mb))
    set_setting("app_title", title)
    set_setting("app_eyebrow", eyebrow)
    if favicon_path:
        set_setting("favicon_path", favicon_path)
    return [], changed_bind


def reset_server_defaults() -> None:
    write_config({"AUTH_OPT": "NONE", "PORT": str(DEFAULT_PORT), "IP": DEFAULT_HOST})
    set_setting("log_max_mb", str(DEFAULT_LOG_MAX_MB))
    set_setting("app_title", DEFAULT_APP_TITLE)
    set_setting("app_eyebrow", DEFAULT_APP_EYEBROW)


def fetch_pull_items(
    person_ids: list[int],
    match: str,
    freezer_ids: list[str] | None = None,
    search: str = "",
    include_ingredients: bool = False,
) -> list[sqlite3.Row]:
    if not person_ids and not include_ingredients:
        return []
    params: list[object] = []
    selection_clauses: list[str] = []
    if person_ids:
        placeholders = ",".join("?" for _ in person_ids)
        if match == "all":
            person_clause = f"""
                (
                    SELECT COUNT(DISTINCT picked.person_id)
                    FROM item_people picked
                    WHERE picked.item_id = freezer_items.id
                        AND picked.person_id IN ({placeholders})
                ) = ?
            """
        else:
            person_clause = f"""
                EXISTS (
                    SELECT 1
                    FROM item_people picked
                    WHERE picked.item_id = freezer_items.id
                        AND picked.person_id IN ({placeholders})
                )
            """
        params.extend(person_ids)
        if match == "all":
            params.append(len(set(person_ids)))
        selection_clauses.append(person_clause)
    if include_ingredients:
        selection_clauses.append("freezer_items.ingredient = 1")
    selection_joiner = " AND " if match == "all" else " OR "
    selection_clause = f" AND ({selection_joiner.join(selection_clauses)})"
    freezer_ids = freezer_ids or []
    freezer_clause = ""
    if freezer_ids:
        include_unassigned = "unassigned" in freezer_ids
        numeric_freezers = [value for value in freezer_ids if value != "unassigned"]
        clauses = []
        if numeric_freezers:
            clauses.append(f"freezer_items.freezer_id IN ({','.join('?' for _ in numeric_freezers)})")
            params.extend(numeric_freezers)
        if include_unassigned:
            clauses.append("freezer_items.freezer_id IS NULL")
        freezer_clause = f" AND ({' OR '.join(clauses)})"
    search_clause = ""
    if search.strip():
        search_clause = " AND (freezer_items.name LIKE ? OR freezer_items.notes LIKE ?)"
        like = f"%{search.strip()}%"
        params.extend([like, like])
    with get_connection() as conn:
        return list(
            conn.execute(
                f"""
                SELECT freezer_items.*,
                    COALESCE(freezers.name, freezer_items.location, 'Unassigned') AS freezer_name,
                    GROUP_CONCAT(DISTINCT people.name) AS people_names,
                    CASE
                        WHEN use_by IS NULL OR use_by = '' THEN 99999
                        ELSE CAST(julianday(use_by) - julianday('now') AS INTEGER)
                    END AS days_left
                FROM freezer_items
                LEFT JOIN freezers ON freezers.id = freezer_items.freezer_id
                LEFT JOIN item_people all_people ON all_people.item_id = freezer_items.id
                LEFT JOIN people ON people.id = all_people.person_id
                WHERE freezer_items.quantity > 0
                    {selection_clause}
                    {freezer_clause}
                    {search_clause}
                GROUP BY freezer_items.id
                ORDER BY freezer_name COLLATE NOCASE, freezer_items.name COLLATE NOCASE
                """,
                params,
            )
        )


def fetch_expiry_items(filters: dict[str, str]) -> list[sqlite3.Row]:
    days = int_or_none(filters.get("days")) or 30
    before = filters.get("before", "")
    if not before:
        before = (date.today() + timedelta(days=days)).isoformat()
    ingredient = filters.get("ingredient", "")
    ingredient_clause = ""
    params: list[object] = [before]
    if ingredient == "yes":
        ingredient_clause = "AND freezer_items.ingredient = 1"
    elif ingredient == "no":
        ingredient_clause = "AND freezer_items.ingredient = 0"
    with get_connection() as conn:
        return list(
            conn.execute(
                f"""
                SELECT freezer_items.*,
                    COALESCE(freezers.name, freezer_items.location, 'Unassigned') AS freezer_name,
                    GROUP_CONCAT(people.name, ', ') AS people_names,
                    CAST(julianday(use_by) - julianday('now') AS INTEGER) AS days_left
                FROM freezer_items
                LEFT JOIN freezers ON freezers.id = freezer_items.freezer_id
                LEFT JOIN item_people ON item_people.item_id = freezer_items.id
                LEFT JOIN people ON people.id = item_people.person_id
                WHERE use_by IS NOT NULL
                    AND use_by != ''
                    AND freezer_items.quantity > 0
                    AND date(use_by) <= date(?)
                    {ingredient_clause}
                GROUP BY freezer_items.id
                ORDER BY date(use_by) ASC, freezer_items.name COLLATE NOCASE
                """,
                params,
            )
        )


def fetch_audit_events(limit: int = 250, actions: list[str] | None = None, search: str = "") -> list[sqlite3.Row]:
    limit = max(1, min(limit, 1000))
    where: list[str] = []
    params: list[object] = []
    if actions:
        where.append(f"action IN ({','.join('?' for _ in actions)})")
        params.extend(actions)
    if search:
        where.append("(item_name LIKE ? COLLATE NOCASE OR details LIKE ? COLLATE NOCASE OR username LIKE ? COLLATE NOCASE)")
        params.extend([f"%{search}%"] * 3)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    with get_connection() as conn:
        return list(
            conn.execute(
                f"""
                SELECT *
                FROM audit_events
                {where_sql}
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (*params, limit),
            )
        )


def audit_colors() -> dict[str, str]:
    current_user = getattr(RENDER_CONTEXT, "user", None)
    try:
        raw = (
            get_user_setting(current_user["id"], "audit_colors", "{}")
            if current_user
            else get_setting("audit_colors", "{}")
        )
        saved = json.loads(raw)
    except json.JSONDecodeError:
        saved = {}
    return {**DEFAULT_AUDIT_COLORS, **{key: value for key, value in saved.items() if normalize_hex_color(str(value))}}


def audit_badge(action: str) -> str:
    color = audit_colors().get(action, "#657173")
    return f'<span class="badge audit-action-badge" style="--audit-color:{esc(color)}">{esc(action)}</span>'


def fetch_stock_stats(recent_limit: int = 50) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    recent_limit = max(1, min(recent_limit, 5000))
    stats_since = get_setting("stock_stats_since", "")
    with get_connection() as conn:
        by_item = list(
            conn.execute(
                """
                SELECT item_name,
                    unit,
                    SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS added,
                    ABS(SUM(CASE WHEN delta < 0 THEN delta ELSE 0 END)) AS removed,
                    COUNT(*) AS changes
                FROM stock_events
                WHERE delta IS NOT NULL
                    AND archived_at IS NULL
                    AND (? = '' OR datetime(created_at) >= datetime(?))
                GROUP BY item_name, unit
                ORDER BY removed DESC, added DESC, item_name COLLATE NOCASE
                LIMIT 50
                """,
                (stats_since, stats_since),
            )
        )
        recent = list(
            conn.execute(
                """
                SELECT *
                FROM stock_events
                WHERE archived_at IS NULL
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (recent_limit,),
            )
        )
    return by_item, recent


def archive_stock_events(actor: dict[str, str]) -> int:
    batch = secrets.token_hex(8)
    archived_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        count = int(
            conn.execute("SELECT COUNT(*) AS count FROM stock_events WHERE archived_at IS NULL").fetchone()["count"]
        )
        if count:
            conn.execute(
                """
                UPDATE stock_events
                SET archive_batch = ?,
                    archived_at = ?,
                    archived_by = ?,
                    archived_ip = ?,
                    archived_device = ?
                WHERE archived_at IS NULL
                """,
                (
                    batch,
                    archived_at,
                    actor.get("username", ""),
                    actor.get("ip_address", ""),
                    actor.get("device_name", ""),
                ),
            )
            log_audit(
                conn,
                "Events archived",
                None,
                "Stock events",
                f"Archived {count} stock event(s) for 90-day administrator retention. Archive batch: {batch}.",
                actor,
            )
    return count


def fetch_stock_event_archives() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                """
                SELECT archive_batch, archived_at, archived_by, archived_ip, archived_device,
                    COUNT(*) AS event_count,
                    MIN(created_at) AS first_event_at,
                    MAX(created_at) AS last_event_at
                FROM stock_events
                WHERE archived_at IS NOT NULL
                    AND datetime(archived_at) >= datetime('now', '-90 days')
                GROUP BY archive_batch, archived_at, archived_by, archived_ip, archived_device
                ORDER BY datetime(archived_at) DESC
                """
            )
        )


def fetch_archived_stock_events(batch: str = "") -> list[sqlite3.Row]:
    with get_connection() as conn:
        if batch:
            return list(
                conn.execute(
                    """
                    SELECT * FROM stock_events
                    WHERE archive_batch = ?
                        AND archived_at IS NOT NULL
                        AND datetime(archived_at) >= datetime('now', '-90 days')
                    ORDER BY datetime(created_at) DESC, id DESC
                    """,
                    (batch,),
                )
            )
        return list(
            conn.execute(
                """
                SELECT * FROM stock_events
                WHERE archived_at IS NOT NULL
                    AND datetime(archived_at) >= datetime('now', '-90 days')
                ORDER BY datetime(archived_at) DESC, datetime(created_at) DESC, id DESC
                LIMIT 5000
                """
            )
        )


def archive_stats_reset(actor: dict[str, str]) -> int:
    by_item, _recent = fetch_stock_stats()
    snapshot = [dict(row) for row in by_item]
    reset_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        event_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM stock_events
                WHERE archived_at IS NULL
                    AND delta IS NOT NULL
                    AND (? = '' OR datetime(created_at) >= datetime(?))
                """,
                (get_setting("stock_stats_since", ""), get_setting("stock_stats_since", "")),
            ).fetchone()["count"]
        )
        cursor = conn.execute(
            """
            INSERT INTO stats_reset_history
                (reset_at, reset_by, reset_ip, reset_device, snapshot_json, item_count, event_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reset_at,
                actor.get("username", ""),
                actor.get("ip_address", ""),
                actor.get("device_name", ""),
                json.dumps(snapshot),
                len(snapshot),
                event_count,
            ),
        )
        log_audit(
            conn,
            "Stats reset",
            None,
            "Usage statistics",
            f"Reset usage statistics after preserving {len(snapshot)} food summary row(s) from {event_count} event(s). Reset ID: {cursor.lastrowid}.",
            actor,
        )
    return int(cursor.lastrowid)


def fetch_stats_reset_history() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                """
                SELECT *
                FROM stats_reset_history
                WHERE datetime(reset_at) >= datetime('now', '-90 days')
                ORDER BY datetime(reset_at) DESC, id DESC
                """
            )
        )


def fetch_stats_reset(reset_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM stats_reset_history
            WHERE id = ?
                AND datetime(reset_at) >= datetime('now', '-90 days')
            """,
            (reset_id,),
        ).fetchone()


def fetch_inventory_distribution() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return list(
            conn.execute(
                """
                SELECT name AS item_name, SUM(quantity) AS quantity
                FROM freezer_items
                WHERE quantity > 0
                GROUP BY LOWER(TRIM(name))
                ORDER BY quantity DESC, item_name COLLATE NOCASE
                """
            )
        )


_CPU_SAMPLE: tuple[int, float] | None = None


def add_network_bytes(amount: int) -> None:
    global APP_NETWORK_BYTES
    if amount <= 0:
        return
    with NETWORK_LOCK:
        APP_NETWORK_BYTES += amount


def app_storage_bytes() -> int:
    files = [DB_PATH, AUTH_DB_PATH, CONFIG_PATH, LOG_PATH, ROOT / "server.py"]
    files.extend(path for path in STATIC_DIR.rglob("*") if path.is_file())
    return sum(path.stat().st_size for path in files if path.exists())


def display_bytes(value: object) -> str:
    size = float(value or 0)
    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or suffix == "TB":
            return f"{size:.1f} {suffix}" if suffix != "B" else f"{size:.0f} {suffix}"
        size /= 1024
    return "0 B"


def system_snapshot() -> dict[str, float | int]:
    global _CPU_SAMPLE
    cpu_percent = 0.0
    ram_percent = 0.0
    ram_bytes = 0
    with NETWORK_LOCK:
        network_bytes = APP_NETWORK_BYTES
    disk_io_bytes = 0
    try:
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = ctypes.c_void_p
        ctypes.windll.kernel32.GetProcessTimes(
            get_process(),
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        current = (kernel.value + user.value, time.perf_counter())
        if _CPU_SAMPLE:
            process_seconds = (current[0] - _CPU_SAMPLE[0]) / 10_000_000
            elapsed = current[1] - _CPU_SAMPLE[1]
            if elapsed > 0:
                cpu_percent = max(0.0, min(100.0, process_seconds / elapsed / max(1, os.cpu_count() or 1) * 100))
        _CPU_SAMPLE = current
    except Exception:
        pass
    try:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong),
                ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong),
                ("avail_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("avail_virtual", ctypes.c_ulonglong),
                ("avail_extended", ctypes.c_ulonglong),
            ]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = ctypes.c_void_p
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCounters), ctypes.c_ulong]
        get_memory.restype = ctypes.c_int
        get_memory(get_process(), ctypes.byref(counters), counters.cb)
        ram_bytes = int(counters.working_set_size)
        ram_percent = counters.working_set_size / status.total_phys * 100 if status.total_phys else 0.0
    except Exception:
        pass
    try:
        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("read_ops", ctypes.c_ulonglong),
                ("write_ops", ctypes.c_ulonglong),
                ("other_ops", ctypes.c_ulonglong),
                ("read_bytes", ctypes.c_ulonglong),
                ("write_bytes", ctypes.c_ulonglong),
                ("other_bytes", ctypes.c_ulonglong),
            ]
        counters = IoCounters()
        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = ctypes.c_void_p
        get_io = ctypes.windll.kernel32.GetProcessIoCounters
        get_io.argtypes = [ctypes.c_void_p, ctypes.POINTER(IoCounters)]
        get_io(get_process(), ctypes.byref(counters))
        disk_io_bytes = counters.read_bytes + counters.write_bytes
    except Exception:
        pass
    return {
        "cpu_percent": round(cpu_percent, 2),
        "ram_percent": round(ram_percent, 2),
        "ram_bytes": ram_bytes,
        "disk_percent": 0.0,
        "disk_io_bytes": disk_io_bytes,
        "app_storage_bytes": app_storage_bytes(),
        "network_bytes": network_bytes,
    }


def record_system_metric() -> None:
    values = system_snapshot()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO system_metrics (
                cpu_percent, ram_percent, ram_bytes, disk_percent, disk_io_bytes, app_storage_bytes, network_bytes
            )
            VALUES (
                :cpu_percent, :ram_percent, :ram_bytes, :disk_percent, :disk_io_bytes, :app_storage_bytes, :network_bytes
            )
            """,
            values,
        )
        conn.execute("DELETE FROM system_metrics WHERE datetime(created_at) < datetime('now', '-30 days')")


def metrics_loop(stop_event: threading.Event) -> None:
    system_snapshot()
    while not stop_event.wait(30):
        try:
            record_system_metric()
        except Exception as exc:
            safe_print(f"Metrics sample failed: {exc}")


def fetch_system_metrics(range_key: str) -> list[sqlite3.Row]:
    windows = {"1h": "-1 hour", "6h": "-6 hours", "24h": "-24 hours", "7d": "-7 days"}
    window = windows.get(range_key, "-1 hour")
    with get_connection() as conn:
        return list(
            conn.execute(
                """
                SELECT * FROM system_metrics
                WHERE datetime(created_at) >= datetime('now', ?)
                ORDER BY datetime(created_at), id
                """,
                (window,),
            )
        )


def change_version() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS version FROM audit_events").fetchone()
        return int(row["version"])


def option_tags_from_rows(rows: list[sqlite3.Row], selected: str | int | None) -> str:
    selected_text = "" if selected is None else str(selected)
    return "".join(
        f'<option value="{row["id"]}" {"selected" if str(row["id"]) == selected_text else ""}>{esc(row["name"])}</option>'
        for row in rows
    )


def option_tags(options: list[str], selected: str | None) -> str:
    return "".join(
        f'<option value="{esc(option)}" {"selected" if option == selected else ""}>{esc(option)}</option>'
        for option in options
    )


def checkbox_tags(people: list[sqlite3.Row], selected_ids: list[int]) -> str:
    selected = set(selected_ids)
    if not people:
        return '<p class="muted compact">No people yet.</p>'
    return "".join(
        f"""
        <label class="check-option">
            <input type="checkbox" name="person_ids" value="{person["id"]}" {"checked" if person["id"] in selected else ""}>
            <span>{esc(person["name"])}</span>
        </label>
        """
        for person in people
    )


def checkbox_filter_rows(rows: list[sqlite3.Row], name: str, selected_values: list[str]) -> str:
    selected = set(selected_values)
    return "".join(
        f"""
        <label class="check-option">
            <input type="checkbox" name="{esc(name)}" value="{row["id"]}" {"checked" if str(row["id"]) in selected else ""}>
            <span>{esc(row["name"])}</span>
        </label>
        """
        for row in rows
    )


def age_label(frozen_on: str) -> str:
    try:
        frozen_date = datetime.strptime(frozen_on, "%Y-%m-%d").date()
    except ValueError:
        return "Unknown"
    days = (date.today() - frozen_date).days
    if days < 0:
        return "Future"
    if days == 0:
        return "Today"
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    return f"{months} month{'s' if months != 1 else ''} ago"


def use_by_label(use_by: str | None) -> str:
    if not use_by:
        return ""
    try:
        use_by_date = datetime.strptime(use_by, "%Y-%m-%d").date()
    except ValueError:
        return "Unknown"
    days = (use_by_date - date.today()).days
    if days < 0:
        overdue = abs(days)
        return f"{overdue} day{'s' if overdue != 1 else ''} ago"
    if days == 0:
        return "Today"
    return f"{days} day{'s' if days != 1 else ''}"


def display_date(value: str | None) -> str:
    if not value:
        return "Not set"
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return value
    date_format = get_setting("date_format", DEFAULT_DATE_FORMAT)
    return parsed.strftime(DATE_FORMATS.get(date_format, DATE_FORMATS[DEFAULT_DATE_FORMAT]))


def display_quantity(item: sqlite3.Row) -> str:
    quantity = float(item["quantity"])
    unit = str(item["unit"])
    if quantity != 1 and unit and not unit.lower().endswith("s"):
        unit = f"{unit}s"
    return f"{quantity:g} {unit}"


def stat_class(value: int, kind: str) -> str:
    if kind == "expired":
        return "stat-good" if value == 0 else "stat-danger"
    if kind == "soon":
        if value == 0:
            return "stat-good"
        if value <= 5:
            return "stat-warning"
        return "stat-danger"
    return ""


def get_setting(key: str, default: str) -> str:
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return default
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def create_backup(mode: str) -> tuple[bytes, str, str]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if mode == "settings":
        with get_connection() as conn:
            settings = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM app_settings")}
        payload = json.dumps(
            {"type": "freezer-stock-settings", "version": 1, "config": read_config(), "settings": settings},
            indent=2,
        ).encode("utf-8")
        return payload, f"freezer-stock-settings-{timestamp}.json", "application/json"

    with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
        temp = Path(temp_dir)
        main_copy = temp / "freezer.db"
        auth_copy = temp / "webuser_auth.db"
        source = get_connection()
        destination = sqlite3.connect(main_copy)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        source = get_auth_connection()
        destination = sqlite3.connect(auth_copy)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(main_copy, "freezer.db")
            bundle.write(auth_copy, "webuser_auth.db")
            bundle.writestr("config.yml", CONFIG_PATH.read_text(encoding="utf-8"))
            favicon = get_setting("favicon_path", "").removeprefix("/static/")
            favicon_path = STATIC_DIR / favicon
            if favicon and favicon_path.exists():
                bundle.write(favicon_path, f"static/{favicon_path.name}")
        return archive.getvalue(), f"freezer-stock-full-{timestamp}.zip", "application/zip"


def create_prereset_backup() -> tuple[str, str]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder_name = f"prereset-backup-{timestamp}"
    folder = ROOT / folder_name
    suffix = 1
    while folder.exists():
        folder_name = f"prereset-backup-{timestamp}-{suffix}"
        folder = ROOT / folder_name
        suffix += 1
    folder.mkdir()
    payload, filename, _content_type = create_backup("full")
    (folder / filename).write_bytes(payload)
    return folder_name, filename


def reset_application_preserving_admins() -> None:
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        triggers = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")]
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for trigger in triggers:
            conn.execute(f'DROP TRIGGER IF EXISTS "{trigger.replace(chr(34), chr(34) * 2)}"')
        for table in tables:
            conn.execute(f'DROP TABLE IF EXISTS "{table.replace(chr(34), chr(34) * 2)}"')
        conn.commit()
    finally:
        conn.close()
    init_db()
    auth_conn = get_auth_connection()
    try:
        auth_conn.execute(
            "DELETE FROM webuser_settings WHERE user_id IN (SELECT id FROM webusers WHERE role != 'ADMIN')"
        )
        auth_conn.execute("DELETE FROM webusers WHERE role != 'ADMIN'")
        auth_conn.commit()
    finally:
        auth_conn.close()
    safe_print("Application data reset to defaults; administrator accounts were preserved.")


def prereset_backup_path(folder_name: str) -> Path | None:
    if not re.fullmatch(r"prereset-backup-\d{8}-\d{6}(?:-\d+)?", folder_name):
        return None
    folder = ROOT / folder_name
    if not folder.is_dir():
        return None
    backups = sorted(folder.glob("freezer-stock-full-*.zip"))
    return backups[0] if len(backups) == 1 else None


def restore_backup(mode: str, encoded_data: str) -> list[str]:
    try:
        payload = base64.b64decode(encoded_data.split(",", 1)[-1], validate=True)
    except (ValueError, binascii.Error):
        return ["Backup file could not be decoded."]
    try:
        if mode == "settings":
            data = json.loads(payload.decode("utf-8"))
            if data.get("type") != "freezer-stock-settings":
                return ["That is not a Freezer Stock settings backup."]
            config = data.get("config", {})
            settings = data.get("settings", {})
            write_config(config)
            with get_connection() as conn:
                conn.executemany(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    [(str(key), str(value)) for key, value in settings.items()],
                )
            return []

        with zipfile.ZipFile(io.BytesIO(payload)) as bundle, tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            required = {"freezer.db", "webuser_auth.db", "config.yml"}
            if not required.issubset(bundle.namelist()):
                return ["That is not a complete Freezer Stock backup."]
            temp = Path(temp_dir)
            bundle.extract("freezer.db", temp)
            bundle.extract("webuser_auth.db", temp)
            source = sqlite3.connect(temp / "freezer.db")
            destination = get_connection()
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            source = sqlite3.connect(temp / "webuser_auth.db")
            destination = get_auth_connection()
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            CONFIG_PATH.write_bytes(bundle.read("config.yml"))
            for name in bundle.namelist():
                if name.startswith("static/") and Path(name).name == name.removeprefix("static/"):
                    (STATIC_DIR / Path(name).name).write_bytes(bundle.read(name))
        init_db()
        init_auth_db()
        return []
    except (OSError, sqlite3.Error, zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        return [f"Backup could not be restored: {exc}"]


def log_tail(limit: int = 18) -> str:
    if not LOG_PATH.exists():
        return "No server log entries yet."
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[: max(1, limit)])


def shutdown_from_web() -> None:
    if SERVER_INSTANCE:
        SERVER_INSTANCE.shutdown()
        SERVER_INSTANCE.server_close()
    time.sleep(0.2)
    os._exit(0)


def csv_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def report_csv(report: str) -> tuple[bytes, str] | None:
    if report == "buy":
        items = fetch_buy_items()
        rows = [[row["name"], display_quantity(row), row["buy_reason"], row["freezer_name"], row["people_names"] or "No one"] for row in items]
        return csv_bytes(["Food", "Quantity", "Reason", "Freezer", "People"], rows), "buy-list.csv"
    if report == "expiry":
        items = fetch_expiry_items({"days": "36500"})
        rows = [[row["name"], display_quantity(row), row["freezer_name"], display_date(row["use_by"]), use_by_label(row["use_by"])] for row in items]
        return csv_bytes(["Food", "Quantity", "Freezer", "Use by", "Status"], rows), "expiry-report.csv"
    if report == "stock":
        _by_item, events = fetch_stock_stats(5000)
        rows = [[row["created_at"], row["item_name"], row["action"], row["quantity_before"], row["quantity_after"], row["username"] or ""] for row in events]
        return csv_bytes(["When", "Food", "Action", "Before", "After", "User"], rows), "stock-events.csv"
    return None


def logs_page() -> bytes:
    preferences = server_log_preferences(getattr(RENDER_CONTEXT, "user", None))
    content = f"""
        <section class="panel">
            <div class="panel-heading split">
                <h2>Server Log</h2>
                <div class="heading-actions">
                    <button class="icon-button" type="button" title="Server log settings" aria-label="Server log settings" data-server-log-settings-open>{icon("settings")}</button>
                    <button class="secondary" type="button" onclick="window.print()">Print</button>
                </div>
            </div>
            <pre class="full-log" data-live-server-log data-log-limit="1000" style="--server-log-bg: {esc(preferences["background"])}; --server-log-text: {esc(preferences["text"])}">{esc(log_tail(1000))}</pre>
        </section>
        {server_log_settings_modal("/logs")}
    """
    return render_page(content, "manage")


def log_max_bytes() -> int:
    raw_value = get_setting("log_max_mb", str(DEFAULT_LOG_MAX_MB))
    try:
        mb = int(raw_value)
    except ValueError:
        mb = DEFAULT_LOG_MAX_MB
    mb = max(1, min(mb, 1024))
    return mb * 1024 * 1024


def darken_hex_color(hex_color: str, factor: float = 0.7) -> str:
    color = normalize_hex_color(hex_color) or DEFAULT_ACCENT_COLOR
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    return f"#{int(red * factor):02x}{int(green * factor):02x}{int(blue * factor):02x}"


def theme_style() -> str:
    current_user = getattr(RENDER_CONTEXT, "user", None)
    palette = user_palette(current_user["id"]) if current_user else {
        "accent": normalize_hex_color(get_setting("accent_color", DEFAULT_ACCENT_COLOR)) or DEFAULT_ACCENT_COLOR,
        "info": normalize_hex_color(get_setting("info_color", "#2f5d7c")) or "#2f5d7c",
        "warning": normalize_hex_color(get_setting("warning_color", "#a4661b")) or "#a4661b",
        "danger": normalize_hex_color(get_setting("danger_color", "#a53d36")) or "#a53d36",
    }
    accent = palette["accent"]
    dark = darken_hex_color(accent)
    return (
        f'<style id="theme-style">:root {{--green:{esc(accent)};--green-dark:{esc(dark)};'
        f"--blue:{esc(palette['info'])};--amber:{esc(palette['warning'])};--red:{esc(palette['danger'])};}}</style>"
    )


def write_console_log(message: str) -> None:
    entry = f"{message.rstrip()}\n"
    max_bytes = log_max_bytes()
    encoded_entry = entry.encode("utf-8", errors="replace")
    with LOG_LOCK:
        existing = b""
        if LOG_PATH.exists():
            existing = LOG_PATH.read_bytes()
        combined = encoded_entry + existing
        if len(combined) > max_bytes:
            combined = combined[:max_bytes]
            last_newline = combined.rfind(b"\n")
            if last_newline > 0:
                combined = combined[: last_newline + 1]
        LOG_PATH.write_bytes(combined)


def status_badge(item: sqlite3.Row) -> str:
    use_by = item["use_by"]
    if not use_by:
        return '<span class="badge badge-neutral">No date</span>'

    days_left = item["days_left"]
    if days_left < 0:
        return '<span class="badge badge-danger">Expired Food</span>'
    if days_left <= 14:
        return f'<span class="badge badge-warning">{days_left} days</span>'
    return '<span class="badge badge-good">Fresh</span>'


def safe_print(message: str) -> None:
    if sys.stdout:
        print(message)
    try:
        write_console_log(message)
    except OSError:
        pass


def print_console_help() -> None:
    safe_print(
        "\nConsole commands\n"
        "  stop                         Stop the server cleanly\n"
        "  reload                       Re-run database setup and migrations\n"
        "  help                         Show this help\n\n"
        "Webuser commands\n"
        '  ADD WEBUSER "ADMIN/USER" "USERNAME" ["PASSWORD"]\n'
        '  EDIT WEBUSER "USERNAME" "ADMIN/USER" "NEWUSERNAME" ["PASSWORD"]\n'
        '  REMOVE WEBUSER "USERNAME"\n'
        "  Password is optional. Leave it blank to generate a strong password.\n"
    )


def lan_urls() -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    try:
        host_name = socket.gethostname()
        addresses = socket.getaddrinfo(host_name, None, family=socket.AF_INET)
    except OSError:
        addresses = []
    for address in addresses:
        ip = address[4][0]
        if ip.startswith("127.") or ip in seen:
            continue
        seen.add(ip)
        urls.append(f"http://{ip}:{PORT}")
    return urls


def bind_server_with_fallback() -> ThreadingHTTPServer:
    global PORT
    config = read_config()
    host = config["IP"]
    port = int(config["PORT"])
    while port <= 65535:
        try:
            server = ThreadingHTTPServer((host, port), FreezerHandler)
            if port != int(config["PORT"]):
                write_config({**config, "PORT": str(port)})
                safe_print(f"Configured port was busy; updated config.yml to PORT=\"{port}\".")
            PORT = port
            return server
        except OSError:
            port += 1
    raise OSError("No available port found.")


def parse_console_command(command: str) -> list[str]:
    return [quoted or bare for quoted, bare in re.findall(r'"([^"]*)"|(\S+)', command)]


def handle_webuser_command(parts: list[str]) -> bool:
    if not parts:
        return False
    command = parts[0].upper()
    if command == "ADD" and len(parts) >= 4 and parts[1].upper() == "WEBUSER":
        password = parts[4] if len(parts) >= 5 else None
        errors, generated = create_webuser(parts[2], parts[3], password)
        if errors:
            safe_print("; ".join(errors))
        else:
            log_user_audit(
                "User created",
                parts[3],
                f"{normalize_role(parts[2])} account created from the server console. Password {'generated automatically' if generated else 'supplied through the console'}.",
                {"username": "Console", "device_name": "Server console"},
            )
            message = f"Created {normalize_role(parts[2])} webuser {parts[3]}."
            if generated:
                message += f" Generated password: {generated}"
            safe_print(message)
        return True
    if command == "REMOVE" and len(parts) >= 3 and parts[1].upper() == "WEBUSER":
        username = parts[2]
        with get_auth_connection() as conn:
            row = conn.execute("SELECT id FROM webusers WHERE username = ?", (username,)).fetchone()
            if row:
                conn.execute("DELETE FROM webusers WHERE id = ?", (row["id"],))
                log_user_audit(
                    "User deleted",
                    username,
                    "Account permanently deleted from the server console.",
                    {"username": "Console", "device_name": "Server console"},
                )
                safe_print(f"Removed webuser {username}.")
            else:
                safe_print(f"Webuser {username} was not found.")
        return True
    if command == "EDIT" and len(parts) >= 5 and parts[1].upper() == "WEBUSER":
        username = parts[2]
        with get_auth_connection() as conn:
            row = conn.execute("SELECT id, role FROM webusers WHERE username = ?", (username,)).fetchone()
        if not row:
            safe_print(f"Webuser {username} was not found.")
            return True
        role = parts[3]
        new_username = parts[4]
        password = parts[5] if len(parts) >= 6 else None
        errors, generated = update_webuser(row["id"], role, new_username, password)
        if errors:
            safe_print("; ".join(errors))
        else:
            log_user_audit(
                "User updated",
                new_username,
                (
                    f'Account updated from the server console; previous username "{username}", '
                    f"role set to {normalize_role(role)}"
                    f"{'; password changed' if password else ''}."
                ),
                {"username": "Console", "device_name": "Server console"},
            )
            message = f"Updated webuser {username}."
            if generated:
                message += f" Generated password: {generated}"
            safe_print(message)
        return True
    return False


def return_path(path: str, query_values: dict[str, object] | None = None) -> str:
    if not query_values:
        return path
    pairs: list[tuple[str, str]] = []
    for key, value in query_values.items():
        if isinstance(value, list):
            pairs.extend((key, item) for item in value)
        elif value:
            pairs.append((key, value))
    return path if not pairs else f"{path}?{urlencode(pairs)}"


def safe_return_target(target: str) -> str:
    if not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


def stock_controls(item: sqlite3.Row, return_to: str) -> str:
    return f"""
        <form method="post" action="/stock/{item["id"]}" class="stock-control">
            <input type="hidden" name="return_to" value="{esc(return_to)}">
            <input type="hidden" name="amount" value="1">
            <button type="submit" name="direction" value="remove" title="Remove stock">-</button>
            <button type="submit" name="direction" value="add" title="Add stock">+</button>
        </form>
    """


def item_form(
    item: sqlite3.Row | dict[str, object] | None,
    errors: list[str],
    action: str,
    title: str,
    selected_people: list[int] | None = None,
    autofocus_field: str = "name",
    return_to: str = "/",
) -> str:
    freezers = fetch_freezers()
    people = fetch_people()
    units = fetch_units()
    categories = fetch_categories()
    unit_names = [unit["name"] for unit in units]
    category_names = [category["name"] for category in categories]
    values = {
        "name": "",
        "category": "Other",
        "quantity": "1",
        "unit": "item",
        "freezer_id": freezers[0]["id"] if freezers else "",
        "frozen_on": today_iso(),
        "use_by": next_year_iso(),
        "notes": "",
        "batch_number": "1",
        "house_staple": 0,
        "ingredient": 0,
        "staple_threshold": "1",
        "buy_requested": 0,
    }
    if item:
        if isinstance(item, sqlite3.Row):
            values.update({key: item[key] for key in values.keys() if key in item.keys()})
        else:
            values.update({key: item[key] for key in values.keys() if key in item})

    selected = selected_people
    if selected is None and item and isinstance(item, sqlite3.Row):
        selected = fetch_item_people(item["id"])
    selected = selected or []

    error_html = notice(errors) if errors else ""
    selected_unit = str(values["unit"]).lower()
    unit_select_options = "".join(
        f'<option value="{esc(unit)}" {"selected" if unit == selected_unit else ""}>{esc(unit)}</option>'
        for unit in unit_names
    )
    custom_unit = "" if selected_unit in unit_names else selected_unit
    selected_category = str(values["category"])
    category_select_options = "".join(
        f'<option value="{esc(category)}" {"selected" if category == selected_category else ""}>{esc(category)}</option>'
        for category in category_names
    )
    custom_category = "" if selected_category in category_names else selected_category

    return f"""
        <section class="panel form-panel">
            <div class="panel-heading">
                <h2>{esc(title)}</h2>
            </div>
            {error_html}
            <form method="post" action="{esc(action)}" class="item-form" data-food-form>
                <input type="hidden" name="buy_requested" value="{esc(values["buy_requested"])}">
                <input type="hidden" name="batch_number" value="{esc(values["batch_number"])}">
                <input type="hidden" name="return_to" value="{esc(return_to)}">
                <label>
                    <span>Food</span>
                    <div class="food-search">
                        <input name="name" required value="{esc(values["name"])}" placeholder="Chicken thighs" autocomplete="off" {"data-food-search" if action in ("/new", "/") else ""} {"data-autofocus" if autofocus_field == "name" else ""}>
                        <div class="food-suggestions" data-food-suggestions hidden></div>
                    </div>
                </label>
                <div class="item-control-row">
                    <label class="control-category">
                        <span>Category</span>
                        <select name="category" data-remember-category data-quick-add-select="category">
                            {category_select_options}
                            {f'<option value="{esc(custom_category)}" selected>{esc(custom_category)}</option>' if custom_category else ""}
                            <option value="__add__">Add Category</option>
                        </select>
                    </label>
                    <label class="control-freezer">
                        <span>Freezer</span>
                        <select name="freezer_id" data-quick-add-select="freezer">
                            <option value="">Unassigned</option>
                            {option_tags_from_rows(freezers, values["freezer_id"])}
                            <option value="__add__">Add Freezer</option>
                        </select>
                    </label>
                    <label class="control-quantity">
                        <span>Quantity</span>
                        <input name="quantity" type="number" min="0.01" step="any" required value="{esc(values["quantity"])}" {"data-autofocus" if autofocus_field == "quantity" else ""}>
                    </label>
                    <label class="control-unit">
                        <span>Unit</span>
                        <select name="unit" data-unit-select data-quick-add-select="unit">
                            {unit_select_options}
                            {f'<option value="{esc(custom_unit)}" selected>{esc(custom_unit)}</option>' if custom_unit else ""}
                            <option value="__add__">Add Unit</option>
                        </select>
                    </label>
                    <div class="attribute-controls">
                        <div class="staple-control control-staple {"is-open" if int(values.get("house_staple") or 0) else ""}" data-staple-control>
                            <label class="inline-toggle">
                                <input name="house_staple" type="checkbox" data-staple-toggle {"checked" if int(values.get("house_staple") or 0) else ""}>
                                <span>House Staple</span>
                            </label>
                            <div class="staple-threshold-reveal" data-staple-threshold>
                                <label>
                                    <span>Buy threshold</span>
                                    <input name="staple_threshold" type="number" min="0" step="any" value="{esc(values["staple_threshold"])}">
                                </label>
                            </div>
                        </div>
                        <label class="inline-toggle control-ingredient">
                            <input name="ingredient" type="checkbox" {"checked" if int(values.get("ingredient") or 0) else ""}>
                            <span>Ingredient</span>
                        </label>
                    </div>
                </div>
                <fieldset class="people-picker">
                    <legend>People</legend>
                    <button class="people-add-button" type="button" title="Add person" aria-label="Add person" data-quick-add-button="person">+</button>
                    <div class="check-grid" data-people-options>{checkbox_tags(people, selected)}</div>
                </fieldset>
                <div class="form-detail-row">
                    <div class="date-stack">
                        <label>
                            <span>Frozen on</span>
                            <input name="frozen_on" type="date" required value="{esc(values["frozen_on"])}">
                        </label>
                        <label>
                            <span>Use by</span>
                            <input name="use_by" type="date" value="{esc(values["use_by"])}">
                            <div class="date-shortcuts {"add-food-shortcuts" if action == "/new" else ""}">
                                <button type="button" data-expiry-months="1">1m</button>
                                <button type="button" data-expiry-months="2">2m</button>
                                <button type="button" data-expiry-months="3">3m</button>
                                <button type="button" data-expiry-months="4">4m</button>
                                <button type="button" data-expiry-months="6">6m</button>
                                <button type="button" data-expiry-months="12">12m</button>
                                <button type="button" data-expiry-months="24">24m</button>
                                <button type="button" data-expiry-months="36">36m</button>
                            </div>
                        </label>
                    </div>
                    <label class="notes-field">
                        <span>Notes</span>
                        <textarea name="notes" rows="4" placeholder="Portioned, cooked, brand, shelf...">{esc(values["notes"])}</textarea>
                    </label>
                </div>
                <div class="form-actions">
                    <button class="primary" type="submit">Save item</button>
                    <a class="secondary" href="{esc(return_to)}">Cancel</a>
                </div>
            </form>
        </section>
    """


def batch_form_values(item: sqlite3.Row) -> dict[str, object]:
    return {
        "name": item["name"],
        "category": item["category"],
        "quantity": "1",
        "unit": item["unit"],
        "freezer_id": item["freezer_id"] or "",
        "frozen_on": today_iso(),
        "use_by": next_year_iso(),
        "notes": item["notes"] or "",
        "batch_number": next_batch_number(item["name"]),
        "house_staple": item["house_staple"],
        "ingredient": item["ingredient"],
        "staple_threshold": item["staple_threshold"],
        "buy_requested": 0,
    }


def notice(errors: list[str]) -> str:
    error_items = "".join(f"<li>{esc(error)}</li>" for error in errors)
    return f'<div class="notice error"><strong>Check the form</strong><ul>{error_items}</ul></div>'


def render_page(content: str, active: str = "inventory") -> bytes:
    current_user = getattr(RENDER_CONTEXT, "user", None)
    auth_enabled = read_config()["AUTH_OPT"] != "NONE"
    can_edit = not auth_enabled or current_user is not None
    app_title = get_setting("app_title", DEFAULT_APP_TITLE)
    app_eyebrow = get_setting("app_eyebrow", DEFAULT_APP_EYEBROW)
    favicon_path = get_setting("favicon_path", "")
    nav = [
        ("/", "Inventory", "inventory"),
        ("/new", "Add food", "new"),
        ("/pull", "Pull food", "pull"),
        ("/buy", "Buy", "buy"),
        ("/expiry", "Expiring", "expiry"),
        ("/stats", "Stats", "stats"),
        ("/manage", "Manage", "manage"),
    ]
    if current_user and current_user["role"] == "ADMIN":
        nav.append(("/admin", "Admin", "admin"))
    nav_html = "".join(
        f'<a class="nav-link {"active" if key == active else ""}" href="{href}">{label}</a>'
        for href, label, key in nav
    )
    auth_action_html = ""
    if current_user:
        auth_action_html = f'<a class="nav-link subtle-nav logout-nav" href="/logout" title="Log out" aria-label="Log out">{icon("logout")}</a>'
    elif auth_enabled:
        auth_action_html = f'<a class="nav-link {"active" if active == "login" else ""}" href="/login">Login</a>'
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(app_title)}</title>
    {f'<link rel="icon" href="{esc(favicon_path)}">' if favicon_path else ""}
    <link rel="stylesheet" href="/static/styles.css">
    {theme_style()}
    <script src="/static/app.js" defer></script>
</head>
<body class="{"read-only" if not can_edit else ""}">
    <header class="topbar">
        <a class="brand-block" href="/" aria-label="Inventory">
            <p class="eyebrow">{esc(app_eyebrow)}</p>
            <h1>{esc(app_title)}</h1>
        </a>
        <div class="compact-nav-actions">
            <a class="compact-nav-shortcut" href="/new" title="Add food" aria-label="Add food">{icon("add")}</a>
            <a class="compact-nav-shortcut" href="/pull" title="Pull food" aria-label="Pull food">{icon("pull")}</a>
            <button class="menu-toggle {"admin-menu" if current_user and current_user["role"] == "ADMIN" else ""}" type="button" aria-label="Open navigation" aria-expanded="false" data-menu-toggle>
                <span></span><span></span><span></span>
            </button>
        </div>
        <nav class="main-nav" aria-label="Main navigation" data-main-nav>{nav_html}{auth_action_html}</nav>
    </header>
    <main>
        {content}
    </main>
    <footer class="site-footer">&copy; 2026 Jacob Warren</footer>
    <div class="modal-backdrop" data-confirm-modal hidden>
        <section class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
            <h2 id="confirm-title">Confirm action</h2>
            <p data-confirm-message></p>
            <div class="form-actions">
                <button class="secondary" type="button" data-confirm-cancel>Cancel</button>
                <button class="primary" type="button" data-confirm-accept>Confirm</button>
            </div>
        </section>
    </div>
    <div class="modal-backdrop" data-quick-add-modal hidden>
        <section class="confirm-modal quick-add-modal" role="dialog" aria-modal="true" aria-labelledby="quick-add-title">
            <h2 id="quick-add-title" data-quick-add-title>Add item</h2>
            <form data-quick-add-form>
                <input type="hidden" name="kind" data-quick-add-kind>
                <label>
                    <span data-quick-add-name-label>Name</span>
                    <input name="name" required data-quick-add-name>
                </label>
                <label>
                    <span>Notes</span>
                    <input name="notes" placeholder="Optional">
                </label>
                <p class="form-message" data-quick-add-error hidden></p>
                <div class="form-actions">
                    <button class="secondary" type="button" data-quick-add-cancel>Cancel</button>
                    <button class="primary" type="submit">Add</button>
                </div>
            </form>
        </section>
    </div>
    {f'''
    <div class="modal-backdrop" data-login-required-modal hidden>
        <section class="confirm-modal" role="dialog" aria-modal="true">
            <h2>Login required</h2>
            <p>Log in to make changes to Freezer Stock.</p>
            <div class="form-actions">
                <button class="secondary" type="button" data-login-required-cancel>Cancel</button>
                <a class="primary" href="/login">Login</a>
            </div>
        </section>
    </div>
    ''' if auth_enabled and not current_user else ""}
    <div class="modal-backdrop" data-password-modal hidden>
        <section class="confirm-modal" role="dialog" aria-modal="true">
            <h2>Confirm admin password</h2>
            <p data-password-message></p>
            <label><span>Password</span><input type="password" data-password-input></label>
            <div class="form-actions">
                <button class="secondary" type="button" data-password-cancel>Cancel</button>
                <button class="primary" type="button" data-password-accept>Confirm</button>
            </div>
        </section>
    </div>
</body>
</html>""".encode("utf-8")


def filter_dropdown(label: str, name: str, options: list[tuple[str, str]], selected: list[str]) -> str:
    selected_set = set(selected)
    selected_labels = [text for value, text in options if value in selected_set]
    checks = "".join(
        f'<label class="check-option" title="{esc(text)}"><input type="checkbox" name="{esc(name)}" value="{esc(value)}" {"checked" if value in selected_set else ""}><span>{esc(text)}</span></label>'
        for value, text in options
    )
    summary = ", ".join(selected_labels) if selected_labels else f"All {label.lower()}"
    return f"""
        <details class="filter-dropdown" data-filter-key="{esc(name)}">
            <summary title="{esc(summary)}"><span>{esc(summary)}</span></summary>
            <div class="filter-dropdown-menu">{checks}</div>
        </details>
    """


def people_filter_dropdown(people: list[sqlite3.Row], selected: list[str], match: str) -> str:
    selected_set = set(selected)
    selected_names = [str(row["name"]) for row in people if str(row["id"]) in selected_set]
    checks = "".join(
        f'<label class="check-option" title="{esc(row["name"])}"><input type="checkbox" name="person_id" value="{row["id"]}" {"checked" if str(row["id"]) in selected_set else ""}><span>{esc(row["name"])}</span></label>'
        for row in people
    )
    summary = ", ".join(selected_names) if selected_names else "All people"
    return f"""
        <details class="filter-dropdown people-match-dropdown" data-filter-key="person_id">
            <summary title="{esc(summary)}"><span>{esc(summary)}</span></summary>
            <div class="filter-dropdown-menu">
                <fieldset class="filter-match-options">
                    <legend>Match</legend>
                    <label class="radio-option"><input type="radio" name="person_match" value="any" {"checked" if match != "all" else ""}><span>Any selected person</span></label>
                    <label class="radio-option"><input type="radio" name="person_match" value="all" {"checked" if match == "all" else ""}><span>All selected people</span></label>
                </fieldset>
                <fieldset class="filter-people-options">
                    <legend>People</legend>
                    {checks}
                </fieldset>
            </div>
        </details>
    """


def index_page(filters: dict[str, object], errors: list[str] | None = None, form_values: dict[str, object] | None = None) -> bytes:
    items = fetch_items(filters)
    freezers = fetch_freezers()
    people = fetch_people()
    categories = fetch_categories()
    total_units = sum(float(item["quantity"]) for item in items)
    due_soon = sum(1 for item in items if item["use_by"] and 0 <= item["days_left"] <= 14)
    past_due = sum(1 for item in items if item["use_by"] and item["days_left"] < 0)
    buy_count = len(fetch_buy_items())
    current_path = return_path("/", filters)
    rows = "".join(item_row(item, current_path) for item in items) or """
        <tr>
            <td colspan="10" class="empty">No freezer items match this view.</td>
        </tr>
    """

    content = f"""
        <section class="stats-grid" aria-label="Inventory summary">
            <div><span>{len(items)}</span><p>Items tracked</p></div>
            <div><span>{total_units:g}</span><p>Total quantity</p></div>
            <a class="{stat_class(due_soon, "soon")}" href="/expiry?days=14"><span>{due_soon}</span><p>Use soon</p></a>
            <a class="{stat_class(past_due, "expired")}" href="/expiry?before={today_iso()}"><span>{past_due}</span><p>Expired Food</p></a>
            <a class="{"stat-warning" if buy_count else "stat-good"}" href="/buy"><span>{buy_count}</span><p>Buy</p></a>
        </section>
        <section class="layout">
            {item_form(form_values, errors or [], "/", "Add freezer item", form_values.get("person_ids", []) if form_values else [])}
            <section class="panel inventory-panel" data-scalable-table data-table-key="inventory" data-table-base-width="1120">
                <div class="panel-heading inventory-heading">
                    <div class="table-heading-row">
                        <h2>Inventory</h2>
                        <label class="table-scale-control" title="Adjust inventory table size">
                            <span>Table size</span>
                            <input type="range" min="45" max="100" step="5" value="100" data-table-scale>
                        </label>
                    </div>
                    <form method="get" action="/" class="filters" data-live-filter>
                        <input name="q" value="{esc(filter_scalar(filters, "q"))}" placeholder="Search food or notes">
                        {filter_dropdown("Categories", "category", [(row["name"], row["name"]) for row in categories], filter_values(filters, "category"))}
                        {filter_dropdown("Freezers", "freezer_id", [("unassigned", "Unassigned"), *[(str(row["id"]), row["name"]) for row in freezers]], filter_values(filters, "freezer_id"))}
                        {filter_dropdown("Food types", "ingredient", [("yes", "Ingredients"), ("no", "Non-ingredients")], filter_values(filters, "ingredient"))}
                        {people_filter_dropdown(people, filter_values(filters, "person_id"), filter_scalar(filters, "person_match"))}
                    </form>
                </div>
                <div class="table-wrap inventory-table-wrap">
                    <table class="inventory-table scalable-table">
                        <thead>
                            <tr>
                                <th>Food</th>
                                <th>Batch</th>
                                <th>Category</th>
                                <th>Qty</th>
                                <th>Freezer</th>
                                <th>People</th>
                                <th>Frozen</th>
                                <th>Use by</th>
                                <th>Status</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            </section>
        </section>
    """
    return render_page(content, "inventory")


def item_row(item: sqlite3.Row, return_to: str) -> str:
    notes = f'<p class="item-notes">{esc(item["notes"])}</p>' if item["notes"] else ""
    staple = '<span class="muted">House Staple</span>' if item["house_staple"] else ""
    ingredient = '<span class="muted">Ingredient</span>' if item["ingredient"] else ""
    people = item["people_names"] or "No one"
    use_by = esc(display_date(item["use_by"]))
    use_by_meta = f'<span class="muted">{use_by_label(item["use_by"])}</span>' if item["use_by"] else ""
    return f"""
        <tr>
            <td data-label="Food">
                <strong>{esc(item["name"])}</strong>
                {notes}
                {staple}
                {ingredient}
            </td>
            <td data-label="Batch"><span class="batch-id">{item["batch_number"]}</span></td>
            <td data-label="Category">{esc(item["category"])}</td>
            <td data-label="Qty"><div class="quantity-cell"><span>{esc(display_quantity(item))}</span>{stock_controls(item, return_to)}</div></td>
            <td data-label="Freezer">{esc(item["freezer_name"])}</td>
            <td data-label="People">{esc(people)}</td>
            <td data-label="Frozen">{esc(display_date(item["frozen_on"]))}<span class="muted">{age_label(item["frozen_on"])}</span></td>
            <td data-label="Use by">{use_by}{use_by_meta}</td>
            <td data-label="Status">{status_badge(item)}</td>
            <td data-label="Action" class="row-actions compact-actions">
                <div class="action-group">
                    <a class="action-button" href="/new?{urlencode({"copy": item["id"], "return_to": return_to})}" title="Add batch">Add batch</a>
                    <a class="action-button edit-action" href="/edit/{item["id"]}?{urlencode({"return_to": return_to})}" title="Edit" aria-label="Edit">{icon("edit")}</a>
                    <form method="post" action="/delete/{item["id"]}" data-confirm="Delete {esc(item["name"])} batch {item["batch_number"]}?">
                        <input type="hidden" name="return_to" value="{esc(return_to)}">
                        <button class="action-button danger-action delete-action" type="submit" title="Delete" aria-label="Delete">{icon("close")}</button>
                    </form>
                </div>
            </td>
        </tr>
    """


def pull_page(filters: dict[str, list[str]]) -> bytes:
    people = fetch_people()
    freezers = fetch_freezers()
    selected_ids = selected_people_from_form(filters)
    selected_freezers = filters.get("freezer_id", [])
    search = scalar_values(filters).get("q", "")
    match = scalar_values(filters).get("match", "any")
    ingredient_selected = "yes" in filters.get("ingredient", [])
    if match not in ("any", "all"):
        match = "any"
    items = fetch_pull_items(selected_ids, match, selected_freezers, search, ingredient_selected)
    current_path = return_path("/pull", filters)
    empty_message = "Select one or more people or Ingredients to build a pull list." if not selected_ids and not ingredient_selected else "No food matches this filter."
    rows = "".join(pull_row(item, current_path) for item in items) or f"""
        <tr><td colspan="6" class="empty">{esc(empty_message)}</td></tr>
    """
    content = f"""
        <section class="pull-layout">
            <aside class="panel filter-panel">
                <div class="panel-heading split">
                    <h2>Filter</h2>
                    <form method="get" action="/pull" data-auto-submit>
                        <button type="submit" class="icon-button reload-button" title="Refresh list" aria-label="Refresh list">{icon("reload")}</button>
                    </form>
                </div>
                <form method="get" action="/pull" class="pull-filters" data-auto-submit>
                    <fieldset class="match-picker freezer-picker">
                        <legend>Freezers</legend>
                        <label class="check-option">
                            <input type="checkbox" name="freezer_id" value="unassigned" {"checked" if "unassigned" in selected_freezers else ""}>
                            <span>Unassigned</span>
                        </label>
                        {checkbox_filter_rows(freezers, "freezer_id", selected_freezers)}
                    </fieldset>
                    <fieldset class="match-picker">
                        <legend>Food type</legend>
                        <label class="check-option">
                            <input type="checkbox" name="ingredient" value="yes" {"checked" if ingredient_selected else ""}>
                            <span>Ingredients</span>
                        </label>
                    </fieldset>
                    <fieldset class="match-picker">
                        <legend>Match</legend>
                        <label class="radio-option">
                            <input type="radio" name="match" value="any" {"checked" if match == "any" else ""}>
                            <span>Any selected person</span>
                        </label>
                        <label class="radio-option">
                            <input type="radio" name="match" value="all" {"checked" if match == "all" else ""}>
                            <span>All selected people</span>
                        </label>
                    </fieldset>
                    <fieldset class="match-picker people-filter">
                        <legend>People</legend>
                        <div class="vertical-checks">{checkbox_tags(people, selected_ids)}</div>
                    </fieldset>
                </form>
            </aside>
            <section class="panel inventory-panel" data-scalable-table data-table-key="pull" data-table-base-width="900">
                <div class="panel-heading split">
                    <h2>Pull Food</h2>
                    <div class="heading-actions">
                        <form method="get" action="/pull" class="pull-search" data-live-filter>
                            <input name="q" value="{esc(search)}" placeholder="Search food or notes">
                            {"".join(f'<input type="hidden" name="person_ids" value="{person_id}">' for person_id in selected_ids)}
                            {"".join(f'<input type="hidden" name="freezer_id" value="{esc(freezer_id)}">' for freezer_id in selected_freezers)}
                            {f'<input type="hidden" name="ingredient" value="yes">' if ingredient_selected else ""}
                            <input type="hidden" name="match" value="{esc(match)}">
                        </form>
                        <label class="table-scale-control" title="Adjust pull table size"><span>Table size</span><input type="range" min="45" max="100" step="5" value="100" data-table-scale></label>
                    </div>
                </div>
                <div class="table-wrap">
                    <table class="scalable-table">
                        <thead>
                            <tr>
                                <th>Food</th>
                                <th>Freezer</th>
                                <th>People</th>
                                <th>Qty</th>
                                <th>Use by</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            </section>
        </section>
    """
    return render_page(content, "pull")


def pull_row(item: sqlite3.Row, return_to: str) -> str:
    use_by_meta = f'<span class="muted">{use_by_label(item["use_by"])}</span>' if item["use_by"] else ""
    ingredient = '<span class="muted">Ingredient</span>' if item["ingredient"] else ""
    return f"""
        <tr>
            <td><strong>{esc(item["name"])}</strong><span class="muted">{esc(item["category"])}</span>{ingredient}</td>
            <td>{esc(item["freezer_name"])}</td>
            <td>{esc(item["people_names"] or "No one")}</td>
            <td><div class="quantity-cell"><span>{esc(display_quantity(item))}</span>{stock_controls(item, return_to)}</div></td>
            <td>{esc(display_date(item["use_by"]))}{use_by_meta}</td>
            <td>{status_badge(item)}</td>
        </tr>
    """


def buy_page() -> bytes:
    items = fetch_buy_items()
    rows = "".join(buy_row(item) for item in items) or """
        <tr><td colspan="7" class="empty">Nothing needs restocking right now.</td></tr>
    """
    content = f"""
        <section class="panel" data-scalable-table data-table-key="buy" data-table-base-width="980">
            <div class="panel-heading split">
                <h2>Buy</h2>
                <div class="heading-actions">
                    <a class="secondary" href="/reports/buy.csv">Export CSV</a>
                    <button class="secondary" type="button" onclick="window.print()">Print</button>
                    <label class="table-scale-control" title="Adjust buy table size"><span>Table size</span><input type="range" min="45" max="100" step="5" value="100" data-table-scale></label>
                </div>
            </div>
            <div class="table-wrap">
                <table class="scalable-table">
                    <thead>
                        <tr>
                            <th>Food</th>
                            <th>Reason</th>
                            <th>Qty</th>
                            <th>Threshold</th>
                            <th>Freezer</th>
                            <th>People</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
    """
    return render_page(content, "buy")


def buy_row(item: sqlite3.Row) -> str:
    return f"""
        <tr>
            <td><strong>{esc(item["name"])}</strong><span class="muted">{esc(item["category"])}</span></td>
            <td><span class="badge badge-warning">{esc(item["buy_reason"])}</span></td>
            <td>{esc(display_quantity(item))}</td>
            <td>{float(item["staple_threshold"]):g}</td>
            <td>{esc(item["freezer_name"])}</td>
            <td>{esc(item["people_names"] or "No one")}</td>
            <td class="row-actions">
                <form method="post" action="/buy/clear/{item["id"]}">
                    <button class="action-button" type="submit">Clear</button>
                </form>
            </td>
        </tr>
    """


def expiry_page(filters: dict[str, str]) -> bytes:
    days = int_or_none(filters.get("days")) or 30
    before = filters.get("before") or (date.today() + timedelta(days=days)).isoformat()
    items = fetch_expiry_items({**filters, "before": before, "days": str(days)})
    rows = "".join(expiry_row(item) for item in items) or """
        <tr><td colspan="7" class="empty">No food expires in this window.</td></tr>
    """
    content = f"""
        <section class="panel" data-scalable-table data-table-key="expiry" data-table-base-width="920">
            <div class="panel-heading table-toolbar-heading">
                <div class="table-heading-row">
                    <h2>Expiring Food</h2>
                    <label class="table-scale-control" title="Adjust expiry table size">
                        <span>Table size</span>
                        <input type="range" min="45" max="100" step="5" value="100" data-table-scale>
                    </label>
                </div>
                <form method="get" action="/expiry" class="filters" data-live-filter>
                    <a class="secondary" href="/reports/expiry.csv">Export CSV</a>
                    <button class="secondary" type="button" onclick="window.print()">Print</button>
                    <label class="inline-field">
                        <span>Days</span>
                        <input name="days" type="number" min="1" value="{esc(days)}">
                    </label>
                    <label class="inline-field">
                        <span>Before</span>
                        <input name="before" type="date" value="{esc(before)}">
                    </label>
                    <select name="ingredient" aria-label="Food type">
                        <option value="">All food types</option>
                        <option value="yes" {"selected" if filters.get("ingredient") == "yes" else ""}>Ingredients</option>
                        <option value="no" {"selected" if filters.get("ingredient") == "no" else ""}>Non-ingredients</option>
                    </select>
                    <button type="submit">Show dates</button>
                </form>
            </div>
            <div class="table-wrap">
                <table class="scalable-table">
                    <thead>
                        <tr>
                            <th>Food</th>
                            <th>Freezer</th>
                            <th>People</th>
                            <th>Qty</th>
                            <th>Frozen</th>
                            <th>Use by</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
    """
    return render_page(content, "expiry")


def expiry_row(item: sqlite3.Row) -> str:
    ingredient = '<span class="muted">Ingredient</span>' if item["ingredient"] else ""
    return f"""
        <tr>
            <td><strong>{esc(item["name"])}</strong><span class="muted">{esc(item["category"])}</span>{ingredient}</td>
            <td>{esc(item["freezer_name"])}</td>
            <td>{esc(item["people_names"] or "No one")}</td>
            <td>{esc(display_quantity(item))}</td>
            <td>{esc(display_date(item["frozen_on"]))}</td>
            <td>{esc(display_date(item["use_by"]))}<span class="muted">{use_by_label(item["use_by"])}</span></td>
            <td>{status_badge(item)}</td>
        </tr>
    """


def audit_settings_modal(return_to: str) -> str:
    colors = audit_colors()
    fields = "".join(
        f'<label><span>{esc(action)}</span><input type="color" name="{esc(action)}" value="{esc(color)}"></label>'
        for action, color in colors.items()
    )
    return f"""
        <div class="modal-backdrop" data-audit-settings-modal hidden>
            <section class="confirm-modal audit-settings-modal" role="dialog" aria-modal="true">
                <h2>Audit Colours</h2>
                <form method="post" action="/audit/settings" class="audit-colour-grid">
                    <input type="hidden" name="return_to" value="{esc(return_to)}">
                    {fields}
                    <div class="form-actions">
                        <button class="secondary" type="button" data-audit-settings-cancel>Cancel</button>
                        <button class="secondary" type="submit" formaction="/audit/settings/reset">Reset defaults</button>
                        <button class="primary" type="submit">Save colours</button>
                    </div>
                </form>
            </section>
        </div>
    """


def colour_preferences_modal(return_to: str) -> str:
    current_user = getattr(RENDER_CONTEXT, "user", None)
    palette = user_palette(current_user["id"]) if current_user else {
        "accent": normalize_hex_color(get_setting("accent_color", DEFAULT_ACCENT_COLOR)) or DEFAULT_ACCENT_COLOR,
        "info": normalize_hex_color(get_setting("info_color", "#2f5d7c")) or "#2f5d7c",
        "warning": normalize_hex_color(get_setting("warning_color", "#a4661b")) or "#a4661b",
        "danger": normalize_hex_color(get_setting("danger_color", "#a53d36")) or "#a53d36",
    }
    interface_fields = "".join(
        f'<label><span>{label}</span><input type="color" name="{key}" value="{esc(palette[key])}"></label>'
        for key, label in (
            ("accent", "Accent"),
            ("info", "Information"),
            ("warning", "Warning"),
            ("danger", "Danger"),
        )
    )
    audit_fields = "".join(
        f'<label><span>{esc(action)}</span><input type="color" name="{esc(action)}" value="{esc(color)}"></label>'
        for action, color in audit_colors().items()
    )
    metric_section = ""
    if current_user and current_user["role"] == "ADMIN":
        metric_colors = admin_metric_colors(current_user["id"])
        metric_fields = "".join(
            f'<label><span>{label}</span><input type="color" name="{key}" value="{esc(metric_colors[key])}"></label>'
            for key, label in (
                ("cpu_percent", "CPU"),
                ("ram_percent", "RAM"),
                ("app_storage_bytes", "App storage"),
            )
        )
        metric_section = f"""
            <form method="post" action="/admin/metric-colors" class="preference-card" data-preference-form data-reset-action="/admin/metric-colors/reset">
                <div class="preference-section-heading"><h3>Statistics</h3><span>Admin resource charts</span></div>
                <div class="preference-colour-grid">{metric_fields}</div>
                <div class="form-actions">
                    <button class="secondary" type="submit" formaction="/admin/metric-colors/reset">Reset</button>
                </div>
            </form>
        """
    return f"""
        <div class="modal-backdrop" data-palette-settings-modal hidden>
            <section class="confirm-modal preferences-modal" role="dialog" aria-modal="true">
                <div class="preferences-modal-heading">
                    <h2>Colour Preferences</h2>
                    <div class="preferences-modal-actions">
                        <button class="primary" type="button" data-preferences-save-all>Save</button>
                        <button class="secondary" type="button" data-preferences-reset-all>Reset all</button>
                        <button class="icon-button" type="button" aria-label="Close colour preferences" title="Close" data-palette-settings-cancel>{icon("close")}</button>
                    </div>
                </div>
                <div class="preference-card-grid {"has-admin-card" if metric_section else ""}">
                    {metric_section}
                    <form method="post" action="/appearance/settings" class="preference-card" data-preference-form data-reset-action="/appearance/settings/reset">
                        <input type="hidden" name="return_to" value="{esc(return_to)}">
                        <div class="preference-section-heading"><h3>Interface</h3><span>Navigation, notices and status colours</span></div>
                        <div class="preference-colour-grid">{interface_fields}</div>
                        <div class="form-actions">
                            <button class="secondary" type="submit" formaction="/appearance/settings/reset">Reset</button>
                        </div>
                    </form>
                    <form method="post" action="/audit/settings" class="preference-card" data-preference-form data-reset-action="/audit/settings/reset">
                        <input type="hidden" name="return_to" value="{esc(return_to)}">
                        <div class="preference-section-heading"><h3>Audit Logs</h3><span>Event badge colours</span></div>
                        <div class="preference-colour-grid audit-preference-grid">{audit_fields}</div>
                        <div class="form-actions">
                            <button class="secondary" type="submit" formaction="/audit/settings/reset">Reset</button>
                        </div>
                    </form>
                </div>
            </section>
        </div>
    """


def audit_page(filters: dict[str, list[str]] | None = None) -> bytes:
    filters = filters or {}
    selected_actions = filters.get("action", [])
    search = filters.get("q", [""])[0]
    events = fetch_audit_events(actions=selected_actions, search=search)
    with get_connection() as conn:
        actions = [row["action"] for row in conn.execute("SELECT DISTINCT action FROM audit_events ORDER BY action")]
    rows = "".join(audit_row(event) for event in events) or """
        <tr><td colspan="6" class="empty">No audit events yet.</td></tr>
    """
    action_checks = "".join(
        f'<label class="check-option"><input type="checkbox" name="action" value="{esc(action)}" {"checked" if action in selected_actions else ""}><span>{esc(action)}</span></label>'
        for action in actions
    )
    content = f"""
        <section class="panel">
            <div class="panel-heading split">
                <h2>Audit Log</h2>
                <button class="icon-button" type="button" title="Audit colour settings" aria-label="Audit colour settings" data-audit-settings-open>{icon("settings")}</button>
            </div>
            <form method="get" action="/audit" class="audit-filters" data-live-filter>
                <input name="q" value="{esc(search)}" placeholder="Search audit events">
                <div class="inline-checks">{action_checks}</div>
            </form>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>When</th>
                            <th>User</th>
                            <th>Source</th>
                            <th>Action</th>
                            <th>Food</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
        {colour_preferences_modal("/audit")}
    """
    return render_page(content, "audit")


def audit_row(event: sqlite3.Row) -> str:
    username = event["username"] or "Not logged in"
    source = event["ip_address"] or "Unknown IP"
    device = event["device_name"] or "Unknown device"
    agent = event["user_agent"] or ""
    return f"""
        <tr>
            <td>{esc(event["created_at"])}</td>
            <td><strong>{esc(username)}</strong></td>
            <td>{esc(source)}<span class="muted">{esc(device)}</span><span class="muted">{esc(agent)}</span></td>
            <td>{audit_badge(event["action"])}</td>
            <td><strong>{esc(event["item_name"])}</strong></td>
            <td><pre class="audit-details">{esc(event["details"])}</pre></td>
        </tr>
    """


def audit_preview_row(event: sqlite3.Row) -> str:
    created_at = str(event["created_at"] or "")
    date_part, _, time_part = created_at.partition(" ")
    shown_date = display_date(date_part) if date_part else "Unknown"
    shown_time = time_part[:8] if time_part else ""
    item_name = event["item_name"] or "Unknown item"
    return f"""
        <tr>
            <td><span class="audit-preview-date">{esc(shown_date)}</span><span class="muted">{esc(shown_time)}</span></td>
            <td>{esc(event["username"] or "Not logged in")}</td>
            <td>{audit_badge(event["action"])}</td>
            <td><strong class="audit-food-name" title="{esc(item_name)}">{esc(item_name)}</strong></td>
        </tr>
    """


def stats_page() -> bytes:
    current_user = getattr(RENDER_CONTEXT, "user", None)
    by_item, recent = fetch_stock_stats()
    distribution = fetch_inventory_distribution()
    item_rows = "".join(stats_item_row(row) for row in by_item) or """
        <tr><td colspan="5" class="empty">No stock history yet.</td></tr>
    """
    recent_rows = "".join(stats_event_preview_row(row) for row in recent) or """
        <tr><td colspan="4" class="empty">No stock events yet.</td></tr>
    """
    popular = [row for row in by_item if float(row["removed"] or 0) > 0][:8]
    max_removed = max((float(row["removed"] or 0) for row in popular), default=1)
    popular_bars = "".join(
        f"""
        <div class="bar-chart-row">
            <span title="{esc(row["item_name"])}">{esc(row["item_name"])}</span>
            <div><i style="width:{max(3, float(row["removed"] or 0) / max_removed * 100):.2f}%"></i></div>
            <strong>{float(row["removed"] or 0):g}</strong>
        </div>
        """
        for row in popular
    ) or '<p class="empty">Stock usage will appear after items are removed.</p>'
    chart_colors = ["#2f6f4f", "#c99a13", "#4b78a8", "#a8473f", "#7b5ba7", "#3f8b8b", "#8a6b3f", "#6d7f45"]
    total_quantity = sum(float(row["quantity"] or 0) for row in distribution)
    angle = 0.0
    slices: list[str] = []
    legend: list[str] = []
    for index, row in enumerate(distribution[:8]):
        quantity = float(row["quantity"] or 0)
        portion = quantity / total_quantity * 100 if total_quantity else 0
        end = angle + portion
        color = chart_colors[index % len(chart_colors)]
        slices.append(f"{color} {angle:.2f}% {end:.2f}%")
        legend.append(
            f'<li><i style="background:{color}"></i><span title="{esc(row["item_name"])}">{esc(row["item_name"])}</span><strong>{quantity:g}</strong></li>'
        )
        angle = end
    if len(distribution) > 8:
        remaining = sum(float(row["quantity"] or 0) for row in distribution[8:])
        portion = remaining / total_quantity * 100 if total_quantity else 0
        slices.append(f"#aeb9b4 {angle:.2f}% 100%")
        legend.append(f'<li><i style="background:#aeb9b4"></i><span>Other</span><strong>{remaining:g}</strong></li>')
    pie_style = f' style="background:conic-gradient({", ".join(slices)})"' if slices else ""
    content = f"""
        <section class="manage-layout">
            <div class="manage-columns wide-panel">
                <div class="manage-column">
                    <section class="panel">
                        <div class="panel-heading split"><h2>Most Used Food</h2>{'<form method="post" action="/stats/reset" data-confirm="Reset usage statistics from this point forward? Stock event history will be kept."><button class="secondary danger-text" type="submit">Reset stats</button></form>' if current_user and current_user["role"] == "ADMIN" else ""}</div>
                        <div class="chart-body bar-chart">{popular_bars}</div>
                    </section>
                    <section class="panel">
                        <div class="panel-heading"><h2>Stock Usage</h2></div>
                        <div class="table-wrap">
                            <table>
                                <thead><tr><th>Food</th><th>Unit</th><th>Added</th><th>Removed</th><th>Changes</th></tr></thead>
                                <tbody>{item_rows}</tbody>
                            </table>
                        </div>
                    </section>
                </div>
                <div class="manage-column">
                    <section class="panel">
                        <div class="panel-heading"><h2>Freezer Space by Quantity</h2></div>
                        <div class="chart-body pie-chart-layout">
                            <div class="pie-chart"{pie_style} aria-label="Current freezer quantity distribution"></div>
                            <ul class="chart-legend">{"".join(legend) or "<li>No inventory data yet.</li>"}</ul>
                        </div>
                    </section>
                    <section class="panel stock-events-preview">
                        <div class="panel-heading split">
                            <h2>Recent Stock Events</h2>
                            <a class="secondary" href="/stats/events">Full Data</a>
                        </div>
                        <div class="stock-events-preview-wrap internal-scroll">
                            <table class="stock-events-preview-table">
                                <thead><tr><th>Date</th><th>Food</th><th>Action</th><th>Change</th></tr></thead>
                                <tbody>{recent_rows}</tbody>
                            </table>
                        </div>
                    </section>
                </div>
            </div>
        </section>
    """
    return render_page(content, "stats")


def stock_events_page() -> bytes:
    current_user = getattr(RENDER_CONTEXT, "user", None)
    _by_item, recent = fetch_stock_stats(5000)
    rows = "".join(stats_event_row(row) for row in recent) or """
        <tr><td colspan="6" class="empty">No stock events yet.</td></tr>
    """
    content = f"""
        <section class="panel">
            <div class="panel-heading split">
                <h2>Stock Events</h2>
                <div class="heading-actions">
                    <a class="secondary" href="/reports/stock.csv">Export CSV</a>
                    <button class="secondary" type="button" onclick="window.print()">Print</button>
                    {f'<form method="post" action="/stats/events/reset" data-confirm="Reset all stock events and usage statistics? The archived data will remain available to administrators for 90 days."><button class="secondary danger-text" type="submit">Reset events</button></form>' if current_user and current_user["role"] == "ADMIN" else ""}
                </div>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>When</th><th>Food</th><th>Action</th><th>Before</th><th>After</th><th>Source</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
    """
    return render_page(content, "stats")


def stock_event_archive_card() -> str:
    archives = fetch_stock_event_archives()
    rows = "".join(
        f"""
        <tr>
            <td><strong>{esc(row["archived_by"] or "Unknown admin")}</strong><span class="muted">{esc(row["archived_ip"] or "Unknown IP")}</span></td>
            <td>{esc(row["archived_at"])}</td>
            <td>{row["event_count"]}</td>
            <td class="row-actions"><a class="action-button" href="/admin/stock-event-archive?batch={esc(row["archive_batch"])}">View</a></td>
        </tr>
        """
        for row in archives[:8]
    ) or '<tr><td colspan="4" class="empty">No stock-event resets in the last 90 days.</td></tr>'
    return f"""
        <section class="panel">
            <div class="panel-heading split">
                <h2>Stock Event Reset History</h2>
                <a class="secondary" href="/admin/stock-event-archive">Full Data</a>
            </div>
            <div class="table-wrap internal-scroll compact-admin-table-wrap">
                <table class="compact-admin-table reset-history-table">
                    <thead><tr><th>Reset by</th><th>When</th><th>Events</th><th class="action-heading">Action</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
    """


def archived_stock_events_page(batch: str = "") -> bytes:
    events = fetch_archived_stock_events(batch)
    rows = "".join(
        f"""
        <tr>
            <td>{esc(row["archived_at"])}</td>
            <td><strong>{esc(row["archived_by"] or "Unknown admin")}</strong><span class="muted">{esc(row["archived_ip"] or "Unknown IP")} · {esc(row["archived_device"] or "Unknown device")}</span></td>
            <td>{esc(row["created_at"])}</td>
            <td><strong>{esc(row["item_name"])}</strong><span class="muted">{esc(row["unit"] or "")}</span></td>
            <td>{esc(row["action"])}</td>
            <td>{'' if row["quantity_before"] is None else f'{float(row["quantity_before"]):g}'} → {'' if row["quantity_after"] is None else f'{float(row["quantity_after"]):g}'}</td>
        </tr>
        """
        for row in events
    ) or '<tr><td colspan="6" class="empty">No retained stock events match this archive.</td></tr>'
    content = f"""
        <section class="panel">
            <div class="panel-heading split">
                <div><h2>Archived Stock Events</h2><span class="muted">Retained for 90 days after reset.</span></div>
                <a class="secondary" href="/admin">Back to Admin</a>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Reset when</th><th>Reset by</th><th>Event when</th><th>Food</th><th>Action</th><th>Quantity</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
    """
    return render_page(content, "admin")


def stats_reset_history_card() -> str:
    resets = fetch_stats_reset_history()
    rows = "".join(
        f"""
        <tr>
            <td><strong>{esc(row["reset_by"] or "Unknown admin")}</strong><span class="muted">{esc(row["reset_ip"] or "Unknown IP")}</span></td>
            <td>{esc(row["reset_at"])}</td>
            <td>{row["item_count"]} foods<span class="muted">{row["event_count"]} events</span></td>
            <td class="row-actions"><a class="action-button" href="/admin/stats-reset-archive?id={row["id"]}">View</a></td>
        </tr>
        """
        for row in resets[:8]
    ) or '<tr><td colspan="4" class="empty">No statistics resets in the last 90 days.</td></tr>'
    return f"""
        <section class="panel">
            <div class="panel-heading split">
                <h2>Statistics Reset History</h2>
                <a class="secondary" href="/admin/stats-reset-archive">Full Data</a>
            </div>
            <div class="table-wrap internal-scroll compact-admin-table-wrap">
                <table class="compact-admin-table reset-history-table">
                    <thead><tr><th>Reset by</th><th>When</th><th>Preserved</th><th class="action-heading">Action</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
    """


def archived_stats_page(reset_id: int | None = None) -> bytes:
    resets = [fetch_stats_reset(reset_id)] if reset_id else fetch_stats_reset_history()
    resets = [row for row in resets if row]
    sections = []
    for reset in resets:
        try:
            snapshot = json.loads(reset["snapshot_json"])
        except json.JSONDecodeError:
            snapshot = []
        rows = "".join(
            f"""
            <tr>
                <td><strong>{esc(row.get("item_name", ""))}</strong></td>
                <td>{esc(row.get("unit", ""))}</td>
                <td>{float(row.get("added") or 0):g}</td>
                <td>{float(row.get("removed") or 0):g}</td>
                <td>{int(row.get("changes") or 0)}</td>
            </tr>
            """
            for row in snapshot
        ) or '<tr><td colspan="5" class="empty">This reset contained no usage statistics.</td></tr>'
        sections.append(
            f"""
            <section class="panel">
                <div class="panel-heading">
                    <h2>{esc(reset["reset_at"])}</h2>
                    <span class="muted">Reset by {esc(reset["reset_by"] or "Unknown admin")} from {esc(reset["reset_ip"] or "Unknown IP")} · {esc(reset["reset_device"] or "Unknown device")}</span>
                </div>
                <div class="table-wrap">
                    <table>
                        <thead><tr><th>Food</th><th>Unit</th><th>Added</th><th>Removed</th><th>Changes</th></tr></thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            </section>
            """
        )
    content = f"""
        <div class="panel-heading split archive-page-heading">
            <div><h2>Archived Usage Statistics</h2><span class="muted">Preserved for 90 days after reset.</span></div>
            <a class="secondary" href="/admin">Back to Admin</a>
        </div>
        {"".join(sections) or '<section class="panel"><div class="empty">No retained statistics resets found.</div></section>'}
    """
    return render_page(content, "admin")


def stats_item_row(row: sqlite3.Row) -> str:
    return f"""
        <tr>
            <td><strong>{esc(row["item_name"])}</strong></td>
            <td>{esc(row["unit"])}</td>
            <td>{float(row["added"] or 0):g}</td>
            <td>{float(row["removed"] or 0):g}</td>
            <td>{row["changes"]}</td>
        </tr>
    """


def stats_event_row(row: sqlite3.Row) -> str:
    return f"""
        <tr>
            <td>{esc(row["created_at"])}</td>
            <td><strong>{esc(row["item_name"])}</strong><span class="muted">{esc(row["unit"])}</span></td>
            <td>{esc(row["action"])}</td>
            <td>{'' if row["quantity_before"] is None else f'{float(row["quantity_before"]):g}'}</td>
            <td>{'' if row["quantity_after"] is None else f'{float(row["quantity_after"]):g}'}</td>
            <td>{esc(row["ip_address"] or "")}<span class="muted">{esc(row["device_name"] or "")}</span></td>
        </tr>
    """


def stats_event_preview_row(row: sqlite3.Row) -> str:
    created_at = str(row["created_at"] or "")
    date_part, _, time_part = created_at.partition(" ")
    delta = row["delta"]
    change = "" if delta is None else f"{float(delta):+g} {row['unit'] or ''}".strip()
    return f"""
        <tr>
            <td><span class="audit-preview-date">{esc(display_date(date_part))}</span><span class="muted">{esc(time_part[:8])}</span></td>
            <td><strong class="audit-food-name" title="{esc(row["item_name"])}">{esc(row["item_name"])}</strong></td>
            <td>{audit_badge(row["action"])}</td>
            <td>{esc(change)}</td>
        </tr>
    """


def server_config_card(config_errors: list[str] | None = None, config_notice: str = "") -> str:
    config = read_config()
    current_user = getattr(RENDER_CONTEXT, "user", None)
    can_upload_favicon = config["AUTH_OPT"] == "NONE" or bool(current_user and current_user["role"] == "ADMIN")
    log_max_mb = get_setting("log_max_mb", str(DEFAULT_LOG_MAX_MB))
    app_title = get_setting("app_title", DEFAULT_APP_TITLE)
    app_eyebrow = get_setting("app_eyebrow", DEFAULT_APP_EYEBROW)
    return f"""
        <section class="panel">
            <div class="panel-heading"><h2>Server Config</h2></div>
            {notice(config_errors or []) if config_errors else ""}
            {f'<div class="notice info">{esc(config_notice)}</div>' if config_notice else ""}
            <form method="post" action="/manage/config" class="item-form compact-form">
                <label>
                    <span>Network access</span>
                    <select name="auth_opt">
                        <option value="NONE" {"selected" if config["AUTH_OPT"] == "NONE" else ""}>Anyone can view and edit</option>
                        <option value="EDIT" {"selected" if config["AUTH_OPT"] == "EDIT" else ""}>Login required to make changes</option>
                        <option value="VIEW" {"selected" if config["AUTH_OPT"] == "VIEW" else ""}>Login required to view</option>
                    </select>
                </label>
                <div class="field-row three-field-row">
                    <label><span>Bind IP</span><input name="ip" value="{esc(config["IP"])}" placeholder="0.0.0.0"></label>
                    <label><span>Port</span><input name="port" type="number" min="1" max="65535" required value="{esc(config["PORT"])}"></label>
                    <label><span>Maximum log size (MB)</span><input name="log_max_mb" type="number" min="1" max="1024" required value="{esc(log_max_mb)}"></label>
                </div>
                <label><span>Application title</span><input name="app_title" required value="{esc(app_title)}"></label>
                <label><span>Header text above title</span><input name="app_eyebrow" required value="{esc(app_eyebrow)}"></label>
                {f'''
                <label>
                    <span>Favicon (PNG or ICO)</span>
                    <input type="file" accept=".png,.ico,image/png,image/x-icon" data-favicon-file>
                    <input type="hidden" name="favicon_data" data-favicon-data>
                </label>
                ''' if can_upload_favicon else ""}
                <div class="form-actions">
                    <button class="primary" type="submit">Save config</button>
                    <button class="secondary" type="submit" formaction="/manage/config/reset">Reset defaults</button>
                </div>
            </form>
        </section>
    """


def server_log_settings_modal(return_to: str) -> str:
    preferences = server_log_preferences(getattr(RENDER_CONTEXT, "user", None))
    theme_options = "".join(
        f'<option value="{esc(key)}" data-background="{esc(background)}" data-text="{esc(text)}" '
        f'{"selected" if preferences["theme"] == key else ""}>{esc(name)}</option>'
        for key, (name, background, text) in SERVER_LOG_THEMES.items()
    )
    theme_options += f'<option value="custom" {"selected" if preferences["theme"] == "custom" else ""}>Custom</option>'
    return f"""
        <div class="modal-backdrop" data-server-log-settings-modal hidden>
            <section class="confirm-modal server-log-settings-modal" role="dialog" aria-modal="true" aria-labelledby="server-log-settings-title">
                <div class="preferences-modal-heading">
                    <h2 id="server-log-settings-title">Server Log</h2>
                    <button class="icon-button" type="button" title="Close" aria-label="Close" data-server-log-settings-cancel>{icon("close")}</button>
                </div>
                <form method="post" action="/server-log/settings" class="server-log-settings-form">
                    <input type="hidden" name="return_to" value="{esc(return_to)}">
                    <label>
                        <span>Theme</span>
                        <select name="theme" data-server-log-theme>{theme_options}</select>
                    </label>
                    <label>
                        <span>Preview history lines</span>
                        <input name="history_length" type="number" min="5" max="1000" step="1" value="{esc(preferences["history_length"])}">
                    </label>
                    <div class="field-row">
                        <label><span>Background</span><input name="background" type="color" value="{esc(preferences["background"])}" data-server-log-background></label>
                        <label><span>Text</span><input name="text" type="color" value="{esc(preferences["text"])}" data-server-log-text></label>
                    </div>
                    <pre class="server-log-theme-preview" data-server-log-theme-preview style="--server-log-bg: {esc(preferences["background"])}; --server-log-text: {esc(preferences["text"])}">[14:02:18] 10.0.20.12 "GET /api/version HTTP/1.1" 200</pre>
                    <div class="form-actions">
                        <button class="secondary" type="submit" formaction="/server-log/settings/reset">Reset</button>
                        <button class="primary" type="submit">Save settings</button>
                    </div>
                </form>
            </section>
        </div>
    """


def server_log_card() -> str:
    preferences = server_log_preferences(getattr(RENDER_CONTEXT, "user", None))
    return f"""
        <section class="panel log-preview-card">
            <div class="panel-heading split">
                <h2>Server Log</h2>
                <div class="heading-actions">
                    <button class="icon-button" type="button" title="Server log settings" aria-label="Server log settings" data-server-log-settings-open>{icon("settings")}</button>
                    <a class="secondary" href="/logs">Full Logs</a>
                </div>
            </div>
            <pre class="log-preview" data-live-server-log data-log-limit="{esc(preferences["history_length"])}" style="--server-log-bg: {esc(preferences["background"])}; --server-log-text: {esc(preferences["text"])}">{esc(log_tail(int(preferences["history_length"])))}</pre>
        </section>
        {server_log_settings_modal("/admin" if read_config()["AUTH_OPT"] != "NONE" else "/manage")}
    """


def backup_card() -> str:
    return """
        <section class="panel backup-card">
            <div class="panel-heading"><h2>Backup &amp; Restore</h2></div>
            <div class="backup-grid">
                <div>
                    <h3>Download backup</h3>
                    <div class="backup-download-actions">
                        <a class="secondary" href="/admin/backup?mode=settings">Settings only</a>
                        <a class="primary" href="/admin/backup?mode=full">Whole dataset</a>
                    </div>
                </div>
                <form method="post" action="/admin/restore" class="item-form compact-form backup-restore-form" data-confirm="Restoring a backup replaces current data. Continue?">
                    <h3>Restore backup</h3>
                    <label><span>Backup type</span><select name="mode"><option value="settings">Settings only</option><option value="full">Whole dataset</option></select></label>
                    <label><span>Backup file</span><input type="file" accept=".json,.zip,application/json,application/zip" required data-backup-file></label>
                    <input type="hidden" name="backup_data" data-backup-data>
                    <button class="primary" type="submit">Restore</button>
                </form>
            </div>
        </section>
    """


def manage_page(
    errors: list[str] | None = None,
    edit_freezer: sqlite3.Row | None = None,
    edit_person: sqlite3.Row | None = None,
    edit_unit: sqlite3.Row | None = None,
    edit_category: sqlite3.Row | None = None,
    log_errors: list[str] | None = None,
    config_errors: list[str] | None = None,
    config_notice: str = "",
) -> bytes:
    freezers = fetch_freezers()
    people = fetch_people_with_stats()
    units = fetch_units()
    categories = fetch_categories()
    foods = fetch_items({})
    log_max_mb = get_setting("log_max_mb", str(DEFAULT_LOG_MAX_MB))
    accent_color = normalize_hex_color(get_setting("accent_color", DEFAULT_ACCENT_COLOR)) or DEFAULT_ACCENT_COLOR
    date_format = get_setting("date_format", DEFAULT_DATE_FORMAT)
    app_title = get_setting("app_title", DEFAULT_APP_TITLE)
    app_eyebrow = get_setting("app_eyebrow", DEFAULT_APP_EYEBROW)
    config = read_config()
    auth_enabled = config["AUTH_OPT"] != "NONE"
    current_user = getattr(RENDER_CONTEXT, "user", None)
    can_upload_favicon = config["AUTH_OPT"] == "NONE" or bool(current_user and current_user["role"] == "ADMIN")
    recent_audit = fetch_audit_events(5)
    audit_preview_rows = "".join(audit_preview_row(event) for event in recent_audit) or (
        '<tr><td colspan="4" class="empty">No audit events yet.</td></tr>'
    )
    freezer_rows = "".join(manage_row("freezer", row, "/manage/freezers") for row in freezers) or empty_manage_row()
    people_rows = "".join(manage_person_row(row) for row in people) or empty_manage_row()
    unit_rows = "".join(manage_row("unit", row, "/manage/units") for row in units) or empty_manage_row()
    category_rows = "".join(manage_row("category", row, "/manage/categories") for row in categories) or empty_manage_row()
    food_rows = "".join(food_manage_row(row) for row in foods) or empty_food_row()
    freezer_action = f"/manage/freezers/edit/{edit_freezer['id']}" if edit_freezer else "/manage/freezers"
    person_action = f"/manage/people/edit/{edit_person['id']}" if edit_person else "/manage/people"
    unit_action = f"/manage/units/edit/{edit_unit['id']}" if edit_unit else "/manage/units"
    category_action = f"/manage/categories/edit/{edit_category['id']}" if edit_category else "/manage/categories"

    content = f"""
        <section class="manage-layout">
            <div class="manage-columns wide-panel">
                <div class="manage-column">
                    <section class="panel">
                        <div class="panel-heading"><h2>Freezers</h2></div>
                        {notice(errors or []) if errors else ""}
                        {manage_form(freezer_action, edit_freezer, "Freezer name", "Chest freezer", "freezer")}
                        <div class="table-wrap"><table class="manage-table"><tbody>{freezer_rows}</tbody></table></div>
                    </section>
                    <section class="panel">
                        <div class="panel-heading"><h2>Units</h2></div>
                        {manage_form(unit_action, edit_unit, "Unit name", "bag", "unit")}
                        <div class="table-wrap"><table class="manage-table"><tbody>{unit_rows}</tbody></table></div>
                    </section>
                    <section class="panel">
                        <div class="panel-heading split">
                            <h2>Appearance</h2>
                            <button class="icon-button" type="button" title="Interface colour settings" aria-label="Interface colour settings" data-palette-settings-open>{icon("settings")}</button>
                        </div>
                        {notice(log_errors or []) if log_errors else ""}
                        <form method="post" action="/manage/log" class="item-form compact-form">
                            <div class="field-row">
                                <label>
                                    <span>Accent colour</span>
                                    <input name="accent_color" type="color" value="{esc(accent_color)}">
                                </label>
                                <label>
                                    <span>Date format</span>
                                    <select name="date_format">{option_tags(list(DATE_FORMATS.keys()), date_format)}</select>
                                </label>
                            </div>
                            <div class="form-actions">
                                <button class="primary" type="submit">Save</button>
                                <button class="secondary" type="submit" formaction="/manage/log/reset">Reset defaults</button>
                            </div>
                        </form>
                    </section>
                    <section class="panel audit-preview-card">
                        <div class="panel-heading split">
                            <h2>Recent Audit Activity</h2>
                            <div class="heading-actions">
                                <button class="icon-button compact-reload" type="button" title="Audit colour settings" aria-label="Audit colour settings" data-audit-settings-open>{icon("settings")}</button>
                                <button class="icon-button reload-button compact-reload" type="button" title="Refresh audit activity" aria-label="Refresh audit activity" data-refresh-main>{icon("reload")}</button>
                                <a class="secondary" href="/audit">Full Logs</a>
                            </div>
                        </div>
                        <div class="audit-preview-wrap">
                            <table class="audit-preview-table">
                                <thead><tr><th>Date</th><th>User</th><th>Action</th><th>Food</th></tr></thead>
                                <tbody>{audit_preview_rows}</tbody>
                            </table>
                        </div>
                    </section>
                </div>
                <div class="manage-column">
                    <section class="panel">
                        <div class="panel-heading"><h2>People</h2></div>
                        {manage_form(person_action, edit_person, "Person name", "Alex", "person")}
                        <div class="table-wrap"><table class="manage-table"><tbody>{people_rows}</tbody></table></div>
                    </section>
                    <section class="panel">
                        <div class="panel-heading"><h2>Categories</h2></div>
                        {manage_form(category_action, edit_category, "Category name", "Prepared meal", "category")}
                        <div class="table-wrap"><table class="manage-table"><tbody>{category_rows}</tbody></table></div>
                    </section>
                    <section class="panel {"auth-admin-only" if auth_enabled else ""}">
                        <div class="panel-heading"><h2>Server Config</h2></div>
                        {notice(config_errors or []) if config_errors else ""}
                        {f'<div class="notice info">{esc(config_notice)}</div>' if config_notice else ""}
                        <form method="post" action="/manage/config" class="item-form compact-form">
                            <label>
                                <span>Network access</span>
                                <select name="auth_opt">
                                    <option value="NONE" {"selected" if config["AUTH_OPT"] == "NONE" else ""}>Anyone can view and edit</option>
                                    <option value="EDIT" {"selected" if config["AUTH_OPT"] == "EDIT" else ""}>Login required to make changes</option>
                                    <option value="VIEW" {"selected" if config["AUTH_OPT"] == "VIEW" else ""}>Login required to view</option>
                                </select>
                            </label>
                            <div class="field-row three-field-row">
                                <label>
                                    <span>Bind IP</span>
                                    <input name="ip" value="{esc(config["IP"])}" placeholder="0.0.0.0">
                                </label>
                                <label>
                                    <span>Port</span>
                                    <input name="port" type="number" min="1" max="65535" required value="{esc(config["PORT"])}">
                                </label>
                                <label>
                                    <span>Maximum log size (MB)</span>
                                    <input name="log_max_mb" type="number" min="1" max="1024" required value="{esc(log_max_mb)}">
                                </label>
                            </div>
                            <label>
                                <span>Application title</span>
                                <input name="app_title" required value="{esc(app_title)}">
                            </label>
                            <label>
                                <span>Header text above title</span>
                                <input name="app_eyebrow" required value="{esc(app_eyebrow)}">
                            </label>
                            {f'''
                            <label>
                                <span>Favicon (PNG or ICO)</span>
                                <input type="file" accept=".png,.ico,image/png,image/x-icon" data-favicon-file>
                                <input type="hidden" name="favicon_data" data-favicon-data>
                            </label>
                            ''' if can_upload_favicon else ""}
                            <div class="form-actions">
                                <button class="primary" type="submit">Save config</button>
                                <button class="secondary" type="submit" formaction="/manage/config/reset">Reset defaults</button>
                            </div>
                        </form>
                    </section>
                    {profile_card(current_user, bool(current_user and current_user["must_change_password"])) if current_user else ""}
                    {server_log_card() if not auth_enabled else ""}
                </div>
            </div>
            <section class="panel wide-panel" data-scalable-table data-table-key="manage-foods" data-table-base-width="920">
                <div class="panel-heading split">
                    <h2>Existing Foods</h2>
                    <div class="heading-actions">
                        <label class="table-scale-control existing-foods-scale" title="Adjust foods table size">
                            <span>Table size</span>
                            <input type="range" min="45" max="100" step="5" value="100" data-table-scale>
                        </label>
                        <a class="secondary" href="/foods">Full Data</a>
                        <a class="secondary" href="/new">Add food</a>
                    </div>
                </div>
                <div class="table-wrap existing-foods-scroll">
                    <table class="scalable-table">
                        <thead>
                            <tr>
                                <th>Food</th>
                                <th>Freezer</th>
                                <th>People</th>
                                <th>Qty</th>
                                <th>Use by</th>
                                <th class="action-heading">Action</th>
                            </tr>
                        </thead>
                        <tbody>{food_rows}</tbody>
                    </table>
                </div>
            </section>
            {colour_preferences_modal("/manage")}
        </section>
    """
    return render_page(content, "manage")


def foods_page(filters: dict[str, object]) -> bytes:
    foods = fetch_items(filters)
    rows = "".join(food_manage_row(row, "/foods") for row in foods) or empty_food_row()
    content = f"""
        <section class="panel">
            <div class="panel-heading split">
                <h2>All Foods</h2>
                <form method="get" action="/foods" class="filters" data-live-filter>
                    <input name="q" value="{esc(filter_scalar(filters, "q"))}" placeholder="Search food or notes">
                    {filter_dropdown("Food types", "ingredient", [("yes", "Ingredients"), ("no", "Non-ingredients")], filter_values(filters, "ingredient"))}
                    <a class="secondary" href="/new?return_to=/foods">Add food</a>
                </form>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Food</th><th>Freezer</th><th>People</th><th>Qty</th><th>Use by</th><th class="action-heading">Action</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </section>
    """
    return render_page(content, "manage")


def manage_form(action: str, row: sqlite3.Row | None, label: str, placeholder: str, focus_key: str) -> str:
    name = row["name"] if row else ""
    notes = row["notes"] if row else ""
    return f"""
        <form method="post" action="{esc(action)}" class="item-form compact-form">
            <label>
                <span>{esc(label)}</span>
                <input name="name" required value="{esc(name)}" placeholder="{esc(placeholder)}" data-focus="{esc(focus_key)}">
            </label>
            <label>
                <span>Notes</span>
                <input name="notes" value="{esc(notes)}" placeholder="Optional">
            </label>
            <div class="form-actions">
                <button class="primary" type="submit">Save</button>
                <a class="secondary" href="/manage">Clear</a>
            </div>
        </form>
    """


def manage_row(kind: str, row: sqlite3.Row, base: str) -> str:
    return f"""
        <tr>
            <td><strong>{esc(row["name"])}</strong><span class="muted">{esc(row["notes"])}</span></td>
            <td class="row-actions">
                <a class="action-button edit-action" href="{base}/edit/{row["id"]}" title="Edit" aria-label="Edit">{icon("edit")}</a>
                <form method="post" action="{base}/delete/{row["id"]}" data-confirm="Delete {esc(row["name"])}?">
                    <button class="action-button danger-action delete-action" type="submit" title="Delete" aria-label="Delete">{icon("close")}</button>
                </form>
            </td>
        </tr>
    """


def manage_person_row(row: sqlite3.Row) -> str:
    food_count = int(row["food_count"] or 0)
    total = float(row["total_quantity"] or 0)
    return f"""
        <tr>
            <td>
                <strong>{esc(row["name"])}</strong>
                <span class="muted">{food_count} food{"s" if food_count != 1 else ""} &middot; {total:g} total quantity</span>
            </td>
            <td class="row-actions">
                <a class="action-button edit-action" href="/manage/people/edit/{row["id"]}" title="Edit" aria-label="Edit">{icon("edit")}</a>
                <form method="post" action="/manage/people/delete/{row["id"]}" data-confirm="Delete {esc(row["name"])}?">
                    <button class="action-button danger-action delete-action" type="submit" title="Delete" aria-label="Delete">{icon("close")}</button>
                </form>
            </td>
        </tr>
    """


def food_manage_row(item: sqlite3.Row, return_to: str = "/manage") -> str:
    encoded_return = urlencode({"return_to": return_to})
    ingredient = '<span class="muted">Ingredient</span>' if item["ingredient"] else ""
    return f"""
        <tr>
            <td><strong>{esc(item["name"])}</strong><span class="muted">{esc(item["category"])}</span>{ingredient}</td>
            <td>{esc(item["freezer_name"])}</td>
            <td>{esc(item["people_names"] or "No one")}</td>
            <td>{esc(display_quantity(item))}</td>
            <td>{esc(display_date(item["use_by"]))}<span class="muted">{use_by_label(item["use_by"])}</span></td>
            <td class="row-actions compact-actions">
                <div class="action-group">
                    <a class="action-button" href="/new?copy={item["id"]}&amp;{encoded_return}">Add batch</a>
                    <a class="action-button edit-action" href="/edit/{item["id"]}?{encoded_return}" title="Edit" aria-label="Edit">{icon("edit")}</a>
                    <form method="post" action="/delete/{item["id"]}" data-confirm="Delete {esc(item["name"])} batch {item["batch_number"]}?">
                        <input type="hidden" name="return_to" value="{esc(return_to)}">
                        <button class="action-button danger-action delete-action" type="submit" title="Delete" aria-label="Delete">{icon("close")}</button>
                    </form>
                </div>
            </td>
        </tr>
    """


def empty_manage_row() -> str:
    return '<tr><td colspan="2" class="empty">Nothing here yet.</td></tr>'


def empty_food_row() -> str:
    return '<tr><td colspan="6" class="empty">No foods in the database yet.</td></tr>'


def login_page(error: str = "") -> bytes:
    auth_enabled = read_config()["AUTH_OPT"] != "NONE"
    content = f"""
        <section class="panel auth-panel">
            <div class="panel-heading"><h2>Login</h2></div>
            {notice([error]) if error else ""}
            <form method="post" action="/login" class="item-form compact-form">
                <label>
                    <span>Username</span>
                    <input name="username" required data-autofocus>
                </label>
                <label>
                    <span>Password</span>
                    <input name="password" type="password" required>
                </label>
                <div class="form-actions">
                    <button class="primary" type="submit">Login</button>
                </div>
            </form>
            {f'<button class="signup-link" type="button" data-signup-open>Create an account</button>' if auth_enabled else ""}
        </section>
        {signup_modal() if auth_enabled else ""}
    """
    return render_page(content, "login")


def signup_modal(errors: list[str] | None = None, username: str = "") -> str:
    return f"""
        <div class="modal-backdrop" data-signup-modal {"data-open='true'" if errors else "hidden"}>
            <section class="confirm-modal quick-add-modal" role="dialog" aria-modal="true" aria-labelledby="signup-title">
                <h2 id="signup-title">Create account</h2>
                {notice(errors or []) if errors else ""}
                <form method="post" action="/signup">
                    <label><span>Username</span><input name="username" required value="{esc(username)}"></label>
                    <label><span>Password</span><input name="password" type="password" minlength="8" required></label>
                    <label><span>Confirm password</span><input name="confirm_password" type="password" minlength="8" required></label>
                    <div class="form-actions">
                        <button class="secondary" type="button" data-signup-cancel>Cancel</button>
                        <button class="primary" type="submit">Create account</button>
                    </div>
                </form>
            </section>
        </div>
    """


def profile_card(current_user: sqlite3.Row, password_required: bool = False, errors: list[str] | None = None) -> str:
    return f"""
        <section class="panel">
            <div class="panel-heading split">
                <h2>User Profile</h2>
                <button class="icon-button" type="button" title="Interface colour settings" aria-label="Interface colour settings" data-palette-settings-open>{icon("settings")}</button>
            </div>
            {f'<div class="notice error"><strong>Password update required</strong><p>Set a new password before continuing.</p></div>' if password_required else ""}
            {notice(errors or []) if errors else ""}
            <form method="post" action="/manage/profile" class="item-form compact-form">
                <label><span>Username</span><input name="username" required value="{esc(current_user["username"])}"></label>
                <label><span>Current password</span><input name="current_password" type="password" required></label>
                <label><span>New password</span><input name="new_password" type="password" minlength="8" placeholder="Leave blank to keep current"></label>
                <div class="form-actions"><button class="primary" type="submit">Save profile</button></div>
            </form>
        </section>
    """


def metric_polyline(rows: list[sqlite3.Row], key: str, width: int = 560, height: int = 120) -> str:
    values = [float(row[key] or 0) for row in rows]
    if not values:
        return ""
    maximum = max(max(values), 100 if key != "network_bytes" else 1)
    points = []
    for index, value in enumerate(values):
        x = index / max(1, len(values) - 1) * width
        y = height - (value / maximum * (height - 8)) - 4
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def metric_circles(rows: list[sqlite3.Row], key: str, color: str, width: int = 560, height: int = 120) -> str:
    values = [float(row[key] or 0) for row in rows]
    if not values:
        return ""
    maximum = max(max(values), 100 if key in ("cpu_percent", "ram_percent") else 1)
    circles = []
    for index, (row, value) in enumerate(zip(rows, values)):
        x = index / max(1, len(values) - 1) * width
        y = height - (value / maximum * (height - 8)) - 4
        detail = f"{value:.1f}%" if key.endswith("_percent") else display_bytes(value)
        circles.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{esc(color)}"><title>{esc(row["created_at"])}: {esc(detail)}</title></circle>'
        )
    return "".join(circles)


def admin_metric_colors(user_id: int) -> dict[str, str]:
    defaults = {"cpu_percent": "#2f6f4f", "ram_percent": "#4b78a8", "app_storage_bytes": "#a4661b"}
    try:
        saved = json.loads(get_user_setting(user_id, "admin_metric_colors", "{}"))
    except json.JSONDecodeError:
        saved = {}
    return {
        key: normalize_hex_color(str(saved.get(key, default))) or default
        for key, default in defaults.items()
    }


def metric_settings_modal(colors: dict[str, str]) -> str:
    labels = {"cpu_percent": "CPU", "ram_percent": "RAM", "app_storage_bytes": "App storage"}
    fields = "".join(
        f'<label><span>{label}</span><input type="color" name="{key}" value="{esc(colors[key])}"></label>'
        for key, label in labels.items()
    )
    return f"""
        <div class="modal-backdrop" data-metric-settings-modal hidden>
            <section class="confirm-modal" role="dialog" aria-modal="true">
                <h2>Statistics colours</h2>
                <form method="post" action="/admin/metric-colors" class="item-form compact-form">
                    {fields}
                    <div class="form-actions">
                        <button class="secondary" type="button" data-metric-settings-cancel>Cancel</button>
                        <button class="secondary" type="submit" formaction="/admin/metric-colors/reset">Reset defaults</button>
                        <button class="primary" type="submit">Save</button>
                    </div>
                </form>
            </section>
        </div>
    """


def admin_result_modal(
    title: str,
    message: str,
    generated_password: str = "",
    success: bool = True,
    action_href: str = "",
    action_label: str = "",
) -> str:
    password = (
        f"""
            <div class="generated-password">
                <span>Generated password</span>
                <div>
                    <code data-generated-password>{esc(generated_password)}</code>
                    <button class="secondary" type="button" data-copy-password>Copy</button>
                </div>
            </div>
        """
        if generated_password
        else ""
    )
    return f"""
        <div class="modal-backdrop" data-admin-result-modal data-result="{"success" if success else "error"}">
            <section class="confirm-modal result-modal" role="dialog" aria-modal="true" aria-labelledby="admin-result-title">
                <h2 id="admin-result-title">{esc(title)}</h2>
                <p>{esc(message)}</p>
                {password}
                <div class="form-actions">
                    {f'<a class="secondary" href="{esc(action_href)}">{esc(action_label or "Download")}</a>' if action_href else ""}
                    <button class="primary" type="button" data-admin-result-close>Close</button>
                </div>
            </section>
        </div>
    """


def admin_page(
    errors: list[str] | None = None,
    generated_password: str = "",
    range_key: str = "1h",
    result_title: str = "",
    result_message: str = "",
    result_success: bool = True,
    result_action_href: str = "",
    result_action_label: str = "",
    form_values: dict[str, str] | None = None,
) -> bytes:
    users = fetch_webusers()
    sessions = fetch_active_sessions()
    metrics = fetch_system_metrics(range_key)
    latest = dict(metrics[-1]) if metrics else system_snapshot()
    current_user = getattr(RENDER_CONTEXT, "user", None)
    metric_colors = admin_metric_colors(current_user["id"]) if current_user else {
        "cpu_percent": "#2f6f4f",
        "ram_percent": "#4b78a8",
        "app_storage_bytes": "#a4661b",
    }
    form_values = form_values or {}
    rows = "".join(admin_user_row(user) for user in users) or """
        <tr><td colspan="5" class="empty">No webusers yet.</td></tr>
    """
    result_modal = (
        admin_result_modal(
            result_title,
            result_message,
            generated_password,
            result_success,
            result_action_href,
            result_action_label,
        )
        if result_title
        else ""
    )
    session_rows = "".join(
        f'''<tr>
            <td><strong>{esc(row["username"])}</strong><span class="muted">{esc(row["role"])} · {row["session_count"]} session(s)</span></td>
            <td>{esc(row["last_ip"] or "Unknown")}</td>
            <td>{esc(row["last_seen_at"])}</td>
            <td class="row-actions"><form method="post" action="/admin/sessions/logout/{row["user_id"]}" data-confirm="Force {esc(row["username"])} to log out on every device? This will invalidate all of their session cookies and require them to log in again."><button class="action-button danger-action force-logout-action" type="submit">Force log out</button></form></td>
        </tr>'''
        for row in sessions
    ) or '<tr><td colspan="4" class="empty">No users active in the last 15 minutes.</td></tr>'
    chart_lines = "".join(
        f'<polyline class="metric-line" style="stroke:{metric_colors[key]}" points="{metric_polyline(metrics, key)}"></polyline>{metric_circles(metrics, key, metric_colors[key])}'
        for key in ("cpu_percent", "ram_percent", "app_storage_bytes")
        if metrics
    )
    content = f"""
        <section class="panel admin-statistics">
            <div class="panel-heading split">
                <h2>Statistics</h2>
                <div class="heading-actions">
                    <button class="icon-button" type="button" title="Statistics colour settings" aria-label="Statistics colour settings" data-metric-settings-open>{icon("settings")}</button>
                    <form method="get" action="/admin"><select name="range" onchange="this.form.submit()">{option_tags(["1h", "6h", "24h", "7d"], range_key)}</select></form>
                </div>
            </div>
            <div class="admin-metrics">
                <div><strong>{len(sessions)}</strong><span>Connected users</span></div>
                <div><strong>{float(latest["cpu_percent"]):.1f}%</strong><span>CPU</span></div>
                <div><strong>{display_bytes(latest["ram_bytes"])} · {float(latest["ram_percent"]):.1f}%</strong><span>RAM</span></div>
                <div><strong>{display_bytes(latest["app_storage_bytes"])}</strong><span>App storage</span></div>
            </div>
            <div class="metric-chart">
                <svg viewBox="0 0 560 120" role="img" aria-label="Freezer Stock server resource history">{chart_lines}</svg>
                <div class="metric-legend">
                    <span style="--legend-color:{metric_colors["cpu_percent"]}">CPU</span>
                    <span style="--legend-color:{metric_colors["ram_percent"]}">RAM</span>
                    <span style="--legend-color:{metric_colors["app_storage_bytes"]}">App storage</span>
                </div>
            </div>
            <div class="table-wrap internal-scroll">
                <table><thead><tr><th>User</th><th>IP</th><th>Last active</th><th>Action</th></tr></thead><tbody>{session_rows}</tbody></table>
            </div>
            <form class="logout-all-form" method="post" action="/admin/sessions/logout-all" data-confirm="Force all users to log out on every device? This will invalidate all session cookies and require every user to log in again."><button class="secondary danger-text" type="submit">Force log out all users</button></form>
        </section>
        <section class="admin-card-flow">
            <div class="manage-columns">
                <div class="manage-column">
                    <section class="panel">
                        <div class="panel-heading"><h2>Webuser Admin</h2></div>
                        <form method="post" action="/admin/users" class="item-form compact-form">
                            <div class="field-row">
                                <label>
                                    <span>Role</span>
                                    <select name="role">{option_tags(["ADMIN", "USER"], form_values.get("role", "USER"))}</select>
                                </label>
                                <label>
                                    <span>Username</span>
                                    <input name="username" required placeholder="jacob" value="{esc(form_values.get("username", ""))}">
                                </label>
                            </div>
                            <label>
                                <span>Password</span>
                                <input name="password" type="password" placeholder="Leave blank to generate">
                            </label>
                            <div class="form-actions">
                                <button class="primary" type="submit">Add user</button>
                            </div>
                        </form>
                        <div class="table-wrap admin-users-table-wrap">
                            <table class="admin-users-table">
                                <thead><tr><th>Username</th><th>Role</th><th>New password</th><th>Created</th><th class="action-heading">Action</th></tr></thead>
                                <tbody>{rows}</tbody>
                            </table>
                        </div>
                    </section>
                    {backup_card()}
                    {stats_reset_history_card()}
                </div>
                <div class="manage-column">
                    {server_config_card()}
                    {server_log_card()}
                    {stock_event_archive_card()}
                    <section class="panel danger-zone">
                        <div class="panel-heading"><h2>Server Controls</h2></div>
                        <form method="post" action="/admin/reset-server" class="item-form compact-form" data-password-confirm="Enter your admin password to reset all application data and settings. A complete backup will be created first. Administrator accounts will be preserved.">
                            <p class="muted compact">Creates a full backup, resets application data and settings, and preserves administrator accounts.</p>
                            <button class="danger-action action-button" type="submit">Reset server data</button>
                        </form>
                        <form method="post" action="/admin/shutdown" class="item-form compact-form" data-password-confirm="Enter your admin password to safely shut down the server.">
                            <button class="danger-action action-button" type="submit">Shut down server</button>
                        </form>
                    </section>
                </div>
            </div>
        </section>
        {colour_preferences_modal("/admin")}
        {result_modal}
    """
    return render_page(content, "admin")


def admin_user_row(user: sqlite3.Row) -> str:
    form_id = f'webuser-edit-{user["id"]}'
    return f"""
        <tr>
            <td><input form="{form_id}" name="username" value="{esc(user["username"])}" required></td>
            <td><select form="{form_id}" name="role">{option_tags(["ADMIN", "USER"], user["role"])}</select></td>
            <td><input form="{form_id}" name="password" type="password" placeholder="Blank keeps current"></td>
            <td>{esc(user["created_at"])}</td>
            <td class="row-actions">
                <form id="{form_id}" method="post" action="/admin/users/edit/{user["id"]}"></form>
                <button form="{form_id}" class="action-button" type="submit">Save</button>
                <button form="{form_id}" class="action-button" type="submit" name="password" value="__generate__">Random</button>
                <form method="post" action="/admin/users/force-password/{user["id"]}" data-confirm="Require {esc(user["username"])} to change their password at next login?">
                    <button class="action-button" type="submit">{"Reset required" if user["must_change_password"] else "Force reset"}</button>
                </form>
                <form method="post" action="/admin/users/delete/{user["id"]}" data-confirm="Delete webuser {esc(user["username"])}?">
                    <button class="action-button danger-action delete-action" type="submit" title="Delete" aria-label="Delete">{icon("close")}</button>
                </form>
            </td>
        </tr>
    """


class FreezerHandler(BaseHTTPRequestHandler):
    def cookie_value(self, name: str) -> str:
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            if key == name:
                return value
        return ""

    def current_user(self) -> sqlite3.Row | None:
        if read_config()["AUTH_OPT"] == "NONE":
            return None
        return session_user(
            self.cookie_value(SESSION_COOKIE),
            self.client_ip(),
            self.headers.get("User-Agent", ""),
        )

    def prepare_request(self, parsed_path: str, method: str) -> tuple[bool, sqlite3.Row | None]:
        user = self.current_user()
        RENDER_CONTEXT.user = user
        config = read_config()
        public_paths = {"/login", "/logout", "/signup", "/api/version"}
        if parsed_path.startswith("/static/") or parsed_path in public_paths:
            return True, user
        if user and user["must_change_password"] and parsed_path not in ("/manage", "/manage/profile"):
            self.redirect("/manage?password_required=1")
            return False, user
        if parsed_path.startswith("/admin"):
            if user and user["role"] == "ADMIN":
                return True, user
            self.redirect("/login")
            return False, user
        if parsed_path in ("/stats/reset", "/stats/events/reset") and not (user and user["role"] == "ADMIN"):
            self.redirect("/login")
            return False, user
        if parsed_path == "/logs" and config["AUTH_OPT"] != "NONE" and not (user and user["role"] == "ADMIN"):
            self.redirect("/login")
            return False, user
        if parsed_path in ("/api/server-log", "/server-log/settings", "/server-log/settings/reset") and config["AUTH_OPT"] != "NONE" and not (user and user["role"] == "ADMIN"):
            if parsed_path != "/api/server-log":
                self.redirect("/login")
                return False, user
            self.respond_json({"error": "Admin access required."}, HTTPStatus.FORBIDDEN)
            return False, user
        if parsed_path in ("/manage/config", "/manage/config/reset") and config["AUTH_OPT"] != "NONE" and not (user and user["role"] == "ADMIN"):
            self.redirect("/login")
            return False, user
        if config["AUTH_OPT"] == "VIEW" and not user:
            self.redirect("/login")
            return False, user
        if config["AUTH_OPT"] == "EDIT" and method == "POST" and not user:
            self.redirect("/login")
            return False, user
        return True, user

    def client_ip(self) -> str:
        forwarded_for = self.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        return self.client_address[0]

    def request_actor(self) -> dict[str, str]:
        user_agent = self.headers.get("User-Agent", "")
        platform = self.headers.get("Sec-CH-UA-Platform", "").strip('"')
        device = platform or user_agent.split(")", 1)[0].removeprefix("Mozilla/5.0 (") or "Unknown device"
        user = getattr(RENDER_CONTEXT, "user", None)
        return {
            "ip_address": self.client_ip(),
            "user_agent": user_agent,
            "device_name": device[:120],
            "username": user["username"] if user else "",
        }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        allowed, _user = self.prepare_request(parsed.path, "GET")
        if not allowed:
            return
        if parsed.path == "/api/foods":
            query = parse_qs(parsed.query)
            search = query.get("q", [""])[0]
            self.respond_json({"items": fetch_food_suggestions(search)})
            return

        if parsed.path == "/api/predict-food":
            query = parse_qs(parsed.query)
            self.respond_json(predict_food_defaults(query.get("q", [""])[0]))
            return

        if parsed.path == "/api/version":
            self.respond_json({"version": change_version()})
            return

        if parsed.path == "/api/server-log":
            query = parse_qs(parsed.query)
            try:
                limit = max(1, min(1000, int(query.get("limit", ["18"])[0])))
            except ValueError:
                limit = 18
            self.respond_json({"log": log_tail(limit)})
            return

        if parsed.path == "/login":
            self.respond(login_page())
            return

        if parsed.path == "/signup":
            self.redirect("/login")
            return

        if parsed.path == "/logout":
            delete_session(self.cookie_value(SESSION_COOKIE))
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax")
            self.end_headers()
            return

        if parsed.path == "/":
            filters: dict[str, object] = parse_qs(parsed.query)
            copy_id = int_or_none(filter_scalar(filters, "copy"))
            filters.pop("copy", None)
            filters.pop("return_to", None)
            source_item = fetch_item(copy_id) if copy_id else None
            form_values = None
            if source_item:
                form_values = batch_form_values(source_item)
                form_values["person_ids"] = fetch_item_people(source_item["id"])
            self.respond(index_page(filters, form_values=form_values))
            return

        if parsed.path == "/new":
            query = parse_qs(parsed.query)
            copy_id = int_or_none(query.get("copy", [""])[0])
            return_to = safe_return_target(query.get("return_to", ["/"])[0])
            source_item = fetch_item(copy_id) if copy_id else None
            if copy_id and not source_item:
                self.not_found()
                return
            if source_item:
                values = batch_form_values(source_item)
                selected_people = fetch_item_people(source_item["id"])
                form = item_form(
                    values,
                    [],
                    "/new",
                    f'Add batch: {source_item["name"]}',
                    selected_people,
                    "quantity",
                    return_to,
                )
            else:
                form = item_form(None, [], "/new", "Add freezer item", return_to="/new")
            self.respond(render_page(form, "new"))
            return

        if parsed.path == "/pull":
            filters = parse_qs(parsed.query)
            self.respond(pull_page(filters))
            return

        if parsed.path == "/buy":
            self.respond(buy_page())
            return

        if parsed.path == "/expiry":
            filters = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            self.respond(expiry_page(filters))
            return

        if parsed.path == "/stats":
            self.respond(stats_page())
            return

        if parsed.path == "/stats/events":
            self.respond(stock_events_page())
            return

        if parsed.path == "/admin/stock-event-archive":
            batch = parse_qs(parsed.query).get("batch", [""])[0]
            self.respond(archived_stock_events_page(batch))
            return

        if parsed.path == "/admin/stats-reset-archive":
            reset_id = int_or_none(parse_qs(parsed.query).get("id", [""])[0])
            self.respond(archived_stats_page(reset_id))
            return

        if parsed.path.startswith("/reports/") and parsed.path.endswith(".csv"):
            report = parsed.path.removeprefix("/reports/").removesuffix(".csv")
            result = report_csv(report)
            if not result:
                self.not_found()
                return
            body, filename = result
            self.respond_download(body, filename, "text/csv; charset=utf-8")
            return

        if parsed.path == "/audit":
            self.respond(audit_page(parse_qs(parsed.query)))
            return

        if parsed.path == "/admin":
            range_key = parse_qs(parsed.query).get("range", ["1h"])[0]
            self.respond(admin_page(range_key=range_key))
            return

        if parsed.path == "/admin/backup":
            mode = parse_qs(parsed.query).get("mode", ["full"])[0]
            if mode not in ("settings", "full"):
                mode = "full"
            body, filename, content_type = create_backup(mode)
            self.respond_download(body, filename, content_type)
            return

        if parsed.path == "/admin/prereset-backup":
            folder_name = parse_qs(parsed.query).get("folder", [""])[0]
            backup_path = prereset_backup_path(folder_name)
            if not backup_path:
                self.not_found()
                return
            self.respond_download(backup_path.read_bytes(), backup_path.name, "application/zip")
            return

        if parsed.path == "/manage":
            self.respond(manage_page())
            return

        if parsed.path == "/logs":
            self.respond(logs_page())
            return

        if parsed.path == "/foods":
            filters = parse_qs(parsed.query)
            self.respond(foods_page(filters))
            return

        if parsed.path.startswith("/manage/freezers/edit/"):
            freezer_id = self.item_id_from_path("/manage/freezers/edit/")
            freezer = fetch_freezer(freezer_id) if freezer_id else None
            if not freezer:
                self.not_found()
                return
            self.respond(manage_page(edit_freezer=freezer))
            return

        if parsed.path.startswith("/manage/people/edit/"):
            person_id = self.item_id_from_path("/manage/people/edit/")
            person = fetch_person(person_id) if person_id else None
            if not person:
                self.not_found()
                return
            self.respond(manage_page(edit_person=person))
            return

        if parsed.path.startswith("/manage/units/edit/"):
            unit_id = self.item_id_from_path("/manage/units/edit/")
            unit = fetch_unit(unit_id) if unit_id else None
            if not unit:
                self.not_found()
                return
            self.respond(manage_page(edit_unit=unit))
            return

        if parsed.path.startswith("/manage/categories/edit/"):
            category_id = self.item_id_from_path("/manage/categories/edit/")
            category = fetch_category(category_id) if category_id else None
            if not category:
                self.not_found()
                return
            self.respond(manage_page(edit_category=category))
            return

        if parsed.path.startswith("/edit/"):
            item_id = self.item_id_from_path("/edit/")
            item = fetch_item(item_id) if item_id else None
            if not item:
                self.not_found()
                return
            query = parse_qs(parsed.query)
            return_to = safe_return_target(query.get("return_to", ["/manage"])[0])
            self.respond(render_page(item_form(item, [], f"/edit/{item_id}", "Edit freezer item", return_to=return_to), "manage"))
            return

        if parsed.path.startswith("/static/"):
            self.serve_static(parsed.path)
            return

        self.not_found()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        allowed, _user = self.prepare_request(parsed.path, "POST")
        if not allowed:
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        add_network_bytes(len(body))
        values = parse_form_multi(body)
        form = scalar_values(values)
        actor = self.request_actor()

        if parsed.path == "/login":
            user = authenticate_user(form.get("username", ""), form.get("password", ""))
            if not user:
                self.respond(login_page("Login failed."), HTTPStatus.UNAUTHORIZED)
                return
            token = create_session(user["id"])
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/manage?password_required=1" if user["must_change_password"] else "/")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly")
            self.end_headers()
            return

        if parsed.path == "/signup":
            username = form.get("username", "").strip()
            password = form.get("password", "")
            if password != form.get("confirm_password", ""):
                self.respond(render_page(signup_modal(["Passwords do not match."], username), "login"), HTTPStatus.BAD_REQUEST)
                return
            errors = signup_user(username, password, actor)
            if errors:
                self.respond(render_page(signup_modal(errors, username), "login"), HTTPStatus.BAD_REQUEST)
            else:
                self.respond(
                    render_page(
                        '<section class="panel auth-panel"><div class="panel-heading"><h2>Account created</h2></div><div class="item-form"><p>Your account is ready.</p><a class="primary" href="/login">Continue to login</a></div></section>',
                        "login",
                    )
                )
            return

        if parsed.path == "/server-log/settings":
            preferences = save_server_log_preferences(form, _user)
            if self.headers.get("Accept") == "application/json":
                self.respond_json({"ok": True, **preferences})
            else:
                self.redirect(safe_return_target(form.get("return_to", "/manage")))
            return

        if parsed.path == "/server-log/settings/reset":
            reset_server_log_preferences(_user)
            preferences = server_log_preferences(_user)
            if self.headers.get("Accept") == "application/json":
                self.respond_json({"ok": True, **preferences})
            else:
                self.redirect(safe_return_target(form.get("return_to", "/manage")))
            return

        if parsed.path.startswith("/api/quick-add/"):
            kind = parsed.path.removeprefix("/api/quick-add/").strip("/")
            row, errors = quick_add(kind, form)
            self.respond_json({"ok": not errors, "item": row, "errors": errors}, HTTPStatus.BAD_REQUEST if errors else HTTPStatus.OK)
            return

        if parsed.path == "/":
            person_ids = selected_people_from_form(values)
            item, errors = validate_item(form, person_ids)
            if errors:
                self.respond(index_page({}, errors, item), HTTPStatus.BAD_REQUEST)
                return
            insert_item(item, actor)
            self.redirect("/", {"focus": "food"})
            return

        if parsed.path == "/new":
            person_ids = selected_people_from_form(values)
            item, errors = validate_item(form, person_ids)
            if errors:
                self.respond(render_page(item_form(item, errors, "/new", "Add freezer item", person_ids), "new"), HTTPStatus.BAD_REQUEST)
                return
            insert_item(item, actor)
            self.redirect("/new", {"focus": "food"})
            return

        if parsed.path.startswith("/edit/"):
            item_id = self.item_id_from_path("/edit/")
            existing = fetch_item(item_id) if item_id else None
            if not item_id or not existing:
                self.not_found()
                return
            person_ids = selected_people_from_form(values)
            item, errors = validate_item(form, person_ids)
            if errors:
                self.respond(
                    render_page(
                        item_form(
                            item,
                            errors,
                            f"/edit/{item_id}",
                            "Edit freezer item",
                            person_ids,
                            return_to=safe_return_target(form.get("return_to", "/manage")),
                        ),
                        "manage",
                    ),
                    HTTPStatus.BAD_REQUEST,
                )
                return
            update_item(item_id, item, actor)
            self.redirect(safe_return_target(form.get("return_to", "/manage")))
            return

        if parsed.path.startswith("/stock/"):
            item_id = self.item_id_from_path("/stock/")
            try:
                amount = float(form.get("amount", "0"))
            except ValueError:
                amount = 0
            direction = form.get("direction", "")
            result: dict[str, object] = {"ok": True}
            if item_id and direction in ("add", "remove"):
                result = adjust_stock(item_id, amount, direction, actor)
            if self.headers.get("Accept") == "application/json":
                self.respond_json({**result, "version": change_version()})
                return
            self.redirect(safe_return_target(form.get("return_to", "/")))
            return

        if parsed.path.startswith("/buy/add/"):
            item_id = self.item_id_from_path("/buy/add/")
            if item_id:
                mark_buy_requested(item_id, actor)
            if self.headers.get("Accept") == "application/json":
                self.respond_json({"ok": True, "version": change_version()})
                return
            self.redirect(safe_return_target(form.get("return_to", "/buy")))
            return

        if parsed.path.startswith("/buy/clear/"):
            item_id = self.item_id_from_path("/buy/clear/")
            if item_id:
                clear_buy_requested(item_id, actor)
            self.redirect(safe_return_target(form.get("return_to", "/buy")))
            return

        if parsed.path.startswith("/delete/"):
            item_id = self.item_id_from_path("/delete/")
            if item_id:
                delete_item(item_id, actor)
            self.redirect(safe_return_target(form.get("return_to", "/manage")))
            return

        if parsed.path == "/manage/freezers":
            errors = save_freezer(form)
            if errors:
                self.respond(manage_page(errors), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage", {"focus": "freezer"})
            return

        if parsed.path.startswith("/manage/freezers/edit/"):
            freezer_id = self.item_id_from_path("/manage/freezers/edit/")
            if not freezer_id or not fetch_freezer(freezer_id):
                self.not_found()
                return
            errors = save_freezer(form, freezer_id)
            if errors:
                self.respond(manage_page(errors, fetch_freezer(freezer_id)), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage")
            return

        if parsed.path.startswith("/manage/freezers/delete/"):
            freezer_id = self.item_id_from_path("/manage/freezers/delete/")
            if freezer_id:
                delete_freezer(freezer_id)
            self.redirect("/manage")
            return

        if parsed.path == "/manage/people":
            errors = save_person(form)
            if errors:
                self.respond(manage_page(errors), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage", {"focus": "person"})
            return

        if parsed.path == "/manage/log":
            errors = save_log_settings(form)
            if errors:
                self.respond(manage_page(log_errors=errors), HTTPStatus.BAD_REQUEST)
            else:
                safe_print("Updated appearance settings.")
                self.redirect("/manage")
            return

        if parsed.path == "/manage/profile":
            if not _user:
                self.redirect("/login")
                return
            existing_user = fetch_webuser(_user["id"])
            errors = update_own_profile(
                _user["id"],
                form.get("username", ""),
                form.get("current_password", ""),
                form.get("new_password", ""),
            )
            if errors:
                self.respond(manage_page(errors=errors), HTTPStatus.BAD_REQUEST)
            else:
                updated_user = fetch_webuser(_user["id"])
                if updated_user:
                    changes: list[str] = []
                    if existing_user and existing_user["username"] != updated_user["username"]:
                        changes.append(f'username changed from "{existing_user["username"]}"')
                    if form.get("new_password"):
                        changes.append("password changed")
                    log_user_audit(
                        "User updated",
                        updated_user["username"],
                        "; ".join(changes) + "." if changes else "Profile saved with no visible account changes.",
                        actor,
                    )
                self.redirect("/manage")
            return

        if parsed.path == "/appearance/settings":
            palette = {
                "accent": normalize_hex_color(form.get("accent", "")) or DEFAULT_ACCENT_COLOR,
                "info": normalize_hex_color(form.get("info", "")) or "#2f5d7c",
                "warning": normalize_hex_color(form.get("warning", "")) or "#a4661b",
                "danger": normalize_hex_color(form.get("danger", "")) or "#a53d36",
            }
            if _user:
                set_user_setting(_user["id"], "palette", json.dumps(palette))
            else:
                set_setting("accent_color", palette["accent"])
                set_setting("info_color", palette["info"])
                set_setting("warning_color", palette["warning"])
                set_setting("danger_color", palette["danger"])
            self.redirect(safe_return_target(form.get("return_to", "/manage")))
            return

        if parsed.path == "/appearance/settings/reset":
            if _user:
                set_user_setting(_user["id"], "palette", "{}")
            else:
                set_setting("accent_color", DEFAULT_ACCENT_COLOR)
                set_setting("info_color", "#2f5d7c")
                set_setting("warning_color", "#a4661b")
                set_setting("danger_color", "#a53d36")
            self.redirect(safe_return_target(form.get("return_to", "/manage")))
            return

        if parsed.path == "/audit/settings":
            colors = {
                action: value
                for action, value in form.items()
                if action != "return_to" and normalize_hex_color(value)
            }
            saved_colors = json.dumps({**audit_colors(), **colors})
            if _user:
                set_user_setting(_user["id"], "audit_colors", saved_colors)
            else:
                set_setting("audit_colors", saved_colors)
            self.redirect(safe_return_target(form.get("return_to", "/audit")))
            return

        if parsed.path == "/audit/settings/reset":
            if _user:
                set_user_setting(_user["id"], "audit_colors", "{}")
            else:
                set_setting("audit_colors", json.dumps(DEFAULT_AUDIT_COLORS))
            self.redirect(safe_return_target(form.get("return_to", "/audit")))
            return

        if parsed.path == "/manage/log/reset":
            reset_appearance_defaults()
            self.redirect("/manage")
            return

        if parsed.path == "/manage/config":
            if read_config()["AUTH_OPT"] != "NONE" and not (_user and _user["role"] == "ADMIN"):
                form.pop("favicon_data", None)
            errors, changed_bind = save_server_config(form)
            if errors:
                self.respond(manage_page(config_errors=errors), HTTPStatus.BAD_REQUEST)
            else:
                message = "Saved config.yml. Restart the server for bind IP changes to take effect." if changed_bind else "Saved config.yml."
                self.respond(manage_page(config_notice=message))
            return

        if parsed.path == "/manage/config/reset":
            reset_server_defaults()
            self.respond(manage_page(config_notice="Server settings reset to defaults. Restart the server for bind settings to take effect."))
            return

        if parsed.path == "/admin/users":
            role = form.get("role", "USER")
            username = form.get("username", "").strip()
            supplied_password = form.get("password", "")
            errors, generated = create_webuser(role, username, supplied_password)
            if errors:
                self.respond(
                    admin_page(
                        errors,
                        result_title="User creation failed",
                        result_message=" ".join(errors),
                        result_success=False,
                        form_values={"role": role, "username": username},
                    ),
                    HTTPStatus.BAD_REQUEST,
                )
            else:
                log_user_audit(
                    "User created",
                    username,
                    (
                        f"{normalize_role(role)} account created by an administrator. "
                        f"Password {'generated automatically' if generated else 'supplied by administrator'}."
                    ),
                    actor,
                )
                message = f'Webuser "{username}" was created successfully.'
                if generated:
                    message += " Save the generated password before closing this window."
                self.respond(
                    admin_page(
                        generated_password=generated or "",
                        result_title="User created",
                        result_message=message,
                    )
                )
            return

        if parsed.path.startswith("/admin/users/force-password/"):
            user_id = self.item_id_from_path("/admin/users/force-password/")
            if user_id:
                target_user = fetch_webuser(user_id)
                set_force_password_change(user_id, True)
                if target_user:
                    log_user_audit(
                        "User updated",
                        target_user["username"],
                        "Password change required at next login; existing sessions invalidated.",
                        actor,
                    )
            self.redirect("/admin")
            return

        if parsed.path.startswith("/admin/sessions/logout/"):
            user_id = self.item_id_from_path("/admin/sessions/logout/")
            if user_id:
                invalidate_user_sessions(user_id)
            self.redirect("/admin")
            return

        if parsed.path == "/admin/sessions/logout-all":
            invalidate_user_sessions()
            self.redirect("/login")
            return

        if parsed.path == "/admin/metric-colors":
            colors = {
                key: normalize_hex_color(form.get(key, "")) or default
                for key, default in {
                    "cpu_percent": "#2f6f4f",
                    "ram_percent": "#4b78a8",
                    "app_storage_bytes": "#a4661b",
                }.items()
            }
            set_user_setting(_user["id"], "admin_metric_colors", json.dumps(colors))
            self.redirect("/admin")
            return

        if parsed.path == "/admin/metric-colors/reset":
            set_user_setting(_user["id"], "admin_metric_colors", "{}")
            self.redirect("/admin")
            return

        if parsed.path == "/admin/restore":
            errors = restore_backup(form.get("mode", "full"), form.get("backup_data", ""))
            if errors:
                self.respond(admin_page(result_title="Restore failed", result_message=" ".join(errors), result_success=False), HTTPStatus.BAD_REQUEST)
            else:
                self.respond(admin_page(result_title="Restore complete", result_message="The selected backup was restored successfully."))
            return

        if parsed.path == "/stats/reset":
            archive_stats_reset(actor)
            set_setting("stock_stats_since", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self.redirect("/stats")
            return

        if parsed.path == "/stats/events/reset":
            archive_stock_events(actor)
            set_setting("stock_stats_since", "")
            self.redirect("/stats/events")
            return

        if parsed.path == "/admin/shutdown":
            password = form.get("admin_password", "")
            confirmed = authenticate_user(_user["username"], password)
            if not confirmed or confirmed["role"] != "ADMIN":
                self.respond(admin_page(result_title="Shutdown cancelled", result_message="The admin password was incorrect.", result_success=False), HTTPStatus.UNAUTHORIZED)
                return
            self.respond(render_page('<section class="panel auth-panel"><div class="panel-heading"><h2>Server shutting down</h2></div><div class="item-form"><p>Freezer Stock is closing safely.</p></div></section>', "admin"))
            if SERVER_INSTANCE:
                threading.Thread(target=shutdown_from_web, daemon=True).start()
            return

        if parsed.path == "/admin/reset-server":
            password = form.get("admin_password", "")
            confirmed = authenticate_user(_user["username"], password)
            if not confirmed or confirmed["role"] != "ADMIN":
                self.respond(
                    admin_page(
                        result_title="Reset cancelled",
                        result_message="The admin password was incorrect. No data was changed.",
                        result_success=False,
                    ),
                    HTTPStatus.UNAUTHORIZED,
                )
                return
            try:
                folder_name, backup_filename = create_prereset_backup()
                reset_application_preserving_admins()
            except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
                safe_print(f"Server reset failed: {exc}")
                self.respond(
                    admin_page(
                        result_title="Reset failed",
                        result_message=f"The server could not be reset. No reset was completed: {exc}",
                        result_success=False,
                    ),
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            download_url = f"/admin/prereset-backup?{urlencode({'folder': folder_name})}"
            self.respond(
                admin_page(
                    result_title="Server reset complete",
                    result_message=(
                        "Application data and settings were reset to defaults. Administrator accounts were preserved. "
                        f"The pre-reset backup is stored in {folder_name}. Download a local copy now."
                    ),
                    result_action_href=download_url,
                    result_action_label=f"Download {backup_filename}",
                )
            )
            return

        if parsed.path.startswith("/admin/users/edit/"):
            user_id = self.item_id_from_path("/admin/users/edit/")
            if not user_id:
                self.not_found()
                return
            existing_user = fetch_webuser(user_id)
            errors, generated = update_webuser(user_id, form.get("role", "USER"), form.get("username", ""), form.get("password", ""))
            if errors:
                self.respond(
                    admin_page(
                        errors,
                        result_title="User update failed",
                        result_message=" ".join(errors),
                        result_success=False,
                    ),
                    HTTPStatus.BAD_REQUEST,
                )
            else:
                updated_user = fetch_webuser(user_id)
                if updated_user:
                    changes: list[str] = []
                    if existing_user and existing_user["username"] != updated_user["username"]:
                        changes.append(f'username changed from "{existing_user["username"]}"')
                    if existing_user and existing_user["role"] != updated_user["role"]:
                        changes.append(f'role changed from {existing_user["role"]} to {updated_user["role"]}')
                    if form.get("password"):
                        changes.append("password changed" if not generated else "password generated")
                    log_user_audit(
                        "User updated",
                        updated_user["username"],
                        "; ".join(changes) + "." if changes else "Account saved with no visible profile changes.",
                        actor,
                    )
                self.respond(
                    admin_page(
                        generated_password=generated or "",
                        result_title="User updated",
                        result_message="The webuser was updated successfully.",
                    )
                )
            return

        if parsed.path.startswith("/admin/users/delete/"):
            user_id = self.item_id_from_path("/admin/users/delete/")
            if user_id:
                existing_user = fetch_webuser(user_id)
                delete_webuser(user_id)
                if existing_user:
                    log_user_audit(
                        "User deleted",
                        existing_user["username"],
                        f'{existing_user["role"]} account permanently deleted.',
                        actor,
                    )
            self.redirect("/admin")
            return

        if parsed.path.startswith("/manage/people/edit/"):
            person_id = self.item_id_from_path("/manage/people/edit/")
            if not person_id or not fetch_person(person_id):
                self.not_found()
                return
            errors = save_person(form, person_id)
            if errors:
                self.respond(manage_page(errors, edit_person=fetch_person(person_id)), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage")
            return

        if parsed.path.startswith("/manage/people/delete/"):
            person_id = self.item_id_from_path("/manage/people/delete/")
            if person_id:
                delete_person(person_id)
            self.redirect("/manage")
            return

        if parsed.path == "/manage/units":
            errors = save_unit(form)
            if errors:
                self.respond(manage_page(errors), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage", {"focus": "unit"})
            return

        if parsed.path.startswith("/manage/units/edit/"):
            unit_id = self.item_id_from_path("/manage/units/edit/")
            if not unit_id or not fetch_unit(unit_id):
                self.not_found()
                return
            errors = save_unit(form, unit_id)
            if errors:
                self.respond(manage_page(errors, edit_unit=fetch_unit(unit_id)), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage")
            return

        if parsed.path.startswith("/manage/units/delete/"):
            unit_id = self.item_id_from_path("/manage/units/delete/")
            if unit_id:
                delete_unit(unit_id)
            self.redirect("/manage")
            return

        if parsed.path == "/manage/categories":
            errors = save_category(form)
            if errors:
                self.respond(manage_page(errors), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage", {"focus": "category"})
            return

        if parsed.path.startswith("/manage/categories/edit/"):
            category_id = self.item_id_from_path("/manage/categories/edit/")
            if not category_id or not fetch_category(category_id):
                self.not_found()
                return
            errors = save_category(form, category_id)
            if errors:
                self.respond(manage_page(errors, edit_category=fetch_category(category_id)), HTTPStatus.BAD_REQUEST)
            else:
                self.redirect("/manage")
            return

        if parsed.path.startswith("/manage/categories/delete/"):
            category_id = self.item_id_from_path("/manage/categories/delete/")
            if category_id:
                delete_category(category_id)
            self.redirect("/manage")
            return

        self.not_found()

    def serve_static(self, path: str) -> None:
        file_name = Path(path).name
        file_path = STATIC_DIR / file_name
        content_types = {
            ".css": "text/css",
            ".js": "text/javascript",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".svg": "image/svg+xml",
        }
        if file_path.suffix.lower() not in content_types or not file_path.exists():
            self.not_found()
            return
        self.send_response(HTTPStatus.OK)
        content_type = content_types[file_path.suffix.lower()]
        self.send_header("Content-Type", content_type if content_type.startswith("image/") else f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        body = file_path.read_bytes()
        self.wfile.write(body)
        add_network_bytes(len(body))

    def item_id_from_path(self, prefix: str) -> int | None:
        try:
            return int(urlparse(self.path).path.removeprefix(prefix))
        except ValueError:
            return None

    def respond(self, body: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        add_network_bytes(len(body))

    def respond_json(self, data: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        add_network_bytes(len(body))

    def respond_download(self, body: bytes, filename: str, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)
        add_network_bytes(len(body))

    def redirect(self, path: str, params: dict[str, str] | None = None) -> None:
        target = path if not params else f"{path}?{urlencode(params)}"
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", target)
        self.end_headers()

    def not_found(self) -> None:
        self.respond(
            render_page('<section class="panel"><h2>Not found</h2><p>That freezer item or page does not exist.</p></section>'),
            HTTPStatus.NOT_FOUND,
        )

    def log_message(self, format: str, *args: object) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_print(f"[{timestamp}] {self.client_ip()} {format % args}")


def main() -> None:
    global SERVER_INSTANCE
    load_server_config()
    init_db()
    init_auth_db()
    server = bind_server_with_fallback()
    SERVER_INSTANCE = server
    safe_print("\nFreezer Stock\n=============")
    safe_print(f"Local URL: http://127.0.0.1:{PORT}")
    safe_print(f"LAN bind:  http://{HOST}:{PORT}")
    for url in lan_urls():
        safe_print(f"LAN URL:   {url}")
    safe_print(f"Database:  {DB_PATH}")
    safe_print("Type help for console commands.\n")
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    metrics_stop = threading.Event()
    metrics_thread = threading.Thread(target=metrics_loop, args=(metrics_stop,), daemon=True)
    metrics_thread.start()
    try:
        for raw_command in sys.stdin:
            command = raw_command.strip().lower()
            if not command:
                continue
            if command in ("stop", "quit", "exit"):
                safe_print("Stopping Freezer Stock.")
                server.shutdown()
                break
            if command == "reload":
                init_db()
                init_auth_db()
                safe_print("Reloaded database setup. Refresh the browser to see current data.")
                continue
            if command == "help":
                print_console_help()
                continue
            if handle_webuser_command(parse_console_command(raw_command.strip())):
                continue
            safe_print(f"Unknown command: {command}. Type help for options.")
        server_thread.join()
    except KeyboardInterrupt:
        safe_print("\nShutting down.")
        server.shutdown()
    finally:
        metrics_stop.set()
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (ROOT / "server_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
