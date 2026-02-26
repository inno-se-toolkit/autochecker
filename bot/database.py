"""Database module for SQLite operations."""

import logging
from pathlib import Path

import aiosqlite
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from .config import DB_PATH

logger = logging.getLogger(__name__)


@dataclass
class User:
    """User data model."""
    tg_id: int
    email: str
    github_alias: str
    tg_username: str
    is_admin: bool


# ---------------------------------------------------------------------------
# Schema version history:
#   0 — legacy (users: tg_id, student_name, github_nick, is_admin)
#   1 — self-registration + results table
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 4


async def _get_table_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    """Return set of column names for a table (empty set if table missing)."""
    cols = set()
    try:
        async with db.execute(f"PRAGMA table_info({table})") as cur:
            async for row in cur:
                cols.add(row[1])
    except Exception:
        pass
    return cols


async def _get_schema_version(db: aiosqlite.Connection) -> int:
    """Read current schema version (0 if meta table doesn't exist)."""
    try:
        async with db.execute("SELECT value FROM _meta WHERE key = 'schema_version'") as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


async def _set_schema_version(db: aiosqlite.Connection, version: int) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)
    """)
    await db.execute(
        "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
        (str(version),)
    )


async def init_db() -> None:
    """Initialize or migrate the database to the latest schema."""
    async with aiosqlite.connect(DB_PATH) as db:
        version = await _get_schema_version(db)
        logger.info("Current DB schema version: %d (target: %d)", version, SCHEMA_VERSION)

        if version < 1:
            await _migrate_to_v1(db)
        if version < 2:
            await _migrate_to_v2(db)
        if version < 3:
            await _migrate_to_v3(db)
        if version < 4:
            await _migrate_to_v4(db)

        await _set_schema_version(db, SCHEMA_VERSION)
        await db.commit()
        logger.info("DB ready at schema version %d", SCHEMA_VERSION)

        # Backfill groups from allowed_emails.csv on every startup
        await _backfill_groups(db)
        await db.commit()


async def _migrate_to_v1(db: aiosqlite.Connection) -> None:
    """Migrate from v0 (legacy) to v1 (self-registration + results)."""
    user_cols = await _get_table_columns(db, "users")

    if not user_cols:
        # Fresh DB — create tables from scratch
        logger.info("Creating tables (fresh DB)")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id         INTEGER PRIMARY KEY,
                email         TEXT NOT NULL UNIQUE,
                github_alias  TEXT NOT NULL UNIQUE,
                tg_username   TEXT DEFAULT '',
                is_admin      BOOLEAN DEFAULT 0,
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        # Existing users table — add missing columns
        if "email" not in user_cols:
            logger.info("Migration v1: adding email column")
            await db.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        if "github_alias" not in user_cols:
            logger.info("Migration v1: adding github_alias column")
            await db.execute("ALTER TABLE users ADD COLUMN github_alias TEXT NOT NULL DEFAULT ''")
        if "tg_username" not in user_cols:
            logger.info("Migration v1: adding tg_username column")
            await db.execute("ALTER TABLE users ADD COLUMN tg_username TEXT DEFAULT ''")
        if "registered_at" not in user_cols:
            logger.info("Migration v1: adding registered_at column")
            await db.execute("ALTER TABLE users ADD COLUMN registered_at DATETIME DEFAULT ''")
            await db.execute("UPDATE users SET registered_at = CURRENT_TIMESTAMP WHERE registered_at = ''")

        # Migrate data from old columns if they exist
        if "github_nick" in user_cols:
            logger.info("Migration v1: copying github_nick -> github_alias")
            await db.execute("UPDATE users SET github_alias = github_nick WHERE github_alias = ''")
        if "student_name" in user_cols:
            logger.info("Migration v1: copying student_name -> email placeholder")
            await db.execute(
                "UPDATE users SET email = student_name || '@migrated' WHERE email = ''"
            )

        # Drop legacy columns after data migration (SQLite 3.35+)
        for old_col in ("student_name", "github_nick"):
            if old_col in user_cols:
                try:
                    logger.info("Migration v1: dropping legacy column %s", old_col)
                    await db.execute(f"ALTER TABLE users DROP COLUMN {old_col}")
                except aiosqlite.OperationalError:
                    pass  # SQLite too old or column already dropped

        # Create unique indexes if not present (ignore errors if they exist
        # or if migrated data has duplicates)
        for col in ("email", "github_alias"):
            try:
                await db.execute(f"CREATE UNIQUE INDEX idx_users_{col} ON users({col})")
            except (aiosqlite.OperationalError, aiosqlite.IntegrityError):
                pass

    # Attempts table (unchanged schema, just ensure it exists)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS attempts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id     INTEGER NOT NULL,
            lab_id    TEXT NOT NULL,
            task_id   TEXT NOT NULL DEFAULT '',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tg_id) REFERENCES users(tg_id)
        )
    """)
    # Migration from older attempts table without task_id
    attempt_cols = await _get_table_columns(db, "attempts")
    if attempt_cols and "task_id" not in attempt_cols:
        await db.execute("ALTER TABLE attempts ADD COLUMN task_id TEXT NOT NULL DEFAULT ''")

    # Results table (new in v1)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id     INTEGER NOT NULL,
            lab_id    TEXT NOT NULL,
            task_id   TEXT NOT NULL,
            score     TEXT,
            passed    INTEGER,
            failed    INTEGER,
            total     INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tg_id) REFERENCES users(tg_id)
        )
    """)

    logger.info("Migration to v1 complete")


async def _migrate_to_v2(db: aiosqlite.Connection) -> None:
    """Add details column to results table for per-check breakdown."""
    result_cols = await _get_table_columns(db, "results")
    if "details" not in result_cols:
        logger.info("Migration v2: adding details column to results")
        await db.execute("ALTER TABLE results ADD COLUMN details TEXT DEFAULT ''")
    logger.info("Migration to v2 complete")


async def _migrate_to_v3(db: aiosqlite.Connection) -> None:
    """Add server_ip column to users table for VM deployment checks."""
    user_cols = await _get_table_columns(db, "users")
    if "server_ip" not in user_cols:
        logger.info("Migration v3: adding server_ip column to users")
        await db.execute("ALTER TABLE users ADD COLUMN server_ip TEXT DEFAULT ''")
    logger.info("Migration to v3 complete")


async def _migrate_to_v4(db: aiosqlite.Connection) -> None:
    """Add student_group column to users table."""
    user_cols = await _get_table_columns(db, "users")
    if "student_group" not in user_cols:
        logger.info("Migration v4: adding student_group column to users")
        await db.execute("ALTER TABLE users ADD COLUMN student_group TEXT DEFAULT ''")
    logger.info("Migration to v4 complete")


async def _backfill_groups(db: aiosqlite.Connection) -> None:
    """Sync student groups from allowed_emails.csv into the users table."""
    import csv as _csv
    csv_path = Path(__file__).resolve().parent / "allowed_emails.csv"
    if not csv_path.exists():
        return
    email_to_group: dict[str, str] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            email = row["email"].strip().lower()
            group = row["group"].strip()
            if email and group:
                email_to_group[email] = group
    if not email_to_group:
        return
    for email, group in email_to_group.items():
        await db.execute(
            "UPDATE users SET student_group = ? WHERE email = ? AND (student_group IS NULL OR student_group = '')",
            (group, email),
        )
    logger.info("Backfilled groups for %d emails", len(email_to_group))


async def get_server_ip(tg_id: int) -> str:
    """Get stored server IP for a user. Returns empty string if not set."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT server_ip FROM users WHERE tg_id = ?", (tg_id,)
        ) as cur:
            row = await cur.fetchone()
            return (row[0] or "") if row else ""


