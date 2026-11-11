"""原生端到端测试：mock 平台 + TestClient 驱动 Keyfolio API 全流程断言。

用法：python scripts/e2e_native.py
数据落在临时目录，测完即删，不污染真实数据。
"""
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

_tmp = tempfile.mkdtemp(prefix="keyfolio-e2e-")
os.environ["KEYFOLIO_DATA_DIR"] = _tmp
os.environ["KEYFOLIO_PORT"] = "39010"
os.environ["KEYFOLIO_HOST"] = "127.0.0.1"

import pyotp  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import mock_platform  # noqa: E402

from app import auth as auth_mod  # noqa: E402
from app import crypto, db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.backup import FORMAT, VERSION  # noqa: E402

PASSWORD = "test-password-123"
BACKUP_PASSWORD = "backup-pass-1"
BASE = "http://127.0.0.1:39001"
OTHER_KEY = "sk-other-install-0123456789abcdef"

PASS = 0


def ok(cond, label):
    global PASS
    if not cond:
        raise AssertionError(f"断言失败：{label}")
    PASS += 1
    print(f"  ✓ {label}")


mock_platform.serve()
time.sleep(1.2)

client = TestClient(app)

print("== 初始化与登录 ==")
r = client.get("/api/auth/status")
ok(r.json()["configured"] is False and r.json()["authenticated"] is False, "未初始化状态检测")

r = client.post("/api/auth/setup", json={"password": "short"})
ok(r.status_code == 400, "弱密码被拒绝")

r = client.post("/api/auth/setup", json={"password": PASSWORD})
recovery_code = r.json()["recovery_code"]
ok(r.status_code == 200 and recovery_code.count("-") == 3, "初始化成功并返回恢复码")

r = client.get("/api/auth/status")
ok(r.json()["authenticated"] is True, "初始化后会话可直接恢复")

r = client.post("/api/auth/login", json={"password": "wrong-password"})
ok(r.status_code == 401, "错误密码被拒绝")

r = client.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 200, "正确密码登录成功")

anon = TestClient(app)
r = anon.get("/api/auth/status")
ok(r.json()["authenticated"] is False, "无 Cookie 的客户端未登录")

r = client.post("/api/auth/lock")
ok(r.status_code == 200, "锁屏接口")
r = client.get("/api/auth/status")
ok(r.json()["screen_locked"] is True, "状态里显示已锁屏")
r = client.get("/api/channels")
ok(r.status_code == 423, "锁屏期间数据接口被拒绝")
r = client.post("/api/auth/unlock", json={"password": PASSWORD})
ok(r.status_code == 200, "锁屏解锁（重输密码）通过")
r = client.get("/api/channels")
ok(r.status_code == 200, "解锁后数据接口恢复")

r = client.get("/api/templates")
ok(len(r.json()["templates"]) >= 5, "内置模板已种入")
ok("{api_base}" in r.json()["placeholders"] and "{model}" in r.json()["placeholders"],
   "占位符包含 api_base / model")

print("== 渠道与 Key ==")
r = client.post("/api/channels", json={"name": "Mock 中转", "type": "gateway", "base_url": BASE})
channel_id = r.json()["id"]
ok(r.status_code == 200 and channel_id > 0, "创建渠道")

r = client.post(f"/api/channels/{channel_id}/keys",
                json={"name": "main", "value": "sk-test-1234567890abcdef", "expires_at": "2030-01-01"})
key_id = r.json()["id"]
ok(key_id > 0, "创建 Key（带到期日）")

r = client.post("/api/quickadd/save",
                json={"base_url": BASE, "key": "sk-quick-add-0123456789abcdef", "type": "gateway"})
ok(r.json()["created"] is False and r.json()["type"] == "gateway", "快速添加同一 Base URL 合并到现有渠道")

r = client.post("/api/quickadd/save",
                json={"base_url": BASE + "/v1", "key": "sk-quick-anthropic-0123456789", "type": "anthropic"})
ok(r.json()["created"] is True and r.json()["type"] == "anthropic", "快速添加尊重用户选择的渠道类型")

r = client.post("/api/quickadd/parse", json={
    "text": "文档 https://docs.example.com/guide 接口 https://api.example.com/v1\nsk-parse-0123456789abcdef"})
