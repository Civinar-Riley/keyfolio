"""内置导出模板。只补缺，不覆盖用户改动；旧版内置内容做定向升级。

模板里的 {api_base} 保证版本段只出现一次（Base URL 可带可不带 /v1），
{model} 取该渠道第一个启用的模型，{models}/{models_json} 为全部启用模型。
"""
from . import db

_OLD_SILLYTAVERN = '{\n  "_说明": "SillyTavern：聊天补全源选 Custom(OpenAI-compatible)，custom_url/custom_model 见下；API Key 无法随设置导入，请在连接界面手动填（ST 存于 secrets.json 的 api_key_custom）",\n  "chat_completion_source": "custom",\n  "custom_url": "{base_url}/v1",\n  "api_key_custom": "{key}",\n  "custom_model": "",\n  "models_available": {models_json}\n}'
_OLD_URL_KEY_TEXT = "Base URL: {base_url}\nAPI Key: {key}\n可用模型: {models}"
_OLD_DSH = '# dsh 配置片段（YAML）\n# 1) Key 写入 $DSH_HOME/.credentials.yaml，YAML 里用 apiKeyEnv 引用环境变量\n# 2) base_url / 模型填入对应 profile 的 cordis.patch.yml\ncredentials:\n  api_key_env_value: "{key}"\nprovider:\n  base_url: "{base_url}"\n  models:\n# {models}'

BUILTIN_TEMPLATES = [
    {
        "name": "通用 JSON 配置",
        "client_type": "generic",
        "json_template": '{\n  "name": "{channel_name}",\n  "base_url": "{base_url}",\n  "api_key": "{key}",\n  "models": {models_json}\n}',
    },
    {
        "name": "URL + Key 文本",
        "client_type": "text",
        "json_template": "Base URL: {base_url}\nAPI Base: {api_base}\nAPI Key: {key}\n可用模型: {models}",
    },
    {
        "name": "环境变量 .env",
        "client_type": "dotenv",
        "json_template": "OPENAI_BASE_URL={api_base}\nOPENAI_API_KEY={key}\nOPENAI_MODEL={model}",
    },
    {
        "name": "cURL 示例（OpenAI 兼容）",
        "client_type": "curl",
        "json_template": "curl {api_base}/chat/completions \\\n  -H \"Authorization: Bearer {key}\" \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\"model\": \"{model}\", \"messages\": [{\"role\": \"user\", \"content\": \"ping\"}]}'",
    },
    {
        "name": "OpenAI SDK（Python）",
        "client_type": "python",
        "json_template": "from openai import OpenAI\n\nclient = OpenAI(\n    base_url=\"{api_base}\",\n    api_key=\"{key}\",\n)\n\nresp = client.chat.completions.create(\n    model=\"{model}\",\n    messages=[{\"role\": \"user\", \"content\": \"hello\"}],\n)\nprint(resp.choices[0].message.content)",
    },
    {
        "name": "SillyTavern 自定义端点",
        "client_type": "sillytavern",
        "json_template": '{\n  "_说明": "SillyTavern：聊天补全源选 Custom(OpenAI-compatible)，custom_url/custom_model 见下；API Key 无法随设置导入，请在连接界面手动填（ST 存于 secrets.json 的 api_key_custom）",\n  "chat_completion_source": "custom",\n  "custom_url": "{api_base}",\n  "api_key_custom": "{key}",\n  "custom_model": "",\n  "models_available": {models_json}\n}',
    },
    {
        "name": "ZCode 供应商块",
        "client_type": "zcode",
        "json_template": '{\n  "_说明": "把 provider 块按模型 ID 合并进 ~/.zcode/v2/config.json 的 provider 对象；kind 为 anthropic 或 openai，按渠道实际协议选",\n  "provider": {\n    "custom:{key_name}": {\n      "name": "{channel_name}",\n      "kind": "openai",\n      "options": { "apiKey": "{key}", "baseURL": "{base_url}" },\n      "enabled": true,\n      "source": "custom",\n      "models": {models_json}\n    }\n  }\n}',
    },
    {
        "name": "dsh (DeepSeek Harness) 片段",
        "client_type": "dsh",
        "json_template": '# dsh 配置片段（YAML）\n# 1) Key 写入 $DSH_HOME/.credentials.yaml，YAML 里用 apiKeyEnv 引用环境变量\n# 2) base_url / 模型填入对应 profile 的 cordis.patch.yml\ncredentials:\n  api_key_env_value: "{key}"\nprovider:\n  base_url: "{api_base}"\n  models:\n# {models}',
    },
]

# 旧版本内置内容：仅当用户没有改过时才升级
LEGACY_BUILTINS = {
    "SillyTavern 自定义端点": (_OLD_SILLYTAVERN,),
    "URL + Key 文本": (_OLD_URL_KEY_TEXT,),
    "dsh (DeepSeek Harness) 片段": (_OLD_DSH,),
}


def seed_templates() -> None:
    with db.get_conn() as conn:
        for tpl in BUILTIN_TEMPLATES:
            row = conn.execute(
                "SELECT id, json_template FROM templates WHERE name=? AND builtin=1",
                (tpl["name"],),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO templates(name, client_type, json_template, builtin) VALUES(?,?,?,1)",
                    (tpl["name"], tpl["client_type"], tpl["json_template"]),
                )
                continue
            if row["json_template"] in LEGACY_BUILTINS.get(tpl["name"], ()):
                conn.execute(
                    "UPDATE templates SET client_type=?, json_template=? WHERE id=?",
                    (tpl["client_type"], tpl["json_template"], row["id"]),
                )