async def get_server_ip_owner(ip: str, exclude_tg_id: int) -> Optional[str]:
    """Check if a server IP is already used by another student. Returns github_alias or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT github_alias FROM users WHERE server_ip = ? AND tg_id != ?", (ip, exclude_tg_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_server_ip(tg_id: int, ip: str) -> None:
    """Store server IP for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET server_ip = ? WHERE tg_id = ?", (ip, tg_id)
        )
        await db.commit()


async def get_user(tg_id: int) -> Optional[User]:
    """Get user by Telegram ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT tg_id, email, github_alias, tg_username, is_admin FROM users WHERE tg_id = ?",
            (tg_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return User(
                    tg_id=row["tg_id"],
                    email=row["email"],
                    github_alias=row["github_alias"],
                    tg_username=row["tg_username"],
                    is_admin=bool(row["is_admin"])
                )
            return None


async def delete_user(tg_id: int) -> None:
    """Delete user by Telegram ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
        await db.commit()


async def get_user_by_email(email: str) -> Optional[User]:
    """Get user by email address."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT tg_id, email, github_alias, tg_username, is_admin FROM users WHERE email = ?",
            (email,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return User(
                    tg_id=row["tg_id"],
                    email=row["email"],
                    github_alias=row["github_alias"],
                    tg_username=row["tg_username"],
                    is_admin=bool(row["is_admin"])
                )
            return None


async def get_user_by_github(github_alias: str) -> Optional[User]:
    """Get user by GitHub alias."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT tg_id, email, github_alias, tg_username, is_admin FROM users WHERE github_alias = ?",
            (github_alias,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return User(
                    tg_id=row["tg_id"],
                    email=row["email"],
                    github_alias=row["github_alias"],
                    tg_username=row["tg_username"],
                    is_admin=bool(row["is_admin"])
                )
            return None


async def upsert_user(tg_id: int, email: str, github_alias: str, tg_username: str = "", student_group: str = "") -> None:
    """Create or update a user.

    First-come-first-served: if the email or github_alias already belongs
    to a different Telegram account, the operation is rejected with a
    ValueError so the handler can inform the student.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Check email uniqueness
        async with db.execute(
            "SELECT tg_id FROM users WHERE email = ? AND tg_id != ?", (email, tg_id)
        ) as cur:
            if await cur.fetchone():
                raise ValueError(f"Email {email} is already registered to another account.")

        # Check github_alias uniqueness
        async with db.execute(
            "SELECT tg_id FROM users WHERE github_alias = ? AND tg_id != ?", (github_alias, tg_id)
        ) as cur:
            if await cur.fetchone():
                raise ValueError(f"GitHub username {github_alias} is already registered to another account.")

        await db.execute("""
            INSERT INTO users (tg_id, email, github_alias, tg_username, student_group)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                email = excluded.email,
                github_alias = excluded.github_alias,
                tg_username = excluded.tg_username,
                student_group = excluded.student_group
        """, (tg_id, email, github_alias, tg_username, student_group))
        await db.commit()


async def get_attempts_count(tg_id: int, lab_id: str, task_id: str = "") -> int:
    """Get the number of attempts for a specific task by user."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM attempts WHERE tg_id = ? AND lab_id = ? AND task_id = ?",
            (tg_id, lab_id, task_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def add_attempt(tg_id: int, lab_id: str, task_id: str = "") -> None:
    """Record a new attempt for a task."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO attempts (tg_id, lab_id, task_id, timestamp) VALUES (?, ?, ?, ?)",
            (tg_id, lab_id, task_id, datetime.now().isoformat())
        )
        await db.commit()


async def save_result(
    tg_id: int,
    lab_id: str,
    task_id: str,
    score: Optional[str] = None,
    passed: Optional[int] = None,
    failed: Optional[int] = None,
    total: Optional[int] = None,
    details: Optional[str] = None,
) -> None:
    """Save a check result to the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO results (tg_id, lab_id, task_id, score, passed, failed, total, details, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tg_id, lab_id, task_id, score, passed, failed, total, details or "", datetime.now().isoformat())
        )
        await db.commit()


async def get_task_stats(tg_id: int) -> dict[str, dict]:
    """Get latest score and attempt count for each task.

    Returns dict keyed by 'lab_id:task_id' with values:
        {'attempts': int, 'score': str|None, 'passed': int|None, 'failed': int|None, 'total': int|None}
    """
    stats: dict[str, dict] = {}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Attempt counts
        async with db.execute(
            "SELECT lab_id, task_id, COUNT(*) as cnt FROM attempts WHERE tg_id = ? GROUP BY lab_id, task_id",
            (tg_id,)
        ) as cur:
            async for row in cur:
                key = f"{row['lab_id']}:{row['task_id']}"
                stats[key] = {"attempts": row["cnt"], "score": None, "passed": None, "failed": None, "total": None}

        # Latest result per task
        async with db.execute("""
            SELECT r.lab_id, r.task_id, r.score, r.passed, r.failed, r.total
            FROM results r
            INNER JOIN (
                SELECT tg_id, lab_id, task_id, MAX(timestamp) AS max_ts
                FROM results WHERE tg_id = ?
                GROUP BY lab_id, task_id
            ) latest
            ON r.tg_id = latest.tg_id AND r.lab_id = latest.lab_id
               AND r.task_id = latest.task_id AND r.timestamp = latest.max_ts
            WHERE r.tg_id = ?
        """, (tg_id, tg_id)) as cur:
            async for row in cur:
                key = f"{row['lab_id']}:{row['task_id']}"
                if key not in stats:
                    stats[key] = {"attempts": 0}
                stats[key].update({
                    "score": row["score"],
                    "passed": row["passed"],
                    "failed": row["failed"],
                    "total": row["total"],
                })

    return stats


async def has_passed_task(tg_id: int, lab_id: str, task_id: str) -> bool:
    """Check if a user has passed a task (failed_checks == 0 with total > 0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM results WHERE tg_id = ? AND lab_id = ? AND task_id = ? AND failed = 0 AND total > 0 LIMIT 1",
            (tg_id, lab_id, task_id)
        ) as cur:
            return await cur.fetchone() is not None


async def get_all_users() -> list[User]:
    """Get all users from the database."""
    users = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT tg_id, email, github_alias, tg_username, is_admin FROM users ORDER BY github_alias"
        ) as cursor:
            async for row in cursor:
                users.append(User(
                    tg_id=row["tg_id"],
                    email=row["email"],
                    github_alias=row["github_alias"],
                    tg_username=row["tg_username"],
                    is_admin=bool(row["is_admin"])
                ))
    return users
