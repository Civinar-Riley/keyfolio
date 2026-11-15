"""共享余额账户、元数据读取与历史查询的隔离回归。"""
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(prefix="keyfolio-optimizations-")
os.environ["KEYFOLIO_DATA_DIR"] = _tmp.name
os.environ["KEYFOLIO_PORT"] = "39016"

from fastapi.testclient import TestClient

from app import crypto, db
from app.main import app


class OptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.post("/api/auth/setup", json={"password": "optimization-password-123"}).raise_for_status()

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def setUp(self):
        with db.get_conn() as conn:
            conn.execute("DELETE FROM channels")
        self.channel_id = self.add_channel("Primary")

    def add_channel(self, name):
        response = self.client.post("/api/channels", json={
            "name": name, "type": "gateway", "base_url": "https://example.test/v1",
        })
        response.raise_for_status()
        return response.json()["id"]

    def add_key(self, account="", balance=None, currency="USD", updated="2026-01-01T00:00:00Z", channel_id=None):
        response = self.client.post(f"/api/channels/{channel_id or self.channel_id}/keys", json={
            "name": "test-key", "value": "sk-optimization-0123456789abcdef", "balance_account": account,
        })
        response.raise_for_status()
        key_id = response.json()["id"]
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE keys SET balance=?, currency=?, balance_updated_at=? WHERE id=?",
                (balance, currency, updated, key_id),
            )
        return key_id

    def summary(self):
        response = self.client.get("/api/dashboard")
        response.raise_for_status()
        return response.json()["summary"]

    def test_balance_account_create_edit_and_clear(self):
        key_id = self.add_key("  Shared account  ")
        key = self.client.get("/api/channels").json()["channels"][0]["keys"][0]
        self.assertEqual(key["balance_account"], "Shared account")
        for account, expected in (("  Other account ", "Other account"), ("  ", "")):
            with self.subTest(account=account):
                self.client.put(f"/api/keys/{key_id}", json={"balance_account": account}).raise_for_status()
                with db.get_conn() as conn:
                    self.assertEqual(conn.execute("SELECT balance_account FROM keys WHERE id=?", (key_id,)).fetchone()[0], expected)

    def test_unassigned_keys_keep_independent_balances(self):
        self.add_key(balance=42.5)
        self.add_key(balance=42.5)
        summary = self.summary()
        self.assertEqual(summary["balance_by_currency"], {"USD": 85.0})
        self.assertEqual(summary["shared_balance_accounts"], 0)
        self.assertEqual(summary["keys_total"], 2)

    def test_shared_account_counts_latest_observation_once(self):
        self.add_key("shared", 42.5, updated="2026-01-02T00:00:00Z")
        self.add_key("shared", 100, updated="2026-01-01T00:00:00Z")
        self.add_key("another", 10)
        summary = self.summary()
        self.assertEqual(summary["balance_by_currency"], {"USD": 52.5})
        self.assertEqual(summary["shared_balance_accounts"], 1)
        self.assertEqual(summary["keys_total"], 3)
        self.assertEqual(summary["keys_active"], 3)

    def test_shared_accounts_are_scoped_to_channel_and_currency(self):
        self.add_key("shared", 12, "USD")
        self.add_key("shared", 14, "USD", updated="2026-01-03T00:00:00Z")
        self.add_key("shared", 80, "CNY")
        other = self.add_channel("Another account holder")
        self.add_key("shared", 5, "USD", channel_id=other)
        self.assertEqual(self.summary()["balance_by_currency"], {"USD": 19.0, "CNY": 80.0})

    def test_unknown_balance_does_not_erase_account_balance(self):
        self.add_key("shared", 42.5)
        self.add_key("shared", None, updated="2026-01-04T00:00:00Z")
        self.assertEqual(self.summary()["balance_by_currency"], {"USD": 42.5})

    def test_same_timestamp_uses_last_key_id_deterministically(self):
        self.add_key("shared", 42.5)
        self.add_key("shared", 10)
        self.assertEqual(self.summary()["balance_by_currency"], {"USD": 10.0})

    def test_metadata_and_dashboard_do_not_decrypt_keys(self):
        self.add_key("shared", 42.5)
        with patch.object(crypto, "field_decrypt", side_effect=AssertionError("Metadata must not decrypt credentials")):
            metadata = self.client.get("/api/metadata")
            dashboard = self.client.get("/api/dashboard")
        metadata.raise_for_status()
        dashboard.raise_for_status()
        self.assertEqual(set(metadata.json()), {"channel_types", "providers", "model_types"})
        self.assertEqual(dashboard.json()["channel_types"], metadata.json()["channel_types"])
        self.assertNotIn("value_enc", dashboard.text)
        self.assertNotIn("sk-optimization", dashboard.text)
        with TestClient(app) as anonymous:
            self.assertEqual(anonymous.get("/api/metadata").status_code, 401)
        self.client.post("/api/auth/lock").raise_for_status()
        try:
            self.assertEqual(self.client.get("/api/metadata").status_code, 423)
        finally:
            self.client.post("/api/auth/unlock", json={"password": "optimization-password-123"}).raise_for_status()

    def test_trend_filters_dates_in_sql_and_preserves_order(self):
        key_id = self.add_key(balance=20)
        other_key = self.add_key(balance=100)
        with db.get_conn() as conn:
            conn.executemany(
                "INSERT INTO balance_records(key_id, balance, currency, recorded_at) VALUES(?,?,?,?)",
                [
                    (key_id, 99, "USD", "2026-01-01T11:59:59Z"),
                    (key_id, 50, "USD", "2026-01-01T12:00:00Z"),
                    (key_id, 20, "CNY", "2026-01-15T12:00:00Z"),
                    (key_id, 19, "CNY", "2026-01-15T12:00:00Z"),
                    (other_key, 100, "USD", "2026-01-15T12:00:00Z"),
                ],
            )
        statements = []
        get_conn = db.get_conn

        @contextmanager
        def trace_conn():
            with get_conn() as conn:
                conn.set_trace_callback(statements.append)
                yield conn

        with patch("app.routers.dashboard.datetime") as clock, patch.object(db, "get_conn", trace_conn):
            clock.now.return_value = datetime(2026, 1, 31, 12, tzinfo=timezone.utc)
            response = self.client.get(f"/api/dashboard/trend?key_id={key_id}&days=30")
        response.raise_for_status()
        self.assertEqual([r["balance"] for r in response.json()["records"]], [50, 20, 19])
        queries = [s for s in statements if "FROM balance_records" in s]
        self.assertEqual(len(queries), 1)
        self.assertIn("recorded_at>=", queries[0])
        with db.get_conn() as conn:
            plan = conn.execute(
                "EXPLAIN QUERY PLAN SELECT balance, currency, recorded_at FROM balance_records "
                "WHERE key_id=? AND recorded_at>=? ORDER BY recorded_at ASC, id ASC",
                (key_id, "2026-01-01T12:00:00Z"),
            ).fetchall()
        self.assertTrue(any("idx_balance_key_time" in r["detail"] and "recorded_at>" in r["detail"] for r in plan))

    def test_version_two_database_preserves_keys_on_upgrade(self):
        active_path = db._db_path
        path = Path(_tmp.name) / "old-version.db"
        conn = sqlite3.connect(path)
        try:
            conn.executescript(db.MIGRATIONS[1])
            conn.executescript(db.MIGRATIONS[2])
            conn.execute("INSERT INTO settings VALUES('schema_version', '2')")
            conn.execute("INSERT INTO channels(id, name, base_url, created_at) VALUES(1, 'Old channel', 'https://example.test', '2026-01-01T00:00:00Z')")
            conn.execute("INSERT INTO keys(channel_id, name, value_enc, balance, currency, created_at) VALUES(1, 'Old key', 'unchanged-ciphertext', 42.5, 'USD', '2026-01-01T00:00:00Z')")
            conn.commit()
        finally:
            conn.close()
        try:
            db.init(path)
            db.init(path)
            with db.get_conn() as conn:
                row = conn.execute("SELECT * FROM keys").fetchone()
                self.assertEqual(row["balance_account"], "")
                self.assertEqual(row["value_enc"], "unchanged-ciphertext")
                self.assertEqual(row["balance"], 42.5)
                self.assertEqual(db.get_setting("schema_version", conn=conn), 3)
        finally:
            db._db_path = active_path

    def test_backup_roundtrip_keeps_account_and_old_backups_default_to_empty(self):
        self.add_key("shared", 42.5)
        self.add_key("shared", 42.5)
        backup = self.client.post("/api/backup/export", json={}).json()
        self.assertEqual([key["balance_account"] for key in backup["data"]["keys"]], ["shared", "shared"])
        with db.get_conn() as conn:
            conn.execute("DELETE FROM channels")
        self.client.post("/api/backup/import", json={"backup": backup, "mode": "overwrite"}).raise_for_status()
        self.assertEqual(self.summary()["balance_by_currency"], {"USD": 42.5})
        for row in backup["data"]["keys"]:
            row.pop("balance_account")
        self.client.post("/api/backup/import", json={"backup": backup, "mode": "overwrite"}).raise_for_status()
        self.assertEqual(self.summary()["balance_by_currency"], {"USD": 85.0})


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _tmp.cleanup()
