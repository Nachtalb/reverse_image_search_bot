use futures::future::join_all;
use reqwest::Url;
use teloxide::types::{InlineKeyboardButton, InputFile, ParseMode, ReplyMarkup};
use tokio::task::JoinHandle;

use crate::display;
use crate::models::Enrichment;
use crate::utils::keyboard::button;
use anyhow::Result;

use teloxide::prelude::*;

pub(crate) async fn search(bot: &Bot, msg: &Message, url: &str) -> Result<()> {
    let keyboard = teloxide::types::InlineKeyboardMarkup::new(search_buttons(url));

    bot.send_message(msg.chat.id, "Search for Image")
        .reply_markup(keyboard)
        .await?;

    log::info!("Sent search for image to chat {}", msg.chat.id);
    let mut rx = crate::core::orchestrator::reverse_search(url.to_string()).await;
    let mut handles: Vec<JoinHandle<Result<Message, _>>> = Vec::new();

    while let Some(result) = rx.recv().await {
        match result {
            Ok(enriched) => {
                log::info!("Found enrichments");
                let bot = bot.clone(); // Cheap
                let msg = msg.clone(); // Assuming msg also Clone
                let handle =
                    tokio::spawn(async move { send_search_result(bot, msg, enriched).await });
                handles.push(handle);
            }
            Err(_) => break,
        }
    }

    let results = join_all(handles).await;
    for result in results {
        match result {
            Ok(Ok(_)) => {}
            Ok(Err(e)) => {
                log::error!("Send failed: {:?}", e);
                return Err(e);
            }
            Err(j) => {
                log::error!("Task join failed: {:?}", j);
                return Err(anyhow::anyhow!(j));
            }
        }
    }
    log::info!("Reverse search done");

    Ok(())
}

async fn send_search_result(bot: Bot, msg: Message, result: Enrichment) -> Result<Message> {
    let text = display::enriched::format(&result);

    let video = result
        .episodes
        .clone()
        .and_then(|episodes| episodes.hit_video)
        .or(result.video.clone());
    let image = &result
        .episodes
        .clone()
        .and_then(|episodes| episodes.hit_image)
        .or(result.thumbnail.clone());

    let raw_buttons = display::telegram_buttons(&result.main_url, &result.urls);
    let buttons = if raw_buttons.is_empty() {
        None
    } else {
        Some(ReplyMarkup::inline_kb(raw_buttons))
    };

    let chat_id = msg.chat.id;

    if let Some(video) = video {
        send_video(&bot, chat_id, &video, text, buttons).await
    } else if let Some(image) = image {
        send_image(&bot, chat_id, image, text, buttons).await
    } else {
        send_text(&bot, chat_id, text, buttons).await
    }
}

async fn send_video(
    bot: &Bot,
    chat_id: ChatId,
    url: &str,
    text: String,
    buttons: Option<ReplyMarkup>,
) -> Result<Message> {
    log::info!("Send video result to: {}", chat_id);
    let input_file = InputFile::url(Url::parse(url).unwrap());
    let mut message = bot
        .send_video(chat_id, input_file)
        .caption(text)
        .show_caption_above_media(true);

    if let Some(buttons) = buttons {
        message = message.reply_markup(buttons);
    }

    message
        .parse_mode(ParseMode::Html)
        .await
        .map_err(anyhow::Error::from)
}

async fn send_image(
    bot: &Bot,
    chat_id: ChatId,
    url: &str,
    text: String,
    buttons: Option<ReplyMarkup>,
) -> Result<Message> {
    log::info!("Send image result to: {}", chat_id);
    let input_file = InputFile::url(Url::parse(url).unwrap());
    let mut message = bot
        .send_photo(chat_id, input_file)
        .caption(text)
        .show_caption_above_media(true);

    if let Some(buttons) = buttons {
        message = message.reply_markup(buttons);
    }

    message
        .parse_mode(ParseMode::Html)
        .await
        .map_err(anyhow::Error::from)
}

async fn send_text(
    bot: &Bot,
    chat_id: ChatId,
    text: String,
    buttons: Option<ReplyMarkup>,
) -> Result<Message> {
    log::info!("Send text result to: {}", chat_id);
    let mut message = bot.send_message(chat_id, text);

    if let Some(buttons) = buttons {
        message = message.reply_markup(buttons);
    }

    message
        .parse_mode(ParseMode::Html)
        .await
        .map_err(anyhow::Error::from)
}

fn search_buttons(url: &str) -> Vec<Vec<InlineKeyboardButton>> {
    vec![
        vec![button("Link", "{}", url)],
        vec![
            button("SauceNao", "https://saucenao.com/search.php?url={}", url),
            button(
                "Google",
                "https://www.google.com/searchbyimage?safe=off&sbisrc=tg&image_url={}",
                url,
            ),
        ],
        vec![
            button("Trace", "https://trace.moe/?auto&url={}", url),
            button("IQDB", "https://iqdb.org/?url={}", url),
        ],
        vec![
            button("3D IQDB", "https://3d.iqdb.org/?url={}", url),
            button(
                "Yandex",
                "https://yandex.com/images/search?url={}&rpt=imageview",
                url,
            ),
        ],
        vec![
            button(
                "Bing",
                "https://www.bing.com/images/search?q=imgurl:{}&view=detailv2&iss=sbi",
                url,
            ),
            button("TinEye", "https://tineye.com/search?url={}", url),
        ],
        vec![
            button(
                "Sogou",
                "https://pic.sogou.com/ris?flag=1&drag=0&query={}",
                url,
            ),
            button("ascii2d", "https://ascii2d.net/search/url/{}", url),
        ],
    ]
}

#[cfg(test)]
mod tests {
    use teloxide::types::InlineKeyboardButtonKind;

    use super::*;

    #[tokio::test]
    async fn test_buttons() {
        let expected_url = "https://domain.com";
        let buttons = search_buttons(expected_url);
        for button_row in buttons {
            for button in button_row {
                match button.kind {
                    InlineKeyboardButtonKind::Url(url) => {
                        assert!(url.as_str().contains(expected_url));
                    }
                    _ => panic!("Unexpected button kind"),
                }
            }
        }
    }
}
