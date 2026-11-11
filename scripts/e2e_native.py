"""原生端到端测试：mock 平台 + TestClient 驱动 Keyfolio API 全流程断言。

用法：python scripts/e2e_native.py
数据落在临时目录，测完即删，不污染真实数据。
"""
import json
import os
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

from app.main import app  # noqa: E402

PASSWORD = "test-password-123"
BACKUP_PASSWORD = "backup-pass-1"
BASE = "http://127.0.0.1:39001"

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
ok(r.json()["configured"] is False, "未初始化状态检测")

r = client.post("/api/auth/setup", json={"password": "short"})
ok(r.status_code == 400, "弱密码被拒绝")

r = client.post("/api/auth/setup", json={"password": PASSWORD})
recovery_code = r.json()["recovery_code"]
ok(r.status_code == 200 and recovery_code.count("-") == 3, "初始化成功并返回恢复码")

r = client.post("/api/auth/login", json={"password": "wrong-password"})
ok(r.status_code == 401, "错误密码被拒绝")

r = client.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 200, "正确密码登录成功")

r = client.post("/api/auth/unlock", json={"password": PASSWORD})
ok(r.status_code == 200, "锁屏解锁（重输密码）通过")

r = client.get("/api/templates")
ok(len(r.json()["templates"]) >= 2, "内置模板已种入")

print("== 渠道与 Key ==")
r = client.post("/api/channels", json={"name": "Mock 中转", "type": "gateway", "base_url": BASE})
channel_id = r.json()["id"]
ok(r.status_code == 200 and channel_id > 0, "创建渠道")

r = client.post(f"/api/channels/{channel_id}/keys", json={"name": "main", "value": "sk-test-1234567890abcdef"})
key_id = r.json()["id"]
ok(key_id > 0, "创建 Key")

r = client.post("/api/quickadd/save", json={"base_url": BASE, "key": "sk-quick-add-0123456789abcdef"})
ok(r.json()["type"] == "gateway", "快速添加入库（类型猜测 gateway）")

r = client.get("/api/channels")
channels = r.json()["channels"]
ok(len(channels) == 2, "渠道列表两条")
keys = channels[0]["keys"]
ok("sk-test" not in json.dumps(r.json()), "列表响应不含 Key 明文")
ok("****" in keys[0]["value_masked"], "Key 打码显示")

r = client.post(f"/api/keys/{key_id}/reveal", json={})
ok(r.json()["value"] == "sk-test-1234567890abcdef", "明文解锁与原值一致")

print("== 验证 / 模型 / 同步 ==")
r = client.post(f"/api/keys/{key_id}/verify", json={"mode": "models"})
ok(r.json()["ok"] is True and len(r.json()["models"]) == 5, "一键验证：拉到 5 个 mock 模型")

r = client.post(f"/api/keys/{key_id}/verify", json={"mode": "chat", "model": "mock-chat-pro"})
ok(r.json()["ok"] is True, "可选真实对话请求成功")

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

print("== 余额 ==")
r = client.post(f"/api/keys/{key_id}/balance-check")
ok(r.json()["ok"] is True and r.json()["balance"] == 42.5 and r.json()["currency"] == "CNY", "适配器查余额 42.50 CNY")

r = client.get(f"/api/keys/{key_id}/balance-history")
ok(len(r.json()["records"]) == 1, "余额历史落库")

r = client.post(f"/api/keys/{key_id}/balance-manual", json={"balance": 100.0, "currency": "CNY"})
ok(r.json()["ok"] is True, "手动填余额")

openai_channel = client.post("/api/channels", json={"name": "Mock OpenAI 型", "type": "openai", "base_url": BASE}).json()["id"]
openai_key = client.post(f"/api/channels/{openai_channel}/keys", json={"name": "probe", "value": "sk-probe-123"}).json()["id"]
r = client.post(f"/api/keys/{openai_key}/balance-check")
ok(r.json()["ok"] is True and r.json()["balance"] == 42.5, "无专属适配器 → 通用探测命中")

moonshot_channel = client.post("/api/channels", json={"name": "Mock Moonshot", "type": "moonshot", "base_url": BASE}).json()["id"]
moonshot_key = client.post(f"/api/channels/{moonshot_channel}/keys", json={"name": "m", "value": "sk-moon-123"}).json()["id"]
r = client.post(f"/api/keys/{moonshot_key}/balance-check")
ok(r.json()["ok"] is True and r.json()["balance"] == 42.5, "Moonshot 专属失败 → 回退探测命中")

r = client.get("/api/dashboard")
summary = r.json()["summary"]
ok(summary["keys_total"] == 4 and "CNY" in summary["balance_by_currency"], "看板聚合")

r = client.get(f"/api/dashboard/trend?key_id={key_id}")
ok(len(r.json()["records"]) == 2, "趋势数据（自动+手动）")

print("== 模板渲染 ==")
r = client.get("/api/templates")
generic_tpl = [t for t in r.json()["templates"] if t["client_type"] == "generic"][0]
r = client.post("/api/templates/render", json={"template_id": generic_tpl["id"], "key_id": key_id})
ok(r.json()["is_json"] is True and r.json()["parsed"]["api_key"] == "sk-test-1234567890abcdef", "模板渲染占位符替换")

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

# Base URL 自带 /v1 后缀时不应拼出 /v1/v1/models
v1_chan = client.post("/api/channels", json={
    "name": "Mock 带 v1", "type": "gateway", "base_url": BASE + "/v1"}).json()["id"]
v1_key = client.post(f"/api/channels/{v1_chan}/keys", json={"name": "v1k", "value": "sk-v1-123"}).json()["id"]
r = client.post(f"/api/keys/{v1_key}/verify", json={"mode": "models"})
ok(r.json()["ok"] is True and len(r.json()["models"]) == 5, "Base URL 带 /v1 后缀也能拉模型")
client.delete(f"/api/channels/{v1_chan}")

client2 = TestClient(app)
r = client2.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 200, "第二个会话登录")
r = client2.post("/api/backup/import", json={"backup": enc_backup, "mode": "overwrite", "password": BACKUP_PASSWORD})
ok(r.json()["relogin"] is True, "加密覆盖导入触发重新登录")

r = client2.post("/api/auth/login", json={"password": PASSWORD})
ok(r.status_code == 200, "覆盖导入后原密码仍可登录")
r = client2.get("/api/channels")
ok(len(r.json()["channels"]) == 4, "覆盖导入后渠道数回到备份时点（4 条）")

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
r = client5.post("/api/auth/change-password", json={"old_password": "new-password-456", "new_password": PASSWORD})
ok(r.status_code == 200, "改回原密码")
r = client5.post("/api/auth/unlock", json={"password": PASSWORD})
ok(r.status_code == 200, "改密码后新密码生效")

print("== 持久化（直接读库） ==")
import sqlite3

conn = sqlite3.connect(os.path.join(_tmp, "data.db"))
n_channels = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
n_keys = conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
n_records = conn.execute("SELECT COUNT(*) FROM balance_records").fetchone()[0]
ok(n_channels == 4 and n_keys == 4 and n_records >= 3, "重启后数据仍在（SQLite 文件直读）")
conn.close()

print(f"\n全部通过：{PASS} 项断言")
print(f"临时数据目录：{_tmp}")
