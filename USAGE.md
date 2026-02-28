# Usage

Send the bot an image, sticker, video/gif, or URL and it will return direct
reverse image search links for multiple engines.

**Recommended engines:**

- Anime/artwork → SauceNAO
- General images → Google, Yandex

## Supported Engines

| Category | Engines |
|---|---|
| All-in-one | Google, Yandex, Baidu, Shutterstock, Bing, TinEye, Sogou |
| Artworks & Anime | SauceNAO, Trace, ascii2d |
| Cosplayers | 3D IQDB *(button only — indexes not updated in 2+ years)* |

> **Note:** IQDB was removed as SauceNAO is a full superset. 3D IQDB is kept
> as a search button only.

**Inline results:** SauceNAO, Trace

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message with quick-access keyboard (private) or guide image (groups) |
| `/help` | Commands overview with multilingual help links |
| `/search` | Reply to a message with an image or video to start a search |
| `/settings` | Per-chat settings via inline keyboard (aliases: `/conf`, `/pref`) |

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
