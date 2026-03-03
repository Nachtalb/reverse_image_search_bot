# Reverse Image Search Bot

A Telegram bot that performs reverse image searches across multiple engines
including Google, Yandex, SauceNAO, Trace, and more.

→ **[Usage & Commands](USAGE.md)**

## Quick Start

```yaml
# docker-compose.yml
services:
  ris-bot:
    image: ghcr.io/nachtalb/reverse_image_search_bot:latest
    restart: unless-stopped
    environment:
      TELEGRAM_API_TOKEN: ""
      SAUCENAO_API: ""
      TRACE_API: ""
      UPLOADER_URL: ""
      UPLOADER_PATH: /data/uploads
    volumes:
      - ris-data:/data

volumes:
  ris-data:
```

```bash
docker compose up -d
```

## Configuration

All configuration is done via environment variables.

### Required

| Variable | Description |
|---|---|
| `TELEGRAM_API_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `SAUCENAO_API` | [SauceNAO API key](https://saucenao.com/user.php?page=search-api) |
| `TRACE_API` | [Trace.moe API key](https://soruly.github.io/trace.moe-api/#/limits) |
| `UPLOADER_URL` | Public base URL for uploaded files |
| `UPLOADER_PATH` | Local directory to store uploads (when using `local` uploader) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `ADMIN_IDS` | — | Comma-separated Telegram user IDs with admin access |
| `ANILIST_TOKEN` | — | AniList OAuth token (raises rate limit from 90 to 120 req/min) |
| `MODE_ACTIVE` | `polling` | Bot mode: `polling` or `webhook` |
| `CONCURRENT_UPDATES` | `16` | Number of concurrent update handlers |
| `OLD_CONFIG_DIR` | `~/.config/reverse_image_search_bot` | Legacy config directory (used for JSON→SQLite migration only) |
| `PIXIV_CONFIG` | `~/.config/reverse_image_search_bot/pixiv.json` | Path to the Pixiv config file |
| `CONFIG_DB_PATH` | `~/.config/reverse_image_search_bot/config.db` | Path to the configuration database |
| `PERSISTENCE_PATH` | `~/.config/reverse_image_search_bot/bot_data.pickle` | Path to the bot persistence file |
| `LOG_FORMAT` | `%(asctime)s - %(name)s - %(levelname)s - %(message)s` | Python log format string |
| `METRICS_ENABLED` | `true` | Enable Prometheus metrics endpoint |
| `RIS_METRICS_PORT` | `9100` | Prometheus metrics port |

### Uploader (SSH)

Set `UPLOADER_TYPE=ssh` to upload files via SSH instead of storing locally.

| Variable | Description |
|---|---|
| `UPLOADER_HOST` | SSH host |
| `UPLOADER_USER` | SSH username |
| `UPLOADER_PASSWORD` | SSH password |
| `UPLOADER_UPLOAD_DIR` | Remote upload directory |
| `UPLOADER_KEY_FILENAME` | Path to SSH private key (optional) |

### Webhook Mode

Set `MODE_ACTIVE=webhook` to use webhooks instead of polling.

| Variable | Description |
|---|---|
| `MODE_LISTEN` | Listen address |
| `MODE_PORT` | Listen port |
| `MODE_URL_PATH` | URL path for webhook |
| `MODE_WEBHOOK_URL` | Full public webhook URL |
