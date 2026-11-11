# Keyfolio · 通用本地 API 资产管理器

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/Civinar-Riley/keyfolio)](https://github.com/Civinar-Riley/keyfolio/releases)

[English](README.en.md) | 中文

把散落在各平台的 API Key 集中到一个本地工具里：统一存储、一键验证、拉取模型、查询余额、看板汇总趋势、占位符模板一键导出给任意客户端。数据只存在本机，Key 字段级 AES-GCM 加密。

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="49%" alt="看板">
  <img src="docs/screenshots/channels.png" width="49%" alt="渠道详情">
</p>

## 功能特性

- **凭证库**：渠道（名称/类型/Base URL/控制台地址/分组/备注）挂多个 Key，统一增删改查，Key 打码显示；新建时可按 OpenAI / Claude / Gemini / DeepSeek / SiliconFlow / OpenRouter / Moonshot / 智谱等预设一键带出地址；Key 支持到期日并在列表/看板提示
- **一键验证**：`GET /v1/models` 测 Key 可用性（无消耗），可选发一条 `max_tokens=1` 真实请求验证推理；新推理模型自动改用 `max_completion_tokens`
- **模型发现与同步**：拉取模型 ID，勾选保存、手动添加、粘贴 JSON 批量解析；重新拉取时对比新增/消失/重新出现，确认后同步（消失的标停用不删，手动停用的不会被同步重新启用，自动停用的在远端恢复后可按确认恢复）
- **余额查询**：适配器按渠道类型自动查（DeepSeek / SiliconFlow / OpenRouter 等），失败走通用只读探测，再不行显示具体原因（401/404/超时）并支持手动填；自动查询不会覆盖手动填写的到期日与币种；每次查询记入历史
- **统一看板**：全部 Key 的余额、状态、到期情况一页汇总，按分组/类型筛选、按余额/更新时间排序，余额变化趋势图（Chart.js，7/30/90/365 天）
- **一键导出**：占位符模板（`{name}` `{base_url}` `{api_base}` `{key}` `{model}` `{models}` 等），内置 SillyTavern / ZCode / dsh / .env / cURL / OpenAI SDK / 通用格式，模板可增删改；`{api_base}` 会自动补齐版本段，Base URL 带不带 `/v1` 都不会拼重
- **快速抓取**：粘贴任意文本自动抠出 Base URL 和 Key，支持选择渠道类型，一键测、一键入库；同一 Base URL 再次入库会追加 Key 而不是新建渠道
- **安全**：主密码 + 可选 TOTP 2FA + 备用码；恢复码可重设密码；连错 5 次锁 5 分钟；服务端锁屏（锁屏期间数据接口拒绝访问，刷新页面仍保持锁定）；刷新页面自动恢复会话；改密码踢出其他设备会话；Key 值/TOTP 密钥字段级 AES-GCM 加密
- **备份**：全量导出 .json（含 Key 时可整包加密），导入支持覆盖/合并去重；加密备份可跨实例恢复登录凭证与 Key 密文

## 架构

- 后端：Python + FastAPI + SQLite（WAL），httpx 出站请求，asyncio 后台定时
- 前端：无构建 Vue 3（vendored ESM）+ Chart.js，响应式布局，PWA（manifest + Service Worker）
- 打包：Windows PyInstaller onefile / Docker / 原生 Python，三种跑法同一份代码

## 快速开始

### Docker（推荐 NAS / 服务器）

```bash
docker compose up -d
# 浏览器打开 http://<主机IP>:7465
```

数据卷挂载 `./data:/app/data`，迁移 = 复制 `data/` 目录。环境变量：`KEYFOLIO_PORT`（默认 7465）、`TZ`。

### 原生运行

```bash
pip install -r requirements.txt
python main.py
# 默认 http://127.0.0.1:7465，可用环境变量 KEYFOLIO_HOST / KEYFOLIO_PORT / KEYFOLIO_DATA_DIR 覆盖
```

Linux 可用 systemd 开机自启（`ExecStart=/usr/bin/python3 /path/to/main.py`）。

### Windows exe

下载 [keyfolio.exe](https://github.com/Civinar-Riley/keyfolio/releases/latest/download/keyfolio.exe) 双击运行，本地起服务后自动打开浏览器。`data.db`、`app.log` 落在 exe 同目录的 `data/` 下，随目录迁移。

## 移动端

手机浏览器打开服务地址即是完整界面（<768px 自动切底部导航、单列布局）。在安全上下文（localhost 或反代 HTTPS）下可安装为 PWA 到主屏幕；局域网 HTTP 下功能不受影响，仅无法安装。

## 数据与安全

- Key 值、TOTP 密钥等敏感字段用随机 data key 做 AES-GCM 加密；data key 由主密码（scrypt）和恢复码分别包裹存储
- 首次启动设置主密码后生成恢复码，**只显示一次**，凭恢复码可重设密码（生成新恢复码）
- 锁屏是服务端状态：锁屏期间所有数据接口返回 423，刷新或换标签页仍保持锁定；但密钥仍驻留在服务进程内存中，服务重启后需重新登录
- 会话保存在内存，默认闲置 7 天失效；服务重启后需重新登录
- 备份导出含 Key 明文时会明确提示，可选整包加密；加密备份覆盖导入可恢复登录凭证与 Key 密文
- 主密码丢失且无恢复码 = 数据无法解密，请定期导出加密备份

## 开发

```
main.py              入口
app/                 后端（db / crypto / auth / routers / adapters / scheduler / static）
scripts/             打包与测试脚本（build_exe.bat / mock_platform.py / e2e_native.py / gen_icons.py）
```

端到端测试：`python scripts/e2e_native.py`（脚本会自行在 39001 端口启动假平台，跑完即退出，不需要手工起服务）。

## Limitations

- 余额通用探测是尽力而为，成功率取决于目标站响应格式；不开放余额接口的平台仍需手动填
- session 保存在内存，闲置 7 天失效，服务重启后需重新登录（数据无损）
- 锁屏会拦住 API 访问，但 data key 仍驻留在服务进程内存中（重启即清空）
- Windows exe 每次启动解压，慢 2~3 秒

## License

[MIT](LICENSE)
