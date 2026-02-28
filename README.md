# Reverse Image Search Bot

## How to use me

Send me an image, sticker, video/gif or url and I will send you direct reverse
image search links for SauceNao, Google, Yandex and the like. For anime images
I recommend SauceNao, for other images I recommend to use Google, Yandex.

Supported engines:

- All-in-one: Google, Yandex, Baidu, Shutterstock, Bing, TinEye, Sogou
- Artworks & Anime: SauceNAO, Trace, ascii2d
- Cosplayers: 3D IQDB *(button only — indexes not updated in 2+ years)*

> **Note:** IQDB was removed as SauceNAO is a full superset and indexes all the
> same sources. 3D IQDB is kept as a search button but has no auto-search
> support since its indexes have not been updated in over 2 years.

Inline results support:

SauceNAO, Trace

## Commands

- `/start`: Welcome message with quick-access keyboard (private) or guide image (groups)
- `/help`: Commands overview with multilingual help links
- `/search`: Reply to a message with an image or video to start a search
- `/settings` (`/conf`, `/pref`): Per-chat settings via inline keyboard

## Per-Chat Settings

Use `/settings` to configure the bot per chat via an interactive inline
keyboard. In group chats only admins (creator/administrator) can change
settings.

**Main toggles:**

- **Auto-search** — automatically search when an image is sent
- **Show buttons** — show engine buttons below results
- At least one of these must remain enabled

**Sub-menus (unlocked when the parent toggle is on):**

- **Auto-search engines** — choose which engines run automatically (only
  engines with inline/best-match support). Disabling the last engine turns off
  auto-search entirely and resets the list so all engines are available when
  re-enabled.
- **Engine buttons** — choose which engine buttons appear, plus toggle the
  "Best match" and "Go to image" link buttons.

Settings are stored per `chat_id`, so each group gets its own configuration.
Engines that return 5 consecutive empty results are automatically disabled for
that chat (with a notification); re-enable them from `/settings`.

![example](https://raw.githubusercontent.com/Nachtalb/reverse_image_search_bot/master/reverse_image_search_bot/images/help.jpg)

## Author

- [Nachtalb on Github](https://github.com/Nachtalb)
- [@Nachtalb on Telegram](https://t.me/Nachtalb)

## Donations

- [PayPal](https://paypal.me/Espig)
- BTC: `3E6Pw8gwLJSyfumpjuJ6CWNKjZJLCmXZ2G`
- BTC/BSC: `0x3c5211340Db470A31F1a37E343E326db69FF2F5C`
- ETH: `0x3c5211340Db470A31F1a37E343E326db69FF2F5C`
- USDC: `0x3c5211340Db470A31F1a37E343E326db69FF2F5C`
- PayString: `nachtalb$paystring.crypto.com`

## Other Bots

- [@XenianBot](https://t.me/XenianBot) All general purpose but with tons of functionality

## Issues / Contributions

- [Code repository](https://github.com/Nachtalb/reverse_image_search_bot)
- [@Nachtalb](https://t.me/Nachtalb)
- via /support at [@XenianBot](https://t.me/Nachtalb)

Thank you for using [@reverse_image_search_bot](https://t.me/reverse_image_search_bot).

### Installation

Requires at least **Python 3.10**.

Install all dependencies:

```bash
pip install -r requirements.txt
```

Configuration is done entirely via environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_API_TOKEN` | ✅ | — | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `SAUCENAO_API` | ✅ | — | [SauceNAO API key](https://saucenao.com/user.php?page=search-api) |
| `TRACE_API` | ✅ | — | [Trace.moe API key](https://soruly.github.io/trace.moe-api/#/limits) |
| `ANILIST_TOKEN` | ❌ | — | AniList OAuth access token (raises rate limit from 90 to 120 req/min) |
| `UPLOADER_TYPE` | ❌ | `local` | Uploader backend: `local` or `ssh` |
| `UPLOADER_URL` | ✅ | — | Public base URL for uploaded files |
| `UPLOADER_PATH` | ✅ (local) | — | Local directory to store uploads |
| `UPLOADER_HOST` | ✅ (ssh) | — | SSH host |
| `UPLOADER_USER` | ✅ (ssh) | — | SSH username |
| `UPLOADER_PASSWORD` | ✅ (ssh) | — | SSH password |
| `UPLOADER_UPLOAD_DIR` | ✅ (ssh) | — | Remote upload directory |
| `UPLOADER_KEY_FILENAME` | ❌ (ssh) | — | Path to SSH private key |
| `ADMIN_IDS` | ❌ | — | Comma-separated Telegram user IDs with admin access |
| `MODE_ACTIVE` | ❌ | `polling` | `polling` or `webhook` |
| `MODE_LISTEN` | ✅ (webhook) | — | Listen address |
| `MODE_PORT` | ✅ (webhook) | — | Listen port |
| `MODE_URL_PATH` | ✅ (webhook) | — | URL path for webhook |
| `MODE_WEBHOOK_URL` | ✅ (webhook) | — | Full public webhook URL |
| `WORKERS` | ❌ | `4` | Number of worker threads |
| `CON_POOL_SIZE` | ❌ | `WORKERS+4` | Connection pool size |
| `CONFIG_DIR` | ❌ | `~/.config/reverse_image_search_bot` | Config directory |

Start the bot:

```bash
python run_bot.py
```

Thank you for using [@reverse_image_search_bot](https://t.me/reverse_image_search_bot).