ok(r.json()["base_url"] == "https://api.example.com/v1", "抓取时优先 API 地址而不是文档地址")
r = client.post("/api/quickadd/verify",
                json={"base_url": BASE, "key": "sk-quick-verify-0123456789", "type": "anthropic"})
ok(r.json()["ok"] is True and len(r.json()["models"]) == 3, "抓取页验证按选中类型调用适配器")

r = client.get("/api/channels")
channels = r.json()["channels"]
ok(len(channels) == 2, "渠道列表两条")
ok(len(channels[0]["keys"]) == 2, "同一渠道下追加出第二个 Key")
ok(channels[0]["models_enabled"] == 0 and channels[0]["models_count"] == 0, "渠道模型计数兼容启用数")
ok(any(p["base_url"].startswith("https://api.openai.com") for p in r.json()["providers"]), "渠道预设列表")
ok("sk-test" not in json.dumps(r.json()), "列表响应不含 Key 明文")
ok("****" in channels[0]["keys"][0]["value_masked"], "Key 打码显示")

r = client.post(f"/api/keys/{key_id}/reveal", json={})
ok(r.json()["value"] == "sk-test-1234567890abcdef", "明文解锁与原值一致")

r = client.post("/api/channels", json={"name": "bad", "type": "openai", "base_url": "ftp://example.com"})
ok(r.status_code == 400, "非 http(s) Base URL 被拒绝")

print("== 验证 / 模型 / 同步 ==")
r = client.post(f"/api/keys/{key_id}/verify", json={"mode": "models"})
ok(r.json()["ok"] is True and len(r.json()["models"]) == 5, "一键验证：拉到 5 个 mock 模型")

r = client.post(f"/api/keys/{key_id}/verify", json={"mode": "chat", "model": "mock-chat-pro"})
ok(r.json()["ok"] is True, "可选真实对话请求成功")

r = client.post(f"/api/keys/{key_id}/verify", json={"mode": "chat", "model": "reasoning-1"})
ok(r.json()["ok"] is True, "新推理模型自动回退 max_completion_tokens")

r = client.post(f"/api/channels/{channel_id}/models/diff", json={})
ok(r.json()["ok"] is True and len(r.json()["added"]) == 5 and r.json()["removed"] == [], "diff：新增 5 无消失")

r = client.post(f"/api/channels/{channel_id}/models/sync", json={"added": r.json()["added"]})
ok(r.json()["added"] == 5, "确认同步写入 5 个模型")

r = client.post(
    f"/api/channels/{channel_id}/models/sync",
    json={"added": ["mock-new-model"], "removed": ["mock-image-xl"], "removed_action": "disable"},
)
ok(r.json()["ok"] is True, "二次同步：加 1 禁 1")

r = client.get(f"/api/channels/{channel_id}/models")
models = r.json()["models"]
disabled = [m for m in models if not m["enabled"]]
ok(len(models) == 6 and len(disabled) == 1, "模型表 6 条、1 条停用（未删除）")
embed = [m for m in models if m["model_id"] == "mock-embed-3"][0]
ok(embed["mtype"] == "embedding", "启发式归类：mock-embed-3 → embedding")

r = client.post(f"/api/channels/{channel_id}/models/parse", json={"text": '{"data":[{"id":"parse-a"},{"id":"parse-b"}]}'})
ok(r.json()["ids"] == ["parse-a", "parse-b"], "粘贴 JSON 解析")

chat_pro = [m for m in models if m["model_id"] == "mock-chat-pro"][0]
client.put(f"/api/models/{chat_pro['id']}", json={"enabled": False})
r = client.post(f"/api/channels/{channel_id}/models/diff", json={})
ok(r.json()["added"] == [] and "mock-chat-pro" not in r.json()["added"], "手动停用的模型不会被同步重新启用")
ok("mock-image-xl" in r.json()["revived"], "远端重新出现的模型进入 revived")
ok(r.json()["removed"] == ["mock-new-model"], "diff 只统计启用中的消失模型")

r = client.post(f"/api/channels/{channel_id}/models/sync",
                json={"added": [], "removed": [], "revived": r.json()["revived"]})
