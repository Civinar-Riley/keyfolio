"""备份导入优化回归：python scripts/test_backup_optimizations.py。

只使用临时数据库、假凭证和 .invalid 地址，不启动服务或定时任务。
"""
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_RUNTIME = tempfile.TemporaryDirectory(prefix="keyfolio-backup-optimizations-")
_ENV = {key: os.environ.get(key) for key in ("KEYFOLIO_DATA_DIR", "KEYFOLIO_PORT")}
os.environ["KEYFOLIO_DATA_DIR"] = _RUNTIME.name
os.environ["KEYFOLIO_PORT"] = "39023"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, crypto, db  # noqa: E402
from app.routers import auth_routes, backup, settings  # noqa: E402

APP = FastAPI()
for router in (auth_routes.router, backup.router, settings.router):
    APP.include_router(router)

BACKUP_PASSWORD = "test-backup-password-123"
SOURCE_SETTINGS = {
    "sched_enabled": True, "sched_balance_hours": 0, "sched_models_hours": 1.5,
}
DEST_SETTINGS = {
    "sched_enabled": False, "sched_balance_hours": 7, "sched_models_hours": 18,
}
RUNTIME_SETTINGS = {
    "last_balance_run": 1234567, "last_models_run": 2345678,
    "runtime_marker": "keep local state",
}


def document(channel_count=1, per_channel=3):
    data = {table: [] for table in backup.TABLES}
    for channel_id in range(1, channel_count + 1):
        data["channels"].append({
            "id": channel_id, "name": f"Channel {channel_id}", "type": "openai",
            "base_url": f"https://channel-{channel_id}.invalid/v1",
            "created_at": "2026-01-01T00:00:00Z", "unknown_field": "ignored",
        })
        for index in range(per_channel):
            key_id = (channel_id - 1) * per_channel + index + 1
            data["keys"].append({
                "id": key_id, "channel_id": channel_id, "name": "Shared key",
                "value": f"sk-test-{channel_id}-{index}", "value_encrypted": False,
                "created_at": "2026-01-01T00:00:00Z", "balance": index + 1,
                "notes": "backup notes", "unknown_field": "ignored",
            })
            data["models"].append({
                "id": key_id, "channel_id": channel_id, "model_id": f"model-{index}",
                "auto_disabled": index % 2, "unknown_field": "ignored",
            })
            data["balance_records"].append({
                "id": key_id, "key_id": key_id, "balance": index + 1,
                "recorded_at": "2026-01-01T00:00:00Z", "unknown_field": "ignored",
            })
    data["templates"] = [
        {"id": index + 1, "name": f"Test template {index}", "json_template": "{}",
         "unknown_field": "ignored"}
        for index in range(3)
    ]
    return {"format": backup.FORMAT, "version": 1, "encrypted": False, "data": data}


class Instance:
    def __init__(self, directory, name):
        self.path = directory / (name + ".db")
        self.client = TestClient(APP, raise_server_exceptions=False)
        self.state = (None, {}, set())
        self.activate()
        db.init(self.path)
        self.req("/api/auth/setup", {"password": f"test-{name}-password-123"})

    def activate(self):
        db._db_path = str(self.path)
        auth.State.data_key, auth.State.sessions, auth.State.locked = self.state

    def req(self, path, body, expected=200, method="POST"):
        self.activate()
        try:
            response = self.client.request(
                method, path, content=json.dumps(body),
                headers={"Content-Type": "application/json"},
            )
            if response.status_code != expected:
                raise AssertionError((response.status_code, response.text))
            return response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text
        finally:
            self.state = (auth.State.data_key, auth.State.sessions, auth.State.locked)

    def export(self, encrypted=False):
        return self.req("/api/backup/export", {"password": BACKUP_PASSWORD if encrypted else ""})

    def restore(self, doc, mode="merge", restore_settings=None, expected=200):
        body = {"backup": doc, "mode": mode,
                "password": BACKUP_PASSWORD if doc["encrypted"] else ""}
        if restore_settings is not None:
            body["restore_settings"] = restore_settings
        return self.req("/api/backup/import", body, expected)

    def set_settings(self, values):
        self.activate()
        with db.get_conn() as conn:
            for key, value in values.items():
                db.set_setting(key, value, conn=conn)

    def snapshot(self):
        self.activate()
        with db.get_conn() as conn:
            result = {
                table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
                for table in backup.TABLES
            }
            result["settings"] = {
                row["key"]: json.loads(row["value"])
                for row in conn.execute("SELECT key, value FROM settings")
            }
            return result


