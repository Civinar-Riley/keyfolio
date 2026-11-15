"""认证与备份回归：python scripts/test_backup_regressions.py。

只使用临时数据库，不启动服务、定时任务或外部平台；结束后删除临时数据。
"""
from contextlib import contextmanager
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
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

_RUNTIME = tempfile.TemporaryDirectory(prefix="keyfolio-backup-tests-")
_ENV = {key: os.environ.get(key) for key in ("KEYFOLIO_DATA_DIR", "KEYFOLIO_PORT")}
os.environ["KEYFOLIO_DATA_DIR"] = _RUNTIME.name
os.environ["KEYFOLIO_PORT"] = "39021"

import pyotp  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, crypto, db, paths  # noqa: E402
from app.routers import auth_routes, backup, channels, quickadd  # noqa: E402

PASSWORD = "source-password-123"
OTHER_PASSWORD = "destination-password-456"
BACKUP_PASSWORD = "backup-password-789"

APP = FastAPI()
for router in (auth_routes.router, backup.router, channels.router, quickadd.router):
    APP.include_router(router)


def checked(response, expected=200):
    if response.status_code != expected:
        raise AssertionError((response.status_code, response.text))
    return response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text


class Instance:
    def __init__(self, directory, name, password=PASSWORD, port=39021, cookies=None):
        self.path = directory / (name + ".db")
        self.cookie_name = f"kf_session_{port}"
        self.password = password
        self.client = TestClient(
            APP, base_url=f"http://127.0.0.1:{port}", cookies=cookies,
            raise_server_exceptions=False,
        )
        self.state = (None, {}, set())
        self.activate()
        db.init(self.path)
        self.recovery_code = self.req("POST", "/api/auth/setup", {"password": password})["recovery_code"]

    def activate(self):
        db._db_path = str(self.path)
        auth.SESSION_COOKIE = self.cookie_name
        auth.State.data_key, auth.State.sessions, auth.State.locked = self.state

    def save_state(self):
        self.state = (auth.State.data_key, auth.State.sessions, auth.State.locked)

    def req(self, method, path, body=None, expected=200):
        self.activate()
        try:
            kwargs = {"json": body} if body is not None else {}
            return checked(self.client.request(method, path, **kwargs), expected)
        finally:
            self.save_state()

    def channel(self, name="Shared", url="https://example.invalid/v1"):
        return self.req("POST", "/api/channels", {"name": name, "type": "openai", "base_url": url})["id"]

    def key(self, channel_id, name, value, notes=""):
        return self.req("POST", f"/api/channels/{channel_id}/keys", {"name": name, "value": value, "notes": notes})["id"]

    def balance(self, key_id, value):
        return self.req("POST", f"/api/keys/{key_id}/balance-manual", {"balance": value, "currency": "USD"})

    def export(self, encrypted=False):
        return self.req("POST", "/api/backup/export", {"password": BACKUP_PASSWORD if encrypted else ""})

    def restore(self, document, mode="merge", expected=200):
        return self.req("POST", "/api/backup/import", {
            "backup": document, "mode": mode,
            "password": BACKUP_PASSWORD if document["encrypted"] else "",
        }, expected=expected)

    def values(self):
        result = {}
        for channel in self.req("GET", "/api/channels")["channels"]:
            for key in channel["keys"]:
                value = self.req("POST", f"/api/keys/{key['id']}/reveal", {})["value"]
                result[value] = key
        return result

    def history(self, key_id):
        return self.req("GET", f"/api/keys/{key_id}/balance-history")["records"]

    def auth_state(self):
        self.activate()
        return auth.export_auth_state()

    def enable_totp(self):
        secret = self.req("POST", "/api/auth/totp/setup", {})["secret"]
        codes = self.req("POST", "/api/auth/totp/enable", {"code": pyotp.TOTP(secret).now()})["backup_codes"]
        return secret, codes


