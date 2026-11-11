# Keyfolio · 通用本地 API 资产管理器

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)

English | [中文](README.md)

把散落在各平台的 API Key 集中到一个本地工具里：统一存储、一键验证、拉取模型、查询余额、看板汇总趋势、占位符模板一键导出给任意客户端。数据只存在本机，Key 字段级 AES-GCM 加密。

<!-- TODO: 截图（上线后补） -->

## 功能特性

- **凭证库**：渠道（名称/类型/Base URL/控制台地址/分组/备注）挂多个 Key，统一增删改查，Key 打码显示
- **一键验证**：`GET /v1/models` 测 Key 可用性（无消耗），可选发一条 `max_tokens=1` 真实请求验证推理
- **模型发现与同步**：拉取 `/v1/models` 解析模型 ID，勾选保存、手动添加、粘贴 JSON 批量解析；重新拉取时对比新增/消失，确认后同步（消失的标停用不删，本地手改保留）
- **余额查询**：适配器按渠道类型自动查（DeepSeek / SiliconFlow / OpenRouter 等），失败走通用只读探测，再不行显示具体原因（401/404/超时）并支持手动填；每次查询记入历史
- **统一看板**：全部 Key 的余额、状态一页汇总，按分组/类型筛选、按余额/更新时间排序，余额变化趋势图（Chart.js）
- **一键导出**：占位符 JSON 模板（`{name}` `{base_url}` `{key}` `{models}` 等），内置 SillyTavern / ZCode / 通用格式，模板可增删改
- **快速抓取**：粘贴任意文本自动抠出 Base URL 和 Key，一键测、一键入库
- **安全**：主密码 + 可选 TOTP 2FA + 备用码；恢复码可重设密码；连错 5 次锁 5 分钟；锁屏；改密码；Key 值/TOTP 密钥字段级 AES-GCM 加密
- **备份**：全量导出 .json（含 Key 时可整包加密），导入支持覆盖/合并去重

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

下载 `keyfolio.exe` 双击运行，本地起服务后自动打开浏览器。`data.db`、`app.log` 落在 exe 同目录的 `data/` 下，随目录迁移。

## 移动端

手机浏览器打开服务地址即是完整界面（<768px 自动切底部导航、单列布局）。在安全上下文（localhost 或反代 HTTPS）下可安装为 PWA 到主屏幕；局域网 HTTP 下功能不受影响，仅无法安装。

## 数据与安全

- Key 值、TOTP 密钥等敏感字段用随机 data key 做 AES-GCM 加密；data key 由主密码（scrypt）和恢复码分别包裹存储
- 首次启动设置主密码后生成恢复码，**只显示一次**，凭恢复码可重设密码（生成新恢复码）
- 备份导出含 Key 明文时会明确提示，可选整包加密
- 主密码丢失且无恢复码 = 数据无法解密，请定期导出加密备份

## 开发

```
main.py              入口
app/                 后端（db / crypto / auth / routers / adapters / scheduler / static）
scripts/             打包与测试脚本（build_exe.bat / mock_platform.py / e2e_native.py / gen_icons.py）
```

端到端测试：`python scripts/mock_platform.py` 起本地假平台（端口 39001），再 `python scripts/e2e_native.py` 跑全流程断言。

## Limitations

- 余额通用探测是尽力而为，成功率取决于目标站响应格式
- session 保存在内存，服务重启后需重新登录（数据无损）
- Windows exe 每次启动解压，慢 2~3 秒

## License

[MIT](LICENSE)
