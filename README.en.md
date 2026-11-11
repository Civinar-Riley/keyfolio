# Keyfolio · Local-first API Asset Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/Civinar-Riley/keyfolio)](https://github.com/Civinar-Riley/keyfolio/releases)

[中文](README.md) | English

Manage all your API keys from one local tool: store credentials, verify keys, pull model lists, check balances, watch balance trends on a dashboard, and export ready-to-paste configs to any client. Data stays on your machine; key fields are encrypted with AES-GCM.

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="49%" alt="Dashboard">
  <img src="docs/screenshots/channels.png" width="49%" alt="Channels">
</p>

## Features

- **Credential vault**: channels (name / type / base URL / console URL / group / notes) with multiple keys each; keys masked by default; provider presets for OpenAI / Claude / Gemini / DeepSeek / SiliconFlow / OpenRouter / Moonshot / Zhipu; key expiry dates surfaced in lists and dashboard
- **One-click verification**: `GET /v1/models` reachability test (free), optional real request with `max_tokens=1`; reasoning models automatically fall back to `max_completion_tokens`
- **Model discovery & sync**: pull model IDs, save selected IDs, add manually, or paste JSON; re-pull shows added / removed / revived models for confirmation (removed models get disabled, not deleted; manually disabled models stay disabled; auto-disabled models can be revived when they reappear)
- **Balance queries**: per-platform adapters (DeepSeek / SiliconFlow / OpenRouter …), generic read-only probing as fallback, then explicit failure reasons (401/404/timeout) and manual entry; automatic queries preserve manually entered expiry dates and currencies; every result is recorded to history
- **Dashboard**: all key balances, statuses and expiries on one page, filter by group/type, sort by balance/updated time, balance trend chart (Chart.js, 7/30/90/365 days)
- **One-click export**: placeholder templates (`{name}` `{base_url}` `{api_base}` `{key}` `{model}` `{models}` …) with SillyTavern / ZCode / dsh / .env / cURL / OpenAI SDK / generic presets, fully editable; `{api_base}` appends a version segment only when missing, so a base URL with or without `/v1` never doubles
- **Quick capture**: paste any text, the parser extracts Base URL and key, respects the selected channel type, then tests and saves in one go; saving the same Base URL again appends a key instead of creating a channel
- **Security**: master password + optional TOTP 2FA + backup codes; recovery code for password reset; 5-failure lockout for 5 minutes; server-side screen lock (data APIs return 423 while locked, surviving refresh); sessions restored on page reload; password change signs out other devices; field-level AES-GCM encryption
- **Backup**: full .json export (optionally encrypted when it contains keys), import with overwrite or merge-and-dedup; encrypted backups restore login credentials and key ciphertext across installations

## Architecture

- Backend: Python + FastAPI + SQLite (WAL), httpx for outbound calls, asyncio scheduler
- Frontend: no-build Vue 3 (vendored ESM) + Chart.js, responsive layout, PWA (manifest + Service Worker)
- Packaging: Windows PyInstaller onefile / Docker / native Python — same codebase everywhere

## Quick Start

### Docker (recommended for NAS / servers)

```bash
docker compose up -d
# open http://<host>:7465
```

Data volume is mounted at `./data:/app/data`; migration = copying the `data/` folder. Env vars: `KEYFOLIO_PORT` (default 7465), `TZ`.

### Native

```bash
pip install -r requirements.txt
python main.py
# default http://127.0.0.1:7465; override with KEYFOLIO_HOST / KEYFOLIO_PORT / KEYFOLIO_DATA_DIR
```

### Windows exe

Download [keyfolio.exe](https://github.com/Civinar-Riley/keyfolio/releases/latest/download/keyfolio.exe), double-click, and the browser opens automatically. `data/` and `app.log` live next to the exe.

## Mobile

Open the service URL on a phone for the full responsive UI (<768px switches to bottom navigation, single column). Installable as a PWA in secure contexts (localhost or HTTPS reverse proxy); over plain LAN HTTP everything still works, only installation is unavailable.

## Data & Security

- Sensitive fields are encrypted with a random data key (AES-GCM); the data key is wrapped separately by the master password (scrypt) and the recovery code
- A recovery code is generated once at setup and shown a single time; it can reset the password (and generates a new code)
- Screen lock is server-side: data APIs return 423 while locked, surviving refresh and new tabs; the data key still lives in the server process memory and is cleared on restart
- Sessions are in-memory and expire after 7 days idle; restart requires re-login
- Exports containing plaintext keys trigger an explicit warning, with optional whole-file encryption; encrypted overwrite imports restore login credentials and key ciphertext
- Lost password without a recovery code = data unrecoverable; keep encrypted backups

## Development

```
main.py              entry point
app/                 backend (db / crypto / auth / routers / adapters / scheduler / static)
scripts/             packaging & test scripts (build_exe.bat / mock_platform.py / e2e_native.py / gen_icons.py)
```

E2E tests: run `python scripts/e2e_native.py`; the script starts the fake platform on port 39001 itself and shuts down when done.

## Limitations

- Generic balance probing is best-effort and depends on the target site's response format; platforms without a balance API still need manual entry
- Sessions are in-memory and expire after 7 days idle; restart requires re-login (no data loss)
- The lock screen blocks API access, but the data key remains in server process memory until restart
- The onefile exe extracts on every launch (~2–3s)

## License

[MIT](LICENSE)