class BackupRegressions(unittest.TestCase):
    def setUp(self):
        self.previous = (
            db._db_path, auth.State.data_key, auth.State.sessions,
            auth.State.locked, auth.SESSION_COOKIE,
        )
        self.temp = tempfile.TemporaryDirectory(dir=_RUNTIME.name)
        self.directory = Path(self.temp.name)
        self.instances = []

    def tearDown(self):
        for instance in self.instances:
            instance.client.close()
        auth.drop_all_sessions()
        (db._db_path, auth.State.data_key, auth.State.sessions,
         auth.State.locked, auth.SESSION_COOKIE) = self.previous
        self.temp.cleanup()

    def instance(self, *args, **kwargs):
        instance = Instance(self.directory, *args, **kwargs)
        self.instances.append(instance)
        return instance

    def assert_no_additions(self, result):
        self.assertEqual({k: result[k] for k in ("channels", "keys", "models", "templates")},
                         {"channels": 0, "keys": 0, "models": 0, "templates": 0})

    def check_merge(self, encrypted):
        source = self.instance("source")
        channel_id = source.channel()
        key_ids = [source.key(channel_id, f"Key {i}", f"sk-source-{i}") for i in range(1, 4)]
        source.req("DELETE", f"/api/keys/{key_ids[1]}")
        new_key = source.req("POST", "/api/quickadd/save", {
            "base_url": "https://example.invalid/v1", "key": "sk-source-4",
        })["key_id"]
        source.balance(key_ids[0], 10)
        source.balance(key_ids[2], 30)
        source.balance(new_key, 40)
        document = source.export(encrypted)

        dest = self.instance("destination", OTHER_PASSWORD)
        dest_channel = dest.channel()
        retained = dest.key(dest_channel, "Key 3", "sk-source-3", notes="keep local notes")
        dest.balance(retained, 300)
        original_ciphertext = dest.auth_state()
        result = dest.restore(document)
        self.assertEqual(result["keys"], 2)
        values = dest.values()
        self.assertEqual(set(values), {"sk-source-1", "sk-source-3", "sk-source-4"})
        self.assertEqual(values["sk-source-3"]["notes"], "keep local notes")
        self.assertEqual(values["sk-source-3"]["balance"], 300)
        self.assertEqual(values["sk-source-4"]["name"], "Key 3")
        for value, balances in (("sk-source-1", [10]), ("sk-source-3", [300]), ("sk-source-4", [40])):
            self.assertEqual([r["balance"] for r in dest.history(values[value]["id"])], balances)
        first_data = dest.export()["data"]
        self.assert_no_additions(dest.restore(document))
        self.assertEqual(dest.export()["data"], first_data)
        self.assertEqual(dest.auth_state(), original_ciphertext)
        dest.req("POST", "/api/auth/logout", {})
        dest.req("POST", "/api/auth/login", {"password": OTHER_PASSWORD})
        self.assertEqual(set(dest.values()), set(values))

    def test_plain_merge_preserves_same_name_values_and_history(self):
        self.check_merge(False)

    def test_encrypted_merge_preserves_same_name_values_and_history(self):
        self.check_merge(True)

    def test_duplicate_channels_merge_once_and_stay_idempotent(self):
        source = self.instance("source")
        for i in range(2):
            channel_id = source.channel()
            key_id = source.key(channel_id, "Shared key", f"sk-channel-{i}")
            source.balance(key_id, i + 1)
        document = source.export(True)
        dest = self.instance("destination", OTHER_PASSWORD)
        result = dest.restore(document)
        self.assertEqual((result["channels"], result["keys"]), (1, 2))
        self.assertEqual(len(dest.req("GET", "/api/channels")["channels"]), 1)
        before = dest.export()["data"]
        self.assert_no_additions(dest.restore(document))
        self.assertEqual(dest.export()["data"], before)

    def test_export_keeps_channel_and_key_snapshot(self):
        source = self.instance("source")
        channel_id = source.channel()
        source.key(channel_id, "First", "sk-first")
        original_export_keys = backup._export_keys

        def export_keys(conn, data_key, encrypt):
            second_channel = source.channel("Second", "https://second.invalid/v1")
            source.key(second_channel, "Second", "sk-second")
            return original_export_keys(conn, data_key, encrypt)

        with patch.object(backup, "_export_keys", side_effect=export_keys):
            document = source.export()
        self.assertEqual(len(document["data"]["channels"]), 1)
        self.assertEqual(len(document["data"]["keys"]), 1)
        self.assertEqual(len(source.values()), 2)
        dest = self.instance("destination", OTHER_PASSWORD)
        dest.restore(document, "overwrite")
        self.assertEqual(set(dest.values()), {"sk-first"})

    def test_export_keeps_balance_and_history_snapshot(self):
        source = self.instance("source")
        channel_id = source.channel()
        key_id = source.key(channel_id, "Key", "sk-balance")
        source.balance(key_id, 10)
        original_export_keys = backup._export_keys

        def export_keys(conn, data_key, encrypt):
            rows = original_export_keys(conn, data_key, encrypt)
            source.balance(key_id, 20)
            return rows

        with patch.object(backup, "_export_keys", side_effect=export_keys):
            document = source.export()
        self.assertEqual(document["data"]["keys"][0]["balance"], 10)
        self.assertEqual([r["balance"] for r in document["data"]["balance_records"]], [10])
        self.assertEqual(source.values()["sk-balance"]["balance"], 20)

    def test_export_keeps_auth_snapshot_during_password_change(self):
        source = self.instance("source")
        source.key(source.channel(), "Key", "sk-snapshot")
        original_get = db.get_setting
        changed = False

        def get_setting(key, default=None, *, conn=None):
            nonlocal changed
            if key == auth.K_PW_KDF and conn is not None and not changed:
                changed = True
                source.req("POST", "/api/auth/change-password", {
                    "old_password": PASSWORD, "new_password": OTHER_PASSWORD,
                })
            return original_get(key, default, conn=conn)

        with patch.object(db, "get_setting", side_effect=get_setting):
            document = source.export(True)
        self.assertTrue(changed)
        dest = self.instance("destination", OTHER_PASSWORD)
        self.assertTrue(dest.restore(document, "overwrite")["relogin"])
        dest.req("POST", "/api/auth/login", {"password": PASSWORD})
        self.assertEqual(set(dest.values()), {"sk-snapshot"})

    def test_encrypted_overwrite_restores_totp_and_recovery(self):
        source = self.instance("source")
        source.key(source.channel(), "Key", "sk-encrypted")
        _, codes = source.enable_totp()
        document = source.export(True)
        dest = self.instance("destination", OTHER_PASSWORD)
        self.assertTrue(dest.restore(document, "overwrite")["relogin"])
        self.assertFalse(dest.req("GET", "/api/auth/status")["authenticated"])
        dest.req("POST", "/api/auth/login", {"password": PASSWORD, "totp_code": codes[0]})
        self.assertEqual(set(dest.values()), {"sk-encrypted"})
        result = dest.req("POST", "/api/auth/recovery-reset", {
            "recovery_code": source.recovery_code, "new_password": OTHER_PASSWORD,
        })
        self.assertNotEqual(result["recovery_code"], source.recovery_code)
        self.assertFalse(dest.req("GET", "/api/auth/status")["totp_enabled"])
        self.assertEqual(set(dest.values()), {"sk-encrypted"})

    def test_plain_overwrite_keeps_destination_auth(self):
        source = self.instance("source")
        source.key(source.channel(), "Key", "sk-plain")
        document = source.export()
        dest = self.instance("destination", OTHER_PASSWORD)
        dest.enable_totp()
        before = dest.auth_state()
        self.assertFalse(dest.restore(document, "overwrite")["relogin"])
        self.assertEqual(dest.auth_state(), before)
        self.assertEqual(set(dest.values()), {"sk-plain"})

    @contextmanager
    def fail_setting_write(self, key_to_fail):
        original = db.set_setting

        def set_setting(key, value, *, conn=None):
            original(key, value, conn=conn)
            if key == key_to_fail:
                raise sqlite3.OperationalError("simulated setting write failure")

        with patch.object(db, "set_setting", side_effect=set_setting):
            yield

    def test_overwrite_rolls_back_data_and_auth_together(self):
        source = self.instance("source")
        source.key(source.channel(), "Key", "sk-source")
        document = source.export(True)
        dest = self.instance("destination", OTHER_PASSWORD)
        dest.key(dest.channel("Destination"), "Key", "sk-local")
        before_data = dest.export()["data"]
        before_auth = dest.auth_state()
        with self.fail_setting_write(auth.K_WRAP_PW):
            dest.restore(document, "overwrite", expected=500)
        self.assertEqual(dest.export()["data"], before_data)
        self.assertEqual(dest.auth_state(), before_auth)
        self.assertTrue(dest.req("GET", "/api/auth/status")["authenticated"])
        dest.req("POST", "/api/auth/login", {"password": OTHER_PASSWORD})

    def test_password_change_rolls_back_all_credentials(self):
        instance = self.instance("instance")
        before = instance.auth_state()
        with self.fail_setting_write(auth.K_PW_KDF):
            instance.req("POST", "/api/auth/change-password", {
                "old_password": PASSWORD, "new_password": OTHER_PASSWORD,
            }, expected=500)
        self.assertEqual(instance.auth_state(), before)
        instance.req("POST", "/api/auth/login", {"password": PASSWORD})

    def test_recovery_reset_rolls_back_credentials_and_totp(self):
        instance = self.instance("instance")
        instance.key(instance.channel(), "Key", "sk-recovery")
        _, codes = instance.enable_totp()
        before = instance.auth_state()
        original_delete = db.delete_setting

        def delete_setting(key, *, conn=None):
            original_delete(key, conn=conn)
            if key == auth.K_TOTP_ENABLED:
                raise sqlite3.OperationalError("simulated TOTP removal failure")

        with patch.object(db, "delete_setting", side_effect=delete_setting):
            instance.req("POST", "/api/auth/recovery-reset", {
                "recovery_code": instance.recovery_code, "new_password": OTHER_PASSWORD,
            }, expected=500)
        self.assertEqual(instance.auth_state(), before)
        instance.req("POST", "/api/auth/login", {"password": PASSWORD, "totp_code": codes[0]})
        instance.req("POST", "/api/auth/recovery-reset", {
            "recovery_code": instance.recovery_code, "new_password": OTHER_PASSWORD,
        })
        self.assertEqual(set(instance.values()), {"sk-recovery"})

    def test_totp_enable_and_disable_are_atomic(self):
        instance = self.instance("instance")
        secret = instance.req("POST", "/api/auth/totp/setup", {})["secret"]
        with self.fail_setting_write(auth.K_BACKUP_CODES):
            instance.req("POST", "/api/auth/totp/enable", {"code": pyotp.TOTP(secret).now()}, expected=500)
        self.assertFalse(instance.req("GET", "/api/auth/status")["totp_enabled"])
        self.assertEqual(db.get_setting(auth.K_TOTP_PENDING), secret)
        self.assertIsNone(db.get_setting(auth.K_TOTP_SECRET))
        codes = instance.req("POST", "/api/auth/totp/enable", {"code": pyotp.TOTP(secret).now()})["backup_codes"]
        self.assertEqual(len(codes), 10)
        before = instance.auth_state()
        original_delete = db.delete_setting

        def delete_setting(key, *, conn=None):
            original_delete(key, conn=conn)
            if key == auth.K_TOTP_ENABLED:
                raise sqlite3.OperationalError("simulated TOTP removal failure")

        with patch.object(db, "delete_setting", side_effect=delete_setting):
            instance.req("POST", "/api/auth/totp/disable", {"password": PASSWORD}, expected=500)
        self.assertEqual(instance.auth_state(), before)
        instance.req("POST", "/api/auth/totp/disable", {"password": PASSWORD})
        self.assertFalse(instance.req("GET", "/api/auth/status")["totp_enabled"])

    def test_setup_rolls_back_incomplete_credentials(self):
        db.init(self.directory / "setup.db")
        auth.drop_all_sessions()
        with TestClient(APP, raise_server_exceptions=False) as client:
            with self.fail_setting_write(auth.K_RC_HASH):
                checked(client.post("/api/auth/setup", json={"password": PASSWORD}), expected=500)
            self.assertFalse(auth.is_configured())
            self.assertEqual(auth.export_auth_state(), {})
            checked(client.post("/api/auth/setup", json={"password": PASSWORD}))
            self.assertTrue(checked(client.get("/api/auth/status"))["authenticated"])

    def test_cookies_keep_different_port_sessions_independent(self):
        self.assertEqual(auth.SESSION_COOKIE, f"kf_session_{paths.PORT}")
        jar = CookieJar()
        first = self.instance("first", PASSWORD, port=39021, cookies=jar)
        second = self.instance("second", OTHER_PASSWORD, port=39022, cookies=jar)
        self.assertTrue(first.req("GET", "/api/auth/status")["authenticated"])
        self.assertTrue(second.req("GET", "/api/auth/status")["authenticated"])
        first.req("POST", "/api/auth/logout", {})
        self.assertFalse(first.req("GET", "/api/auth/status")["authenticated"])
        self.assertTrue(second.req("GET", "/api/auth/status")["authenticated"])
        self.assertEqual([cookie.name for cookie in jar], ["kf_session_39022"])


def main():
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(BackupRegressions)
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