ok(r.json()["revived"] == 1, "确认恢复自动停用的模型")
r = client.get(f"/api/channels/{channel_id}/models")
by_id = {m["model_id"]: m for m in r.json()["models"]}
ok(by_id["mock-image-xl"]["enabled"] and not by_id["mock-chat-pro"]["enabled"],
   "同步后手动停用保持、自动停用恢复")

claude_chan = client.post("/api/channels",
                          json={"name": "Mock Claude", "type": "anthropic", "base_url": BASE}).json()["id"]
claude_key = client.post(f"/api/channels/{claude_chan}/keys",
                         json={"name": "c", "value": "sk-ant-123"}).json()["id"]
r = client.post(f"/api/keys/{claude_key}/verify", json={"mode": "models"})
ok(r.json()["ok"] is True and len(r.json()["models"]) == 3 and "claude-mock-c" in r.json()["models"],
   "Anthropic 模型列表分页拉全")
client.delete(f"/api/channels/{claude_chan}")

gemini_chan = client.post("/api/channels",
                          json={"name": "Mock Gemini", "type": "gemini", "base_url": BASE}).json()["id"]
gemini_key = client.post(f"/api/channels/{gemini_chan}/keys",
                         json={"name": "g", "value": "gemini-key-123"}).json()["id"]
r = client.post(f"/api/keys/{gemini_key}/verify", json={"mode": "models"})
ok(r.json()["ok"] is True and len(r.json()["models"]) == 3 and "gemini-mock-c" in r.json()["models"],
   "Gemini 模型列表分页拉全")
client.delete(f"/api/channels/{gemini_chan}")

endpoint_chan = client.post("/api/channels", json={
    "name": "Mock 完整端点", "type": "gateway", "base_url": BASE + "/v1/chat/completions"}).json()["id"]
endpoint_key = client.post(f"/api/channels/{endpoint_chan}/keys",
                           json={"name": "e", "value": "sk-endpoint-123"}).json()["id"]
r = client.post(f"/api/keys/{endpoint_key}/verify", json={"mode": "models"})
ok(r.json()["ok"] is True and len(r.json()["models"]) == 5, "粘贴完整端点也能拉模型")
stored = [c for c in client.get("/api/channels").json()["channels"] if c["id"] == endpoint_chan][0]
ok(stored["base_url"] == BASE + "/v1", "Base URL 保存时剥掉端点后缀")
client.delete(f"/api/channels/{endpoint_chan}")

print("== 余额 ==")
r = client.post(f"/api/keys/{key_id}/balance-check")
ok(r.json()["ok"] is True and r.json()["balance"] == 42.5 and r.json()["currency"] == "CNY", "适配器查余额 42.50 CNY")
ok(r.json()["expires_at"] == "2030-01-01", "自动查余额不覆盖手填到期日")

r = client.get(f"/api/keys/{key_id}/balance-history")
ok(len(r.json()["records"]) == 1, "余额历史落库")

r = client.post(f"/api/keys/{key_id}/balance-manual",
                json={"balance": 100.0, "currency": "CNY", "expires_at": "2031-02-03"})
ok(r.json()["ok"] is True, "手动填余额")
r = client.post(f"/api/keys/{key_id}/balance-check")
ok(r.json()["expires_at"] == "2031-02-03", "再次自动查询仍保留手动到期日")

openai_channel = client.post("/api/channels", json={"name": "Mock OpenAI 型", "type": "openai", "base_url": BASE}).json()["id"]
openai_key = client.post(f"/api/channels/{openai_channel}/keys",
                         json={"name": "probe", "value": "sk-probe-123", "expires_at": "2031-01-01"}).json()["id"]
r = client.post(f"/api/keys/{openai_key}/balance-check")
ok(r.json()["ok"] is True and r.json()["balance"] == 42.5, "无专属适配器 → 通用探测命中")
ok(r.json()["expires_at"] == "2031-01-01", "探测结果为空时保留手动到期日")

openrouter_channel = client.post("/api/channels", json={
    "name": "Mock OpenRouter", "type": "openrouter", "base_url": BASE + "/api/v1"}).json()["id"]
