"""
Database access layer for Waste Segregation.

Uses plain sqlite3 (Python standard library) so the prototype needs zero
external database server -- just a single .db file. Schema is created
automatically on first run.
"""
import sqlite3
from flask import g
import config

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    contact         TEXT NOT NULL UNIQUE,   -- phone or email, used to login
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK(role IN ('HOUSEHOLD','COLLECTOR','ADMIN')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wards (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ward_name           TEXT NOT NULL,
    city                TEXT NOT NULL,
    total_households    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS households (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    household_code      TEXT NOT NULL UNIQUE,     -- e.g. H-10023
    address              TEXT,
    ward_id             INTEGER REFERENCES wards(id),
    district            TEXT,
    qr_code             TEXT NOT NULL UNIQUE,      -- e.g. WASTESEG:H-10023
    user_id             INTEGER UNIQUE REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS collectors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    collector_code      TEXT NOT NULL UNIQUE,   -- e.g. C-001
    name                TEXT NOT NULL,
    phone               TEXT,
    ward_id             INTEGER REFERENCES wards(id),
    user_id             INTEGER UNIQUE REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS collections (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id        INTEGER NOT NULL REFERENCES households(id),
    collector_id        INTEGER NOT NULL REFERENCES collectors(id),
    rating              TEXT NOT NULL CHECK(rating IN ('GOOD','AVERAGE','POOR')),
    credits_awarded     INTEGER NOT NULL,
    collection_date     TEXT NOT NULL,   -- YYYY-MM-DD, one rating per household per day
    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(household_id, collection_date)
);

CREATE TABLE IF NOT EXISTS green_credit_transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id        INTEGER NOT NULL REFERENCES households(id),
    collection_id       INTEGER REFERENCES collections(id),
    amount              INTEGER NOT NULL,     -- positive = earned, negative = redeemed
    transaction_type    TEXT NOT NULL CHECK(transaction_type IN ('EARNED','REDEEMED','ADJUSTED')),
    description         TEXT,
    timestamp           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rewards (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    description         TEXT,
    credits_required    INTEGER NOT NULL,
    available           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS redemptions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id        INTEGER NOT NULL REFERENCES households(id),
    reward_id           INTEGER NOT NULL REFERENCES rewards(id),
    credits_used        INTEGER NOT NULL,
    redemption_date     TEXT NOT NULL DEFAULT (datetime('now')),
    status               TEXT NOT NULL DEFAULT 'COMPLETED'
);

CREATE TABLE IF NOT EXISTS credit_rules (
    rating   TEXT PRIMARY KEY CHECK(rating IN ('GOOD','AVERAGE','POOR')),
    credits  INTEGER NOT NULL
);
"""


def get_db():
    """Return a request-scoped sqlite3 connection (Flask 'g' pattern)."""
    if "db" not in g:
        g.db = sqlite3.connect(config.DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    """Create tables if they don't exist yet, and register teardown hook."""
    app.teardown_appcontext(close_db)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def dict_from_row(row):
    return dict(row) if row is not None else None


def rows_to_list(rows):
    return [dict(r) for r in rows]
