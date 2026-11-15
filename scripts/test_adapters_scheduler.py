"""适配器与调度独立回归：临时 SQLite、假 Key、MockTransport，无真实平台请求。

运行：python scripts/test_adapters_scheduler.py
"""
import asyncio
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx

from app import auth, crypto, db, scheduler, services
from app.adapters import base, generic_probe, openrouter, registry


class MockPlatform:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def dispatch(self, request):
        self.requests.append(request)
        return self.handler(request)

    def client(self, timeout=15.0):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.dispatch), timeout=timeout)

    def __enter__(self):
        self.stack = ExitStack()
        for module in (base, generic_probe, openrouter):
            self.stack.enter_context(patch.object(module, "make_client", self.client))
        return self

    def __exit__(self, *args):
        self.stack.close()


def reply(request, payload=None, status=200):
    return httpx.Response(status, json=payload or {}, request=request)


def block_network(*args, **kwargs):
    raise AssertionError("回归测试禁止真实 HTTP 请求")


class AdapterSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keyfolio-adapters-test-")
        self.addCleanup(self.temp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"KEYFOLIO_DATA_DIR": self.temp.name}))
        self.stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", block_network))
        self.stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", block_network))
        self.stack.enter_context(patch.object(scheduler.log, "warning"))
        db.init(Path(self.temp.name) / "test.sqlite")
        auth.State.data_key = b"T" * 32
        self.addCleanup(auth.drop_all_sessions)

    def pair(self, kind="gateway", url="https://mock.invalid"):
        with db.get_conn() as conn:
            channel_id = conn.execute(
                "INSERT INTO channels(name,type,base_url,created_at) VALUES(?,?,?,?)",
                ("test", kind, url, db.now()),
            ).lastrowid
            key_id = conn.execute(
                "INSERT INTO keys(channel_id,name,value_enc,created_at) VALUES(?,?,?,?)",
                (channel_id, "test-key", crypto.field_encrypt(auth.State.data_key, "sk-test-only"), db.now()),
            ).lastrowid
        return services.get_channel(channel_id), services.get_key(key_id)

    def enable_scheduler(self):
        for setting, value in (
            ("sched_enabled", True),
            ("sched_balance_hours", 1),
            ("sched_models_hours", 1),
        ):
            db.set_setting(setting, value)

    def replace_identity(self, channel, key, change):
        with db.get_conn() as conn:
            if change == "key":
                conn.execute("UPDATE keys SET value_enc=? WHERE id=?", (crypto.field_encrypt(auth.State.data_key, "sk-new"), key["id"]))
            elif change == "url":
                conn.execute("UPDATE channels SET base_url=? WHERE id=?", ("https://new.invalid", channel["id"]))
            elif change == "type":
                conn.execute("UPDATE channels SET type='openai' WHERE id=?", (channel["id"],))
            elif change == "move":
                other = conn.execute(
                    "INSERT INTO channels(name,type,base_url,created_at) VALUES('other','gateway','https://mock.invalid',?)",
                    (db.now(),),
                ).lastrowid
                conn.execute("UPDATE keys SET channel_id=? WHERE id=?", (other, key["id"]))
            elif change == "overwrite":
                # 覆盖备份可将原数字 ID 分配给另一实例的渠道和密文。
                conn.execute("DELETE FROM channels WHERE id=?", (channel["id"],))
                conn.execute(
                    "INSERT INTO channels(id,name,type,base_url,created_at) VALUES(?,?,?,?,?)",
                    (channel["id"], "restored", channel["type"], channel["base_url"], db.now()),
                )
                conn.execute(
                    "INSERT INTO keys(id,channel_id,name,value_enc,balance,currency,created_at) VALUES(?,?,?,?,90,'USD',?)",
                    (key["id"], channel["id"], "restored", crypto.field_encrypt(b"N" * 32, "sk-restored"), db.now()),
                )
            else:
                raise AssertionError(change)

    async def during_request(self, module, name, operation, mutate, value=None, error=None):
        started, release = asyncio.Event(), asyncio.Event()

        async def pending(*args):
            started.set()
            await release.wait()
            if error is not None:
                raise error
            return value

        with patch.object(module, name, pending):
            task = asyncio.create_task(operation())
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                mutate()
            finally:
                release.set()
            return await asyncio.wait_for(task, timeout=2)

    async def test_versioned_api_roots(self):
        for kind, root, model_path, chat_path, model in (
            ("zhipu", "https://mock.invalid/api/paas/v4", "/api/paas/v4/models", "/api/paas/v4/chat/completions", "glm-4-plus"),
            ("openai", "https://mock.invalid/v1/chat/completions", "/v1/models", "/v1/chat/completions", "gpt-4o-mini"),
            ("openrouter", "https://mock.invalid/api/v1", "/api/v1/models", "/api/v1/chat/completions", "openai/gpt-4o-mini"),
            ("gemini", "https://mock.invalid/v1", "/v1/models", "/v1/models/gemini-2.5-flash:generateContent", "gemini-2.5-flash"),
            ("gemini", "https://mock.invalid", "/v1beta/models", "/v1beta/models/gemini-2.5-flash:generateContent", "gemini-2.5-flash"),
        ):
            with self.subTest(kind=kind, root=root):
                def handler(request):
                    if request.method == "GET" and request.url.path == model_path:
                        payload = {"models": [{"name": f"models/{model}"}]} if kind == "gemini" else {"data": [{"id": model}]}
                        return reply(request, payload)
                    if request.method == "POST" and request.url.path == chat_path:
                        return reply(request, {"choices": [{"message": {"content": "pong"}}]})
                    return reply(request, status=404)

                with MockPlatform(handler) as mock:
                    self.assertEqual(await registry.fetch_models(kind, root, "sk-test"), [model])
                    self.assertIn(model, await registry.chat_test(kind, root, "sk-test", model))
                self.assertEqual([r.url.path for r in mock.requests], [model_path, chat_path])

    async def test_models_reject_wrong_shape_but_accept_empty_lists(self):
        for kind, field in (("openai", "data"), ("anthropic", "data"), ("gemini", "models")):
            for payload in ({"error": {"message": "upstream unavailable"}}, {field: {}}, {field: None}):
                with self.subTest(kind=kind, payload=payload), MockPlatform(lambda r: reply(r, payload)):
                    with self.assertRaises(base.AdapterError):
                        await registry.fetch_models(kind, "https://mock.invalid", "sk-test")
            with self.subTest(kind=kind, empty=True), MockPlatform(lambda r: reply(r, {field: []})):
                self.assertEqual(await registry.fetch_models(kind, "https://mock.invalid", "sk-test"), [])

    async def test_model_pagination_error_does_not_return_partial_list(self):
        for kind in ("anthropic", "gemini"):
            def handler(request):
                page_key = "after_id" if kind == "anthropic" else "pageToken"
                if page_key in request.url.params:
                    return reply(request, {"error": "page unavailable"})
                payload = (
                    {"data": [{"id": "claude-model"}], "has_more": True, "last_id": "claude-model"}
                    if kind == "anthropic" else
                    {"models": [{"name": "models/gemini-model"}], "nextPageToken": "next"}
                )
                return reply(request, payload)

            with self.subTest(kind=kind), MockPlatform(handler):
                with self.assertRaises(base.AdapterError):
                    await registry.fetch_models(kind, "https://mock.invalid", "sk-test")

    async def test_siliconflow_currency(self):
        for host, expected in (("api.siliconflow.cn", "CNY"), ("api.siliconflow.com", "USD")):
            with self.subTest(host=host), MockPlatform(lambda r: reply(r, {"data": {"balance": "0.88"}})):
                result = await registry.fetch_balance("siliconflow", f"https://{host}/v1", "sk-test")
                self.assertEqual(result["currency"], expected)
                self.assertEqual(result["balance"], 0.88)
        with MockPlatform(lambda r: reply(r, {"data": {"balance": "0.88", "currency": "EUR"}})):
            result = await registry.fetch_balance("siliconflow", "https://api.siliconflow.com/v1", "sk-test")
            self.assertEqual(result["currency"], "EUR")

    async def test_generic_credits_subtracts_usage(self):
        def handler(request):
            return reply(request, {"data": {"total_credits": 100.5, "total_usage": 58}}) if request.url.path == "/api/v1/credits" else reply(request, status=404)

        with MockPlatform(handler):
            result = await registry.fetch_balance("gateway", "https://mock.invalid/api/v1", "sk-test")
        self.assertEqual(result["balance"], 42.5)
        self.assertEqual(result["currency"], "USD")

    async def test_generic_total_credits_without_usage_is_not_balance(self):
        with MockPlatform(lambda r: reply(r, {"data": {"total_credits": 100}})):
            with self.assertRaises(base.AdapterError):
                await registry.fetch_balance("gateway", "https://mock.invalid", "sk-test")

    def test_real_embedding_and_audio_model_names(self):
        for model in ("BAAI/bge-m3", "BAAI/bge-large-en-v1.5", "intfloat/e5-large-v2", "intfloat/multilingual-e5-large"):
            self.assertEqual(registry.classify_model(model), "embedding", model)
        self.assertEqual(registry.classify_model("BAAI/bge-reranker-v2-m3"), "rerank")
        for model in ("gpt-4o-audio-preview", "gpt-audio", "gemini-2.5-flash-native-audio-preview"):
            self.assertEqual(registry.classify_model(model), "chat", model)
        for model in ("udio", "udio-v1", "provider/udio-v2"):
            self.assertEqual(registry.classify_model(model), "music", model)

    async def test_slow_balance_preserves_latest_manual_fields(self):
        channel, key = self.pair()
        result = await self.during_request(
            registry, "fetch_balance",
            lambda: services.check_balance(channel, key),
            lambda: services.set_balance_manual(key, 90, "USD", "2030-12-31"),
            value={"balance": 8, "currency": "", "expires_at": ""},
        )
        self.assertTrue(result["ok"])
        current = services.get_key(key["id"])
        self.assertEqual((current["balance"], current["currency"], current["expires_at"]), (8, "USD", "2030-12-31"))
        with db.get_conn() as conn:
            records = conn.execute("SELECT * FROM balance_records WHERE key_id=? ORDER BY id", (key["id"],)).fetchall()
        self.assertEqual(len(records), 2)
        self.assertEqual((records[-1]["currency"], records[-1]["expires_at"]), ("USD", "2030-12-31"))

    async def test_stale_balance_does_not_write_to_changed_identity(self):
        for change in ("key", "url", "type", "move", "overwrite"):
            with self.subTest(change=change):
                channel, key = self.pair()
                result = await self.during_request(
                    registry, "fetch_balance", lambda: services.check_balance(channel, key),
                    lambda: self.replace_identity(channel, key, change),
                    value={"balance": 123, "currency": "CNY", "expires_at": ""},
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], services.REQUEST_CHANGED)
                self.assertNotEqual(services.get_key(key["id"])["balance"], 123)
                with db.get_conn() as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM balance_records WHERE key_id=?", (key["id"],)).fetchone()[0], 0)

    async def test_stale_verify_success_and_failure_are_discarded(self):
        for mode, function, value, error in (
            ("models", "fetch_models", ["gpt-4o-mini"], None),
            ("models", "fetch_models", None, base.AdapterError("401：Key 无效", status=401)),
            ("chat", "chat_test", "pong", None),
        ):
            with self.subTest(mode=mode, failure=bool(error)):
                channel, key = self.pair()
                result = await self.during_request(
                    registry, function, lambda: services.verify_key(channel, key, mode, "gpt-4o-mini"),
                    lambda: self.replace_identity(channel, key, "overwrite"), value=value, error=error,
                )
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], services.REQUEST_CHANGED)
                self.assertEqual(services.get_key(key["id"])["last_check"], "")

    async def test_current_verify_records_success_and_failure(self):
        channel, key = self.pair()
        with MockPlatform(lambda r: reply(r, {"data": [{"id": "gpt-4o-mini"}]})):
            self.assertTrue((await services.verify_key(channel, key, "models"))["ok"])
        self.assertEqual(services.get_key(key["id"])["last_check"], "ok")
        with MockPlatform(lambda r: reply(r, status=401)):
            self.assertFalse((await services.verify_key(channel, key, "models"))["ok"])
        self.assertEqual(services.get_key(key["id"])["last_check"], "fail")

    async def test_disabling_scheduler_during_balance_stops_next_requests(self):
        self.enable_scheduler()
        first, _ = self.pair()
        self.pair()
        balance_calls, model_calls = [], []
        started, release = asyncio.Event(), asyncio.Event()

        async def balance(channel, key):
            balance_calls.append(channel["id"])
            started.set()
            await release.wait()
            return {"ok": True}

        async def models(channel, key):
            model_calls.append(channel["id"])
            return []

        with patch.object(services, "check_balance", balance), patch.object(services, "pull_models_async", models):
            task = asyncio.create_task(scheduler.tick())
            await asyncio.wait_for(started.wait(), 2)
            db.set_setting("sched_enabled", False)
            release.set()
            await asyncio.wait_for(task, 2)
        self.assertEqual(balance_calls, [first["id"]])
        self.assertEqual(model_calls, [])
        self.assertIsNone(db.get_setting("last_models_run"))

    async def test_disabled_channel_and_key_are_skipped_mid_batch(self):
        self.enable_scheduler()
        first, _ = self.pair()
        second, _ = self.pair()
        _, third_key = self.pair()
        calls = []

        async def balance(channel, key):
            calls.append(channel["id"])
            with db.get_conn() as conn:
                conn.execute("UPDATE channels SET enabled=0 WHERE id=?", (second["id"],))
                conn.execute("UPDATE keys SET enabled=0 WHERE id=?", (third_key["id"],))
            return {"ok": True}

        with patch.object(services, "check_balance", balance):
            await scheduler.run_all_balances()
        self.assertEqual(calls, [first["id"]])

    async def test_model_interval_disabled_during_balance_takes_effect(self):
        self.enable_scheduler()
        self.pair()
        models_called = []

        async def balance(*args):
            db.set_setting("sched_models_hours", 0)
            return {"ok": True}

        async def models(*args):
            models_called.append(True)
            return []

        with patch.object(services, "check_balance", balance), patch.object(services, "pull_models_async", models):
            await scheduler.tick()
        self.assertEqual(models_called, [])
        self.assertIsNone(db.get_setting("last_models_run"))

    async def test_changed_channel_during_model_fetch_does_not_sync(self):
        self.enable_scheduler()
        channel, key = self.pair()
        await self.during_request(
            services, "pull_models_async", scheduler.run_all_model_sync,
            lambda: self.replace_identity(channel, key, "overwrite"),
            value=["old-account-model"],
        )
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM models").fetchone()[0], 0)

    async def test_disabled_during_model_fetch_does_not_sync(self):
        self.enable_scheduler()
        self.pair()
        await self.during_request(
            services, "pull_models_async", scheduler.run_all_model_sync,
            lambda: db.set_setting("sched_enabled", False), value=["new-model"],
        )
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM models").fetchone()[0], 0)

    async def test_scheduler_adds_and_revives_without_overriding_manual_disable(self):
        self.enable_scheduler()
        channel, _ = self.pair()
        with db.get_conn() as conn:
            for model, auto_disabled in (("manual-off", 0), ("auto-off", 1)):
                conn.execute("INSERT INTO models(channel_id,model_id,enabled,auto_disabled) VALUES(?,?,0,?)", (channel["id"], model, auto_disabled))

        async def models(*args):
            return ["manual-off", "auto-off", "new-model"]

        with patch.object(services, "pull_models_async", models):
            await scheduler.run_all_model_sync()
        with db.get_conn() as conn:
            flags = {r["model_id"]: r["enabled"] for r in conn.execute("SELECT * FROM models")}
        self.assertEqual(flags, {"manual-off": 0, "auto-off": 1, "new-model": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