openrouter_key = client.post(f"/api/channels/{openrouter_channel}/keys",
                             json={"name": "or", "value": "sk-or-123"}).json()["id"]
r = client.post(f"/api/keys/{openrouter_key}/balance-check")
ok(r.json()["ok"] is True and r.json()["balance"] == 42.5 and r.json()["currency"] == "USD",
   "OpenRouter 余额路径拼接正确")
client.delete(f"/api/channels/{openrouter_channel}")

moonshot_channel = client.post("/api/channels", json={"name": "Mock Moonshot", "type": "moonshot", "base_url": BASE}).json()["id"]
moonshot_key = client.post(f"/api/channels/{moonshot_channel}/keys",
                           json={"name": "m", "value": "sk-moon-123"}).json()["id"]
r = client.post(f"/api/keys/{moonshot_key}/balance-check")
ok(r.json()["ok"] is True and r.json()["balance"] == 42.5, "Moonshot 专属失败 → 回退探测命中")

r = client.get("/api/dashboard")
summary = r.json()["summary"]
ok(summary["keys_total"] == 5 and "CNY" in summary["balance_by_currency"], "看板聚合")

r = client.get(f"/api/dashboard/trend?key_id={key_id}")
ok(len(r.json()["records"]) == 3, "趋势数据（自动+手动+自动）")

print("== 模板渲染 ==")
r = client.get("/api/templates")
generic_tpl = [t for t in r.json()["templates"] if t["client_type"] == "generic"][0]
r = client.post("/api/templates/render", json={"template_id": generic_tpl["id"], "key_id": key_id})
ok(r.json()["is_json"] is True and r.json()["parsed"]["api_key"] == "sk-test-1234567890abcdef", "模板渲染占位符替换")

st_tpl = [t for t in client.get("/api/templates").json()["templates"] if t["client_type"] == "sillytavern"][0]
r = client.post("/api/templates/render", json={"template_id": st_tpl["id"], "key_id": key_id})
st_data = r.json()["parsed"]
ok(st_data["custom_url"] == BASE + "/v1", "SillyTavern 模板补齐 /v1 且不重复")

env_tpl = [t for t in client.get("/api/templates").json()["templates"] if t["client_type"] == "dotenv"][0]
r = client.post("/api/templates/render", json={"template_id": env_tpl["id"], "key_id": key_id})
ok(f"OPENAI_BASE_URL={BASE}/v1" in r.json()["rendered"], ".env 模板使用 api_base")

v1_chan = client.post("/api/channels", json={
    "name": "Mock 带 v1", "type": "gateway", "base_url": BASE + "/v1"}).json()["id"]
v1_key = client.post(f"/api/channels/{v1_chan}/keys", json={"name": "v1k", "value": "sk-v1-123"}).json()["id"]
r = client.post("/api/templates/render", json={"template_id": st_tpl["id"], "key_id": v1_key})
ok(r.json()["parsed"]["custom_url"] == BASE + "/v1", "Base URL 已带 /v1 时不重复拼接")
client.delete(f"/api/channels/{v1_chan}")

print("== 备份 ==")
r = client.post("/api/backup/export", json={"password": ""})
plain_backup = json.loads(r.content)
ok(plain_backup["encrypted"] is False and plain_backup["data"]["keys"][0]["value"].startswith("sk-"), "明文导出")

r = client.post("/api/backup/export", json={"password": BACKUP_PASSWORD})
enc_backup = json.loads(r.content)
ok(enc_backup["encrypted"] is True, "加密导出")

r = client.post("/api/backup/import", json={"backup": plain_backup, "mode": "merge"})
ok(r.json()["ok"] is True and r.json()["channels"] == 0, "明文合并：渠道去重 0 新增")

# 删除一条渠道后再合并，验证旧 id 不会撞主键、且新 Key 能插入
quickadd_chan = channels[1]["id"]
client.delete(f"/api/channels/{quickadd_chan}")
r = client.post("/api/backup/import", json={"backup": plain_backup, "mode": "merge"})
ok(r.json()["ok"] is True and r.json()["channels"] == 1 and r.json()["keys"] == 1,
   "合并导入：被删渠道及其 Key 重新插入（旧 id 不冲突）")

