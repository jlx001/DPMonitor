"""SQLite-backed usage store and token-cost estimation."""
import datetime as dt
import json
import os
import sqlite3
import threading

DEFAULT_DB_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "DeepSeekMonitor")

# Unit: CNY per 1M tokens, keyed by the model name the platform reports.
# Off-peak list prices are the official V4.1 price list (USD x 6.67) and
# were confirmed against this account's own billing rows; peak prices are
# twice the off-peak price. Editable per model from the settings panel.
FLASH_PRICE = {"cache_hit": 0.02, "cache_miss": 1.0, "output": 4.0}
FLASH_PEAK_PRICE = {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0}
PRO_PRICE = {"cache_hit": 0.15, "cache_miss": 4.5, "output": 13.5}
PRO_PEAK_PRICE = {"cache_hit": 0.30, "cache_miss": 9.0, "output": 27.0}

# Retired names still show up in billing rows, but those requests are served
# by DeepSeek-V4.1-Flash and billed at the Flash price.
DEFAULT_PRICE_TABLE = {
    "default": dict(FLASH_PRICE),
    "deepseek-flash": dict(FLASH_PRICE),
    "deepseek-v4-flash": dict(FLASH_PRICE),
    "deepseek-v4-flash-vision-exp": dict(FLASH_PRICE),
    "deepseek-v4.1-flash-expires-on-0910": dict(FLASH_PRICE),
    "deepseek-v4-pro": dict(PRO_PRICE),
    "_peak": {
        "default": dict(FLASH_PEAK_PRICE),
        "deepseek-flash": dict(FLASH_PEAK_PRICE),
        "deepseek-v4-flash": dict(FLASH_PEAK_PRICE),
        "deepseek-v4-flash-vision-exp": dict(FLASH_PEAK_PRICE),
        "deepseek-v4.1-flash-expires-on-0910": dict(FLASH_PEAK_PRICE),
        "deepseek-v4-pro": dict(PRO_PEAK_PRICE),
    },
    "_peak_windows": ["09:00-12:00", "14:00-18:00"],
    "_peak_weekdays": [0, 1, 2, 3, 4],
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE,
    sk_id TEXT NOT NULL,
    cost REAL NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sk_daily_usage (
    sk_id TEXT NOT NULL,
    day TEXT NOT NULL,
    cost REAL NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sk_id, day)
);
CREATE TABLE IF NOT EXISTS sk_model_daily (
    sk_id TEXT NOT NULL,
    day TEXT NOT NULL,
    model TEXT NOT NULL,
    cost REAL NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sk_id, day, model)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    sk_id TEXT,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_bindings (
    conv_id TEXT PRIMARY KEY,
    sk_id TEXT NOT NULL,
    fingerprints TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen REAL NOT NULL,
    last_response_id TEXT,
    cost_limit_notified INTEGER NOT NULL DEFAULT 0
);
"""


class UsageStore:
    """Thread-safe local store for per-conversation and per-SK usage."""

    def __init__(self, db_path=None, price_table=None):
        self._db_path = db_path or self._default_db_path()
        self._price_table = price_table or DEFAULT_PRICE_TABLE
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript(_SCHEMA)
            columns = [
                row[1]
                for row in self._conn.execute(
                    "PRAGMA table_info(conversations)")
            ]
            if "title" not in columns:
                self._conn.execute(
                    "ALTER TABLE conversations ADD COLUMN title TEXT")
            self._conn.commit()

    @staticmethod
    def _default_db_path():
        os.makedirs(DEFAULT_DB_DIR, exist_ok=True)
        return os.path.join(DEFAULT_DB_DIR, "usage.db")

    def estimate_cost(self, model, input_tokens, output_tokens, cached_tokens,
                      at_time=None):
        prices = self._prices_for(model, at_time)
        miss_tokens = max(input_tokens - cached_tokens, 0)
        return (
            cached_tokens * prices["cache_hit"]
            + miss_tokens * prices["cache_miss"]
            + output_tokens * prices["output"]
        ) / 1_000_000.0

    def _prices_for(self, model, at_time):
        peak_prices = (self._price_table.get("_peak") or {}).get(model)
        if peak_prices and self._in_peak(at_time):
            return peak_prices
        return self._price_table.get(model) or self._price_table["default"]

    def _in_peak(self, at_time):
        now = at_time or dt.datetime.now()
        windows = self._price_table.get("_peak_windows") or []
        weekdays = self._price_table.get("_peak_weekdays") or []
        if not windows:
            return False
        if weekdays and now.weekday() not in weekdays:
            return False
        current = now.strftime("%H:%M")
        for window in windows:
            start_text, _, end_text = window.partition("-")
            if start_text <= current <= end_text:
                return True
        return False

    def record_request(self, sk_id, conv_id, model,
                       input_tokens, output_tokens, cached_tokens, title=""):
        cost = self.estimate_cost(
            model, input_tokens, output_tokens, cached_tokens)
        tokens = input_tokens + output_tokens
        now_text = dt.datetime.now().isoformat(timespec="seconds")
        day = dt.date.today().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO conversations
                    (fingerprint, sk_id, cost, tokens, requests, title,
                     status, created_at, last_seen)
                VALUES (?, ?, ?, ?, 1, ?, 'active', ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    cost = cost + excluded.cost,
                    tokens = tokens + excluded.tokens,
                    requests = requests + 1,
                    sk_id = excluded.sk_id,
                    title = excluded.title,
                    last_seen = excluded.last_seen
                """,
                (conv_id, sk_id, cost, tokens, title, now_text, now_text),
            )
            self._conn.execute(
                """
                INSERT INTO sk_daily_usage (sk_id, day, cost, tokens, requests)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(sk_id, day) DO UPDATE SET
                    cost = cost + excluded.cost,
                    tokens = tokens + excluded.tokens,
                    requests = requests + 1
                """,
                (sk_id, day, cost, tokens),
            )
            self._conn.execute(
                """
                INSERT INTO sk_model_daily
                    (sk_id, day, model, cost, input_tokens, output_tokens,
                     cached_tokens, requests)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(sk_id, day, model) DO UPDATE SET
                    cost = cost + excluded.cost,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    cached_tokens = cached_tokens + excluded.cached_tokens,
                    requests = requests + 1
                """,
                (sk_id, day, model, cost, input_tokens, output_tokens,
                 cached_tokens),
            )
            self._conn.commit()
        return cost

    def today_cost(self, sk_id):
        return self._day_cost(sk_id, dt.date.today().isoformat())

    def month_cost(self, sk_id):
        prefix = dt.date.today().isoformat()[:7]
        with self._lock:
            row = self._conn.execute(
                "SELECT SUM(cost) AS total FROM sk_daily_usage "
                "WHERE sk_id = ? AND day LIKE ?",
                (sk_id, prefix + "%"),
            ).fetchone()
        return float(row["total"] or 0.0)

    def _day_cost(self, sk_id, day):
        with self._lock:
            row = self._conn.execute(
                "SELECT cost FROM sk_daily_usage WHERE sk_id = ? AND day = ?",
                (sk_id, day),
            ).fetchone()
        return float(row["cost"]) if row else 0.0

    def sk_totals(self):
        with self._lock:
            rows = self._conn.execute(
                "SELECT sk_id, SUM(cost) AS cost, SUM(tokens) AS tokens, "
                "SUM(requests) AS requests FROM sk_daily_usage "
                "GROUP BY sk_id ORDER BY sk_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def daily_stats(self, sk_id):
        day = dt.date.today().isoformat()
        with self._lock:
            row = self._conn.execute(
                "SELECT cost, tokens, requests FROM sk_daily_usage "
                "WHERE sk_id = ? AND day = ?",
                (sk_id, day),
            ).fetchone()
        if row is None:
            return {"cost": 0.0, "tokens": 0, "requests": 0}
        return {
            "cost": float(row["cost"]),
            "tokens": int(row["tokens"]),
            "requests": int(row["requests"]),
        }

    def daily_cost_series(self, sk_id, days=7):
        end = dt.date.today()
        start = end - dt.timedelta(days=days - 1)
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, cost FROM sk_daily_usage "
                "WHERE sk_id = ? AND day >= ? AND day <= ?",
                (sk_id, start.isoformat(), end.isoformat()),
            ).fetchall()
        by_day = {row["day"]: float(row["cost"]) for row in rows}
        series = []
        for offset in range(days):
            day = start + dt.timedelta(days=offset)
            series.append({
                "day": day.isoformat()[5:],
                "cost": by_day.get(day.isoformat(), 0.0),
            })
        return series

    def daily_token_series(self, sk_id, days=7):
        end = dt.date.today()
        start = end - dt.timedelta(days=days - 1)
        with self._lock:
            rows = self._conn.execute(
                "SELECT day, tokens FROM sk_daily_usage "
                "WHERE sk_id = ? AND day >= ? AND day <= ?",
                (sk_id, start.isoformat(), end.isoformat()),
            ).fetchall()
        by_day = {row["day"]: int(row["tokens"]) for row in rows}
        series = []
        for offset in range(days):
            day = start + dt.timedelta(days=offset)
            series.append({
                "day": day.isoformat()[5:],
                "tokens": by_day.get(day.isoformat(), 0),
            })
        return series

    def model_breakdown(self, sk_id, month=False):
        if month:
            prefix = dt.date.today().isoformat()[:7]
            sql = (
                "SELECT model, SUM(cost) AS cost, "
                "SUM(input_tokens) AS input_tokens, "
                "SUM(output_tokens) AS output_tokens, "
                "SUM(cached_tokens) AS cached_tokens, "
                "SUM(requests) AS requests FROM sk_model_daily "
                "WHERE sk_id = ? AND day LIKE ? GROUP BY model ORDER BY model"
            )
            params = (sk_id, prefix + "%")
        else:
            day = dt.date.today().isoformat()
            sql = (
                "SELECT model, cost, input_tokens, output_tokens, "
                "cached_tokens, requests FROM sk_model_daily "
                "WHERE sk_id = ? AND day = ? ORDER BY model"
            )
            params = (sk_id, day)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["hit_rate"] = self._hit_rate(
                item["cached_tokens"], item["input_tokens"])
            item["tokens_total"] = (
                item["input_tokens"] + item["output_tokens"])
            result.append(item)
        return result

    @staticmethod
    def _hit_rate(cached_tokens, input_tokens):
        if input_tokens <= 0:
            return 0.0
        return round(cached_tokens / input_tokens * 100, 1)

    def conversations_by_sk(self, sk_id, limit=10):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conversations WHERE sk_id = ? "
                "ORDER BY last_seen DESC LIMIT ?",
                (sk_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def conversations(self, limit=50):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conversations ORDER BY last_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def touch_conversation(self, conv_id):
        """Refresh last_seen when a new request for a conversation arrives."""
        with self._lock:
            now_text = dt.datetime.now().isoformat(timespec="seconds")
            cursor = self._conn.execute(
                "UPDATE conversations SET last_seen = ? "
                "WHERE fingerprint = ?",
                (now_text, conv_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def clear_conversations(self):
        """Remove conversation display rows; keep usage aggregates intact."""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM conversations")
            self._conn.commit()
            return cursor.rowcount

    def conversation_cost(self, conv_id):
        with self._lock:
            row = self._conn.execute(
                "SELECT cost FROM conversations WHERE fingerprint = ?",
                (conv_id,),
            ).fetchone()
        return float(row["cost"]) if row else 0.0

    def save_conversation_binding(self, conv_id, sk_id, fingerprints,
                                  created_at, last_seen, last_response_id,
                                  cost_limit_notified):
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO conversation_bindings
                    (conv_id, sk_id, fingerprints, created_at, last_seen,
                     last_response_id, cost_limit_notified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conv_id) DO UPDATE SET
                    sk_id = excluded.sk_id,
                    fingerprints = excluded.fingerprints,
                    created_at = excluded.created_at,
                    last_seen = excluded.last_seen,
                    last_response_id = excluded.last_response_id,
                    cost_limit_notified = excluded.cost_limit_notified
                """,
                (conv_id, sk_id, json.dumps(fingerprints), created_at,
                 last_seen, last_response_id,
                 1 if cost_limit_notified else 0),
            )
            self._conn.commit()

    def load_conversation_bindings(self, limit=None):
        sql = ("SELECT * FROM conversation_bindings "
               "ORDER BY last_seen DESC")
        params = []
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["fingerprints"] = json.loads(item["fingerprints"] or "[]")
            result.append(item)
        return result

    def delete_conversation_binding(self, conv_id):
        with self._lock:
            self._conn.execute(
                "DELETE FROM conversation_bindings WHERE conv_id = ?",
                (conv_id,),
            )
            self._conn.commit()

    def add_event(self, kind, message, sk_id=None):
        now_text = dt.datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (ts, kind, sk_id, message) "
                "VALUES (?, ?, ?, ?)",
                (now_text, kind, sk_id, message),
            )
            self._conn.commit()

    def events(self, limit=50):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        with self._lock:
            self._conn.close()
