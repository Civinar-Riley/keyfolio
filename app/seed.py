"""内置导出模板。只补缺，不覆盖用户改动。

格式依据：
- SillyTavern：settings.json 的 oai_settings（chat_completion_source=custom /
  custom_url / custom_model…），Key 实际存 secrets.json 的 api_key_custom，
  无法随快照导入，模板里给出填写提示。
- ZCode：~/.zcode/v2/config.json 的 provider 块（options.apiKey/baseURL + models）。
- dsh（DeepSeek Harness）：YAML patch + .credentials.yaml，Key 走环境变量引用。
"""
import sqlite3

from . import db

BUILTIN_TEMPLATES = [
    {
        "name": "通用 JSON 配置",
        "client_type": "generic",
        "json_template": '{\n  "name": "{channel_name}",\n  "base_url": "{base_url}",\n  "api_key": "{key}",\n  "models": {models_json}\n}',
    },
    {
        "name": "URL + Key 文本",
        "client_type": "text",
        "json_template": "Base URL: {base_url}\nAPI Key: {key}\n可用模型: {models}",
    },
    {
        "name": "SillyTavern 自定义端点",
        "client_type": "sillytavern",
        "json_template": '{\n  "_说明": "SillyTavern：聊天补全源选 Custom(OpenAI-compatible)，custom_url/custom_model 见下；API Key 无法随设置导入，请在连接界面手动填（ST 存于 secrets.json 的 api_key_custom）",\n  "chat_completion_source": "custom",\n  "custom_url": "{base_url}/v1",\n  "api_key_custom": "{key}",\n  "custom_model": "",\n  "models_available": {models_json}\n}',
    },
    {
        "name": "ZCode 供应商块",
        "client_type": "zcode",
        "json_template": '{\n  "_说明": "把 provider 块按模型 ID 合并进 ~/.zcode/v2/config.json 的 provider 对象；kind 为 anthropic 或 openai，按渠道实际协议选",\n  "provider": {\n    "custom:{key_name}": {\n      "name": "{channel_name}",\n      "kind": "openai",\n      "options": { "apiKey": "{key}", "baseURL": "{base_url}" },\n      "enabled": true,\n      "source": "custom",\n      "models": {models_json}\n    }\n  }\n}',
    },
    {
        "name": "dsh (DeepSeek Harness) 片段",
        "client_type": "dsh",
        "json_template": '# dsh 配置片段（YAML）\n# 1) Key 写入 $DSH_HOME/.credentials.yaml，YAML 里用 apiKeyEnv 引用环境变量\n# 2) base_url / 模型填入对应 profile 的 cordis.patch.yml\ncredentials:\n  api_key_env_value: "{key}"\nprovider:\n  base_url: "{base_url}"\n  models:\n# {models}',
    },
]


def seed_templates() -> None:
    with db.get_conn() as conn:
        for tpl in BUILTIN_TEMPLATES:
            exists = conn.execute(
                "SELECT 1 FROM templates WHERE name=? AND builtin=1", (tpl["name"],)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO templates(name, client_type, json_template, builtin) VALUES(?,?,?,1)",
                (tpl["name"], tpl["client_type"], tpl["json_template"]),
            )