client2 = TestClient(app)
r = client2.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 200, "第二个会话登录")
r = client2.post("/api/backup/import", json={"backup": enc_backup, "mode": "overwrite", "password": BACKUP_PASSWORD})
ok(r.json()["relogin"] is True, "加密覆盖导入触发重新登录")

r = client2.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 200, "覆盖导入后原密码仍可登录")
r = client2.get("/api/channels")
ok(r.status_code == 200 and len(r.json().get("channels", [])) == 4
   and sum(len(c["keys"]) for c in r.json().get("channels", [])) == 5,
   "覆盖导入后渠道与 Key 数回到备份时点")

print("== TOTP ==")
r = client2.post("/api/auth/totp/setup")
secret = r.json()["secret"]
ok(r.json()["otpauth_uri"].startswith("otpauth://totp/"), "TOTP 二维码 otpauth URI")
code = pyotp.TOTP(secret).now()
r = client2.post("/api/auth/totp/enable", json={"code": code})
backup_codes = r.json()["backup_codes"]
ok(len(backup_codes) == 10, "TOTP 开启并返回 10 个备用码")

client3 = TestClient(app)
r = client3.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 401, "TOTP 已开：缺验证码登录被拒")
r = client3.post("/api/auth/login", json={"password": PASSWORD, "totp_code": pyotp.TOTP(secret).now()})
ok(r.status_code == 200, "TOTP 正确验证码登录")
r = client3.post("/api/auth/login", json={"password": PASSWORD, "totp_code": backup_codes[0]})
ok(r.status_code == 200, "备用码登录")

client4 = TestClient(app)
r = client4.post("/api/auth/login", json={"password": PASSWORD, "totp_code": backup_codes[0]})
ok(r.status_code == 401, "备用码单次有效：用过的已失效")
r = client4.post("/api/auth/login", json={"password": PASSWORD, "totp_code": backup_codes[1]})
ok(r.status_code == 200, "未使用过的备用码可登录")
client4.post("/api/auth/totp/disable", json={"password": PASSWORD})

print("== 连错锁定与恢复码（TOTP 开启状态下走逃生舱） ==")
r = client2.post("/api/auth/totp/setup")
secret2 = r.json()["secret"]
r = client2.post("/api/auth/totp/enable", json={"code": pyotp.TOTP(secret2).now()})
ok(r.status_code == 200, "为逃生舱场景重新开启 TOTP")

client5 = TestClient(app)
for _ in range(5):
    r = client5.post("/api/auth/login", json={"password": "bad guess"})
ok(r.status_code == 423, "连错 5 次触发锁定")
r = client5.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 423, "锁定期间正确密码也被拒")

r = client5.post("/api/auth/recovery-reset", json={"recovery_code": recovery_code, "new_password": "new-password-456"})
new_code = r.json()["recovery_code"]
ok(r.status_code == 200 and new_code != recovery_code, "恢复码重置密码并生成新恢复码")

r = client5.get("/api/channels")
ok(r.status_code == 200, "重置后自动登录（会话可直接用）")
r = client5.get("/api/auth/status")
ok(r.json()["totp_enabled"] is False, "重置同时清掉 TOTP（验证器丢了也能进）")

r = client5.post("/api/auth/login", json={"password": "new-password-456"})
ok(r.status_code == 200, "新密码登录成功（无需 TOTP、旧恢复码已失效）")

print("== 改密码 ==")
client_a = TestClient(app)
client_b = TestClient(app)
client_a.post("/api/auth/login", json={"password": "new-password-456"})
client_b.post("/api/auth/login", json={"password": "new-password-456"})
r = client_a.post("/api/auth/change-password",
                  json={"old_password": "new-password-456", "new_password": "temp-password-789"})
ok(r.status_code == 200, "改密码成功")
r = client_b.get("/api/channels")
ok(r.status_code == 401, "改密码后其他会话失效")
r = client_a.get("/api/channels")
ok(r.status_code == 200, "当前会话保持有效")
r = client_a.post("/api/auth/change-password",
                  json={"old_password": "temp-password-789", "new_password": PASSWORD})
