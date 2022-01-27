# Reverse Image Search Bot

## How to use me

Send me an image, sticker, video/gif or url and I will send you direct reverse
image search links for SauceNao, Google, Yandex and the like. For anime images
I recommend SauceNao, for other images I recommend to use Google, Yandex.

Supported engines:

- All-in-one: Google, Yandex, Baidu, Shutterstock, Bing, TinEye, Sogou
- Artworks & Anime: SauceNAO, IQDB, Trace, ascii2d

Inline results support:

SauceNAO, IQDB, Trace

## Commands

- `/help`, `/start`: Show this help message
- `/credits`: Show all available engines (and what they are best for), data
  providers and other credits.
- `/tips`: Various tips and tricks for better search results
- `/search`: Reply to a message with an image or video to start a search
- `/auto_search`: Toggle auto search on and off

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

Best if you create a python virtualenv.

Install all dependencies with:

```bash
pip install -r requirements.txt
```

After this is complete, you have to get an API Token from Telegram. You can
easily get one via [@BotFather](https://t.me/BotFather).

Now that you have your API Token copy the `settings.example.py` to `settings.py`
and paste in your API Token and so on.

Finally you can use this to start your bot.

```bash
python run_bot.py
```

Thank you for using [@reverse_image_search_bot](https://t.me/reverse_image_search_bot).
