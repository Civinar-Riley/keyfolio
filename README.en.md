# Keyfolio · Local-first API Asset Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)

[中文](README.md) | English

Manage all your API keys from one local tool: store credentials, verify keys, pull model lists, check balances, watch balance trends on a dashboard, and export ready-to-paste configs to any client. Data stays on your machine; key fields are encrypted with AES-GCM.

## Features

- **Credential vault**: channels (name / type / base URL / console URL / group / notes) with multiple keys each; keys masked by default
- **One-click verification**: `GET /v1/models` reachability test (free), optional real request with `max_tokens=1`
- **Model discovery & sync**: pull `/v1/models`, save selected IDs, add manually, or paste JSON; re-pull shows an add/remove diff for confirmation (removed models get disabled, not deleted; local edits preserved)
- **Balance queries**: per-platform adapters (DeepSeek / SiliconFlow / OpenRouter …), generic read-only probing as fallback, then explicit failure reasons (401/404/timeout) and manual entry; every result is recorded to history
- **Dashboard**: all key balances and statuses on one page, filter by group/type, sort by balance/updated time, balance trend chart (Chart.js)
- **One-click export**: placeholder JSON templates (`{name}` `{base_url}` `{key}` `{models}` …) with SillyTavern / ZCode / generic presets, fully editable
- **Quick capture**: paste any text, the parser extracts Base URL and key, then test and save in one go
- **Security**: master password + optional TOTP 2FA + backup codes; recovery code for password reset; 5-failure lockout for 5 minutes; lock screen; password change; field-level AES-GCM encryption
- **Backup**: full .json export (optionally encrypted when it contains keys), import with overwrite or merge-and-dedup

## Architecture

- Backend: Python + FastAPI + SQLite (WAL), httpx for outbound calls, asyncio scheduler
- Frontend: no-build Vue 3 (vendored ESM) + Chart.js, responsive layout, PWA (manifest + Service Worker)
- Packaging: Windows PyInstaller onefile / Docker / native Python — same codebase everywhere

## Quick Start

### Docker (recommended for NAS / servers)

```bash
docker compose up -d
# open http://<host>:3000
```

Data volume is mounted at `./data:/app/data`; migration = copying the `data/` folder. Env vars: `KEYFOLIO_PORT` (default 3000), `TZ`.

### Native

```bash
pip install -r requirements.txt
python main.py
# default http://127.0.0.1:3000; override with KEYFOLIO_HOST / KEYFOLIO_PORT / KEYFOLIO_DATA_DIR
```

### Windows exe

Download `keyfolio.exe`, double-click, the browser opens automatically. `data/` and `app.log` live next to the exe.

## Mobile

Open the service URL on a phone for the full responsive UI (<768px switches to bottom navigation, single column). Installable as a PWA in secure contexts (localhost or HTTPS reverse proxy); over plain LAN HTTP everything still works, only installation is unavailable.

## Data & Security

- Sensitive fields are encrypted with a random data key (AES-GCM); the data key is wrapped separately by the master password (scrypt) and the recovery code
- A recovery code is generated once at setup and shown a single time; it can reset the password (and generates a new code)
- Exports containing plaintext keys trigger an explicit warning, with optional whole-file encryption
- Lost password without a recovery code = data unrecoverable; keep encrypted backups

## Development

```
main.py              entry point
app/                 backend (db / crypto / auth / routers / adapters / scheduler / static)
scripts/             packaging & test scripts (build_exe.bat / mock_platform.py / e2e_native.py / gen_icons.py)
```

E2E tests: start the fake platform with `python scripts/mock_platform.py` (port 39001), then run `python scripts/e2e_native.py`.

## Limitations

- Generic balance probing is best-effort and depends on the target site's response format
- Sessions are in-memory; restart requires re-login (no data loss)
- The onefile exe extracts on every launch (~2–3s)

## License

[MIT](LICENSE)