ok(r.status_code == 200, "改回原密码")
r = client_a.post("/api/auth/unlock", json={"password": PASSWORD})
ok(r.status_code == 200, "改密码后新密码生效")

print("== 响应头 ==")
r = client_a.get("/api/health")
ok(r.headers.get("x-content-type-options") == "nosniff", "安全响应头 nosniff")
ok(r.headers.get("cache-control") == "no-store", "API 响应禁止缓存")

print("== 跨实例加密备份恢复 ==")
data_key2 = secrets.token_bytes(32)
other_password = "other-install-pass"
other_recovery = "abcd-ef01-2345-6789"
kdf2 = crypto.make_kdf_params()
auth_block = {
    auth_mod.K_PW_HASH: crypto.hash_password(other_password, kdf2),
    auth_mod.K_PW_KDF: kdf2,
    auth_mod.K_WRAP_PW: crypto.wrap_data_key(data_key2, other_password, crypto.AAD_WRAP_PW),
    auth_mod.K_WRAP_RC: crypto.wrap_data_key(
        data_key2, crypto.normalize_recovery(other_recovery), crypto.AAD_WRAP_RC),
    auth_mod.K_RC_HASH: crypto.hash_code(crypto.normalize_recovery(other_recovery)),
}
now = db.now()
other_data = {
    "channels": [{
        "id": 1, "name": "Other Install", "type": "openai", "base_url": "https://other.example/v1",
        "console_url": "", "grp": "", "notes": "", "enabled": 1, "created_at": now,
    }],
    "keys": [{
        "id": 1, "channel_id": 1, "name": "other", "value_enc":
            crypto.field_encrypt(data_key2, OTHER_KEY), "notes": "", "enabled": 1,
        "balance": None, "currency": "", "expires_at": "", "balance_updated_at": "",
        "last_check": "", "last_check_msg": "", "created_at": now, "value_encrypted": True,
    }],
    "models": [],
    "balance_records": [],
    "templates": [],
    "auth": auth_block,
    "backup_wrap": crypto.wrap_data_key(data_key2, BACKUP_PASSWORD, crypto.AAD_BACKUP),
}
kdf = crypto.make_kdf_params()
kek = crypto.derive_kek(BACKUP_PASSWORD, kdf, crypto.AAD_BACKUP)
wrapped = crypto.encrypt_payload(kek, json.dumps(other_data).encode(), crypto.AAD_BACKUP)
other_backup = {
    "format": FORMAT, "version": VERSION, "created_at": now,
    "encrypted": True, "kdf": kdf, **wrapped,
}
r = client_a.post("/api/backup/import",
                  json={"backup": other_backup, "mode": "overwrite", "password": BACKUP_PASSWORD})
ok(r.status_code == 200 and r.json()["relogin"] is True, "跨实例加密备份覆盖导入")

r = client_a.get("/api/channels")
ok(r.status_code == 401, "覆盖后旧会话失效")

client6 = TestClient(app)
r = client6.post("/api/auth/login", json={"password": other_password})
ok(r.status_code == 200, "备份自带的密码可登录")
r = client6.get("/api/channels")
other_channels = r.json()["channels"]
ok(len(other_channels) == 1 and other_channels[0]["keys"][0]["value_masked"] != "****",
   "恢复后 Key 密文与 data key 匹配")
r = client6.post(f"/api/keys/{other_channels[0]['keys'][0]['id']}/reveal", json={})
ok(r.status_code == 200 and r.json()["value"] == OTHER_KEY, "跨实例恢复后 Key 可正常解密")

print("== 持久化（直接读库） ==")
import sqlite3

conn = sqlite3.connect(os.path.join(_tmp, "data.db"))
n_channels = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
n_keys = conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
n_records = conn.execute("SELECT COUNT(*) FROM balance_records").fetchone()[0]
schema_version = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0]
ok(n_channels == 1 and n_keys == 1 and n_records == 0, "最终数据与备份一致（SQLite 文件直读）")
ok(json.loads(schema_version) == 2, "schema 迁移到 v2")
conn.close()

print(f"\n全部通过：{PASS} 项断言")
print(f"临时数据目录：{_tmp}")
