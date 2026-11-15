"""渠道、模型解析与模板导出的隔离回归测试。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.TemporaryDirectory(prefix="keyfolio-regressions-")
os.environ["KEYFOLIO_DATA_DIR"] = _tmp.name

from fastapi.testclient import TestClient

from app import db
from app.main import app


class ApiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/setup", json={"password": "regression-password-123"})
        response.raise_for_status()

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def setUp(self):
        with db.get_conn() as conn:
            conn.execute("DELETE FROM channels")
        self.channel_id = self.client.post("/api/channels", json={
            "name": "Regression", "type": "gateway", "base_url": "https://example.test/v1",
        }).json()["id"]
        self.key_id = self.client.post(f"/api/channels/{self.channel_id}/keys", json={
            "name": "main", "value": "sk-regression-0123456789abcdef",
        }).json()["id"]

    def test_disabled_channel_stays_disabled_on_creation(self):
        channel_id = self.client.post("/api/channels", json={
            "name": "Disabled", "type": "gateway", "base_url": "https://disabled.test/v1",
            "enabled": False,
        }).json()["id"]
        channels = self.client.get("/api/channels").json()["channels"]
        self.assertFalse(next(c for c in channels if c["id"] == channel_id)["enabled"])

    def test_replacing_key_clears_old_balance_and_verification(self):
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE keys SET balance=42.5, currency='USD', expires_at='2030-01-01', "
                "balance_updated_at=?, last_check='ok', last_check_msg='Valid' WHERE id=?",
                (db.now(), self.key_id),
            )
        for value, expected_balance, expected_check in (
            ("sk-regression-0123456789abcdef", 42.5, "ok"),
            ("sk-replacement-0123456789abcdef", None, ""),
        ):
            with self.subTest(value=value):
                response = self.client.put(f"/api/keys/{self.key_id}", json={"value": value})
                self.assertEqual(response.status_code, 200)
                key = self.client.get("/api/channels").json()["channels"][0]["keys"][0]
                self.assertEqual(key["balance"], expected_balance)
                self.assertEqual(key["last_check"], expected_check)
                self.assertEqual(key["currency"], "USD")
                self.assertEqual(key["expires_at"], "2030-01-01")
                if expected_balance is None:
                    self.assertEqual(key["balance_updated_at"], "")
                    self.assertEqual(key["last_check_msg"], "")
                self.assertEqual(self.client.post(f"/api/keys/{self.key_id}/reveal").json()["value"], value)

    def test_empty_model_json_does_not_become_model_id(self):
        for text in ("[]", '{"data": []}', '{"models": []}', '{"error": "unauthorized"}'):
            with self.subTest(text=text):
                response = self.client.post(f"/api/channels/{self.channel_id}/models/parse", json={"text": text})
                self.assertEqual(response.json()["ids"], [])

    def test_model_json_trims_and_deduplicates_ids(self):
        for text in (
            '[" model-a ", "model-a", "", "  ", {"id": "model-b"}]',
            " model-a \nmodel-a\n\n model-b ",
            '{"models": [{"name": "model-a"}, {"name": "model-b"}]}',
        ):
            with self.subTest(text=text):
                response = self.client.post(f"/api/channels/{self.channel_id}/models/parse", json={"text": text})
                self.assertEqual(response.json()["ids"], ["model-a", "model-b"])

    def test_model_fetch_rejects_key_from_another_channel(self):
        other_id = self.client.post("/api/channels", json={
            "name": "Other", "type": "gateway", "base_url": "https://other.test/v1",
        }).json()["id"]
        with patch("app.routers.models.services.pull_models_async", new_callable=AsyncMock) as fetch:
            fetch.return_value = ["wrong-channel-model"]
            for action in ("fetch", "diff"):
                with self.subTest(action=action):
                    response = self.client.post(f"/api/channels/{other_id}/models/{action}", json={"key_id": self.key_id})
                    self.assertEqual(response.status_code, 400)
            fetch.assert_not_awaited()

    def test_json_template_escapes_values_and_replaces_once(self):
        name = 'My "quoted" channel \\ {key}'
        self.client.put(f"/api/channels/{self.channel_id}", json={"name": name})
        self.client.post(f"/api/channels/{self.channel_id}/models/batch", json={"ids": ['model-{key}', 'model-"quoted"']})
        template = '{"name": "{channel_name}", "key": "{key}", "models": {models_json}, "literal": "{models_json}"}'
        template_id = self.client.post("/api/templates", json={"name": "Regression JSON", "json_template": template}).json()["id"]
        response = self.client.post("/api/templates/render", json={"template_id": template_id, "key_id": self.key_id})
        result = response.json()
        self.assertTrue(result["is_json"], result["rendered"])
        self.assertEqual(result["parsed"]["name"], name)
        self.assertEqual(result["parsed"]["key"], "sk-regression-0123456789abcdef")
        self.assertEqual(result["parsed"]["models"], ['model-"quoted"', 'model-{key}'])
        self.assertEqual(json.loads(result["parsed"]["literal"]), ['model-"quoted"', 'model-{key}'])

    def test_plain_template_keeps_values_literal(self):
        name = 'My "quoted" channel {key}'
        self.client.put(f"/api/channels/{self.channel_id}", json={"name": name})
        for template, expected in (
            ("Name: {channel_name}\nKey: {key}", f"Name: {name}\nKey: sk-regression-0123456789abcdef"),
            ("{key}", "sk-regression-0123456789abcdef"),
        ):
            with self.subTest(template=template):
                template_id = self.client.post("/api/templates", json={"name": "Regression text", "json_template": template}).json()["id"]
                response = self.client.post("/api/templates/render", json={"template_id": template_id, "key_id": self.key_id})
                self.assertEqual(response.json()["rendered"], expected)


if __name__ == "__main__":
    unittest.main()