class CountedRows(list):
    def __init__(self, rows):
        super().__init__(rows)
        self.iterations = 0
        self.visits = 0

    def __iter__(self):
        self.iterations += 1
        for row in super().__iter__():
            self.visits += 1
            yield row


@contextmanager
def trace_sql():
    statements = []
    original = db.get_conn

    @contextmanager
    def get_conn():
        with original() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    with patch.object(db, "get_conn", get_conn):
        yield statements


def sql_counts(statements, pattern):
    return Counter(
        match.group(1).lower()
        for statement in statements
        if (match := re.search(pattern, statement, re.IGNORECASE))
    )


class BackupOptimizations(unittest.TestCase):
    def setUp(self):
        self.previous = (db._db_path, auth.State.data_key, auth.State.sessions, auth.State.locked)
        self.temp = tempfile.TemporaryDirectory(dir=_RUNTIME.name)
        self.directory = Path(self.temp.name)
        self.instances = []

    def tearDown(self):
        for instance in self.instances:
            instance.client.close()
        auth.drop_all_sessions()
        db._db_path, auth.State.data_key, auth.State.sessions, auth.State.locked = self.previous
        self.temp.cleanup()

    def instance(self, name):
        instance = Instance(self.directory, name)
        self.instances.append(instance)
        return instance

    def source(self):
        source = self.instance("source")
        source.restore(document(), "overwrite")
        source.set_settings({**SOURCE_SETTINGS, "last_balance_run": 999, "last_models_run": 888})
        return source

    def destination(self, name="destination"):
        dest = self.instance(name)
        local = document()
        local["data"]["channels"][0]["name"] = "Local channel"
        dest.restore(local, "overwrite")
        dest.set_settings({**DEST_SETTINGS, **RUNTIME_SETTINGS})
        return dest

    def assert_settings(self, instance, expected):
        actual = instance.snapshot()["settings"]
        self.assertEqual({key: actual[key] for key in expected}, expected)

    def check_settings_round_trip(self, encrypted):
        source = self.source()
        doc = source.export(encrypted)
        self.assertEqual(doc["version"], 1)
        for mode in ("merge", "overwrite"):
            with self.subTest(mode=mode):
                dest = self.destination(mode)
                result = dest.restore(doc, mode, restore_settings=True)
                self.assertTrue(result["settings_restored"])
                self.assert_settings(dest, {**SOURCE_SETTINGS, **RUNTIME_SETTINGS})
                rows = dest.snapshot()["keys"]
                self.assertEqual(len(rows), 6 if mode == "merge" else 3)
                data_key = source.state[0] if encrypted and mode == "overwrite" else dest.state[0]
                self.assertEqual(
                    {crypto.field_decrypt(data_key, row["value_enc"]) for row in rows},
                    {f"sk-test-1-{index}" for index in range(3)},
                )

    def test_plain_settings_round_trip(self):
        self.check_settings_round_trip(False)

    def test_encrypted_settings_round_trip(self):
        self.check_settings_round_trip(True)

    def test_export_settings_defaults_and_allowlist(self):
        source = self.instance("source")
        source.set_settings(RUNTIME_SETTINGS)
        doc = source.export()
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["data"]["settings"], {
            "sched_enabled": False, "sched_balance_hours": 12, "sched_models_hours": 24,
        })
        self.assertNotIn("auth", doc["data"])

    def test_export_settings_share_data_snapshot(self):
        source = self.source()
        original = backup._export_keys

        def export_keys(conn, data_key, encrypt):
            rows = original(conn, data_key, encrypt)
            source.set_settings(DEST_SETTINGS)
            return rows

        with patch.object(backup, "_export_keys", side_effect=export_keys):
            doc = source.export()
        self.assertEqual(doc["data"]["settings"], SOURCE_SETTINGS)
        self.assert_settings(source, DEST_SETTINGS)

    def test_unselected_settings_keep_destination(self):
        source = self.source()
        for encrypted in (False, True):
            doc = source.export(encrypted)
            for mode in ("merge", "overwrite"):
                for selected in (None, False):
                    with self.subTest(encrypted=encrypted, mode=mode, selected=selected):
                        dest = self.destination(f"dest-{encrypted}-{mode}-{selected}")
                        result = dest.restore(doc, mode, restore_settings=selected)
                        self.assertFalse(result["settings_restored"])
                        self.assert_settings(dest, {**DEST_SETTINGS, **RUNTIME_SETTINGS})

    def test_unselected_invalid_settings_are_ignored(self):
        dest = self.destination()
        doc = document()
        for mode in ("merge", "overwrite"):
            for invalid in (None, [], {"sched_enabled": "yes"}):
                with self.subTest(mode=mode, invalid=invalid):
                    doc["data"]["settings"] = invalid
                    self.assertFalse(dest.restore(doc, mode)["settings_restored"])
                    self.assert_settings(dest, {**DEST_SETTINGS, **RUNTIME_SETTINGS})

    def test_old_backups_keep_destination_settings(self):
        source = self.source()
        for encrypted in (False, True):
            doc = source.export(encrypted)
            if encrypted:
                kek = crypto.derive_kek(BACKUP_PASSWORD, doc["kdf"], crypto.AAD_BACKUP)
                data = json.loads(crypto.decrypt_payload(doc, kek))
                del data["settings"]
                doc.update(crypto.encrypt_payload(kek, json.dumps(data).encode()))
            else:
                del doc["data"]["settings"]
            for mode in ("merge", "overwrite"):
                with self.subTest(encrypted=encrypted, mode=mode):
                    dest = self.destination(f"dest-{encrypted}-{mode}")
                    result = dest.restore(doc, mode, restore_settings=True)
                    self.assertFalse(result["settings_restored"])
                    self.assert_settings(dest, {**DEST_SETTINGS, **RUNTIME_SETTINGS})

    def test_invalid_settings_roll_back_all_rows(self):
        dest = self.destination()
        before = dest.snapshot()
        doc = document()
        invalid = [None, [], {}, {"sched_enabled": True}]
        invalid.extend({key: value for key, value in SOURCE_SETTINGS.items() if key != missing}
                       for missing in SOURCE_SETTINGS)
        invalid.extend({**SOURCE_SETTINGS, "sched_enabled": value} for value in (0, 1, "true", None))
        for key in ("sched_balance_hours", "sched_models_hours"):
            invalid.extend({**SOURCE_SETTINGS, key: value}
                           for value in (-1, True, "2", None, [], float("nan"),
                                         float("inf"), float("-inf"), 10**400))
        for mode in ("merge", "overwrite"):
            for index, values in enumerate(invalid):
                with self.subTest(mode=mode, invalid=index):
                    doc["data"]["settings"] = values
                    with trace_sql() as statements:
                        dest.restore(doc, mode, restore_settings=True, expected=400)
                    self.assertTrue(any(sql.startswith("INSERT INTO keys") for sql in statements))
                    self.assertIn("ROLLBACK", statements)
                    self.assertEqual(dest.snapshot(), before)

    def test_encrypted_overwrite_invalid_settings_keeps_auth_and_session(self):
        doc = self.source().export(True)
        kek = crypto.derive_kek(BACKUP_PASSWORD, doc["kdf"], crypto.AAD_BACKUP)
        data = json.loads(crypto.decrypt_payload(doc, kek))
        data["settings"]["sched_models_hours"] = -1
        doc.update(crypto.encrypt_payload(kek, json.dumps(data).encode()))
        dest = self.destination()
        before = dest.snapshot()
        dest.restore(doc, "overwrite", restore_settings=True, expected=400)
        self.assertEqual(dest.snapshot(), before)
        self.assertTrue(dest.req("/api/auth/status", {}, method="GET")["authenticated"])

    def test_settings_write_failure_rolls_back_data_auth_and_settings(self):
        doc = self.source().export(True)
        original = db.set_setting

        def set_setting(key, value, *, conn=None):
            original(key, value, conn=conn)
            if key == "sched_balance_hours":
                raise sqlite3.OperationalError("simulated setting write failure")

        for mode in ("merge", "overwrite"):
            with self.subTest(mode=mode):
                dest = self.destination(mode)
                before = dest.snapshot()
                with patch.object(db, "set_setting", side_effect=set_setting):
                    dest.restore(doc, mode, restore_settings=True, expected=500)
                self.assertEqual(dest.snapshot(), before)
                self.assertTrue(dest.req("/api/auth/status", {}, method="GET")["authenticated"])

    def test_data_failure_keeps_settings(self):
        dest = self.destination()
        before = dest.snapshot()
        doc = document()
        doc["data"]["settings"] = SOURCE_SETTINGS
        doc["data"]["templates"] = [{"id": 99, "name": "Missing template body"}]
        for mode in ("merge", "overwrite"):
            with self.subTest(mode=mode):
                dest.restore(doc, mode, restore_settings=True, expected=500)
                self.assertEqual(dest.snapshot(), before)

    def test_restore_only_writes_scheduler_allowlist(self):
        dest = self.destination()
        before = dest.snapshot()["settings"]
        doc = document()
        doc["data"]["settings"] = {
            **SOURCE_SETTINGS, "last_balance_run": 0, "last_models_run": 0,
            "runtime_marker": "backup runtime", auth.K_PW_HASH: "backup credential",
            "schema_version": -1,
        }
        for mode in ("merge", "overwrite"):
            with self.subTest(mode=mode):
                self.assertTrue(dest.restore(doc, mode, restore_settings=True)["settings_restored"])
                self.assertEqual(dest.snapshot()["settings"], {**before, **SOURCE_SETTINGS})

    def test_same_name_keys_and_duplicate_channels_remain_idempotent(self):
        dest = self.instance("destination")
        local = document(per_channel=1)
        local["data"]["keys"][0]["notes"] = "local notes"
        local["data"]["keys"][0]["balance"] = 90
        local["data"]["balance_records"][0]["balance"] = 90
        local["data"]["models"][0]["notes"] = "local model notes"
        dest.restore(local, "overwrite")
        doc = document(channel_count=4, per_channel=3)
        channels = doc["data"]["channels"]
        channels[1]["name"] = channels[0]["name"]
        channels[1]["base_url"] = channels[0]["base_url"].upper()
        channels[2]["base_url"] = channels[0]["base_url"]  # URL 相同、名称不同仍是新渠道
        channels[3]["name"] = channels[0]["name"]  # 名称相同、URL 不同仍是新渠道
        keys = doc["data"]["keys"]
        keys[3]["value"] = keys[1]["value"]  # 本次导入中出现的重复值
        keys[4]["value"] = keys[0]["value"]  # 相同值、不同名应保留
        keys[4]["name"] = "Other name"
        result = dest.restore(doc)
        self.assertEqual({key: result[key] for key in ("channels", "keys", "models", "templates")},
                         {"channels": 2, "keys": 10, "models": 8, "templates": 0})
        data = dest.export()["data"]
        retained = next(row for row in data["keys"] if row["id"] == 1)
        self.assertEqual((retained["notes"], retained["balance"]), ("local notes", 90))
        self.assertEqual(data["models"][0]["notes"], "local model notes")
        channel_keys = [row for row in data["keys"] if row["channel_id"] == 1]
        self.assertEqual({(row["name"], row["value"]) for row in channel_keys}, {
            ("Shared key", "sk-test-1-0"), ("Shared key", "sk-test-1-1"),
            ("Shared key", "sk-test-1-2"), ("Other name", "sk-test-1-0"),
            ("Shared key", "sk-test-2-2"),
        })
        self.assertEqual(len(data["balance_records"]), 11)
        self.assertEqual([row["balance"] for row in data["balance_records"] if row["key_id"] == 1], [90])
        inserted = next(row for row in channel_keys if row["value"] == "sk-test-1-1")
        self.assertEqual([row["balance"] for row in data["balance_records"] if row["key_id"] == inserted["id"]], [2])
        before = dest.snapshot()
        repeated = dest.restore(doc)
        self.assertEqual({key: repeated[key] for key in ("channels", "keys", "models", "templates")},
                         {"channels": 0, "keys": 0, "models": 0, "templates": 0})
        self.assertEqual(dest.snapshot(), before)

    def test_overwrite_reads_columns_once_per_table_per_import(self):
        dest = self.instance("destination")
        doc = document(channel_count=12, per_channel=5)
        for attempt in range(2):
            with self.subTest(attempt=attempt), trace_sql() as statements:
                dest.restore(doc, "overwrite")
            self.assertEqual(sql_counts(statements, r"PRAGMA table_info\((\w+)\)"),
                             Counter({table: 1 for table in backup.TABLES}))
        data = dest.export()["data"]
        self.assertEqual(len(data["keys"]), 60)
        self.assertEqual(len(data["balance_records"]), 60)
        self.assertEqual([row["auto_disabled"] for row in data["models"][:5]], [0, 1, 0, 1, 0])
        self.assertTrue(all("unknown_field" not in row for table in backup.TABLES for row in data[table]))

    def test_merge_groups_once_and_prefetches_deduplication_queries(self):
        for channel_count in (1, 8, 24):
            with self.subTest(channels=channel_count):
                dest = self.instance(f"destination-{channel_count}")
                data = document(channel_count, per_channel=4)["data"]
                data["keys"] = CountedRows(data["keys"])
                data["models"] = CountedRows(data["models"])
                for attempt in range(2):
                    dest.activate()
                    with trace_sql() as statements, patch.object(
                        crypto, "field_decrypt", wraps=crypto.field_decrypt,
                    ) as decrypt:
                        stats = backup._import_merge(data, dest.state[0], None)
                    expected_count = channel_count * 4 if attempt == 0 else 0
                    self.assertEqual(stats["keys"], expected_count)
                    self.assertEqual(stats["models"], expected_count)
                    for table in ("keys", "models"):
                        self.assertEqual(data[table].iterations, attempt + 1)
                        self.assertEqual(data[table].visits, (attempt + 1) * channel_count * 4)
                    self.assertEqual(decrypt.call_count, channel_count * 4 if attempt else 0)
                    self.assertEqual(sql_counts(statements, r"PRAGMA table_info\((\w+)\)"),
                                     Counter({table: 1 for table in backup.TABLES}))
                    self.assertEqual(sql_counts(statements, r"\bFROM (channels|keys|models|templates)\b"),
                                     Counter({"channels": 1, "keys": 1, "models": 1, "templates": 1}))

    def test_scheduler_update_uses_same_finite_interval_validation(self):
        dest = self.destination()
        before = dest.snapshot()
        for field in ("balance_interval_hours", "model_interval_hours"):
            for value in (-1, float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, value=value):
                    dest.req("/api/settings/scheduler", {
                        "enabled": True, "balance_interval_hours": 1, "model_interval_hours": 2,
                        field: value,
                    }, expected=400, method="PUT")
                    self.assertEqual(dest.snapshot(), before)
        dest.req("/api/settings/scheduler", {
            "enabled": True, "balance_interval_hours": 0, "model_interval_hours": 1.5,
        }, method="PUT")
        self.assert_settings(dest, {**SOURCE_SETTINGS, **RUNTIME_SETTINGS})


def main():
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(BackupOptimizations)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        auth.drop_all_sessions()
        db._db_path = ""
        _RUNTIME.cleanup()
        for key, value in _ENV.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
