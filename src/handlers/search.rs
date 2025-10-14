use futures::future::join_all;
use reqwest::Url;
use teloxide::types::{InlineKeyboardButton, InputFile, ParseMode};
use tokio::task::JoinHandle;

use crate::display;
use crate::models::{AnimeData, Enriched, FanartData, GenericData, MangaData};
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
    let mut handles: Vec<JoinHandle<Result<(), _>>> = Vec::new();

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
            Ok(Ok(())) => {}
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

async fn send_search_result(bot: Bot, msg: Message, result: Enriched) -> Result<()> {
    if !result.any() {
        log::warn!("send_search_result called with no enrichments");
        return Ok(());
    }

    let mut send_generic = true;

    if let Some(anime) = result.anime {
        send_generic = false;
        match send_anime_search_result_message(&bot, msg.chat.id, &anime).await {
            Ok(_) => {}
            Err(err) => {
                log::error!("Failed to send anime search result: {}", err);
                Err(err)?
            }
        }
    }

    if let Some(manga) = result.manga {
        send_generic = false;
        send_manga_search_result_message(&bot, msg.chat.id, &manga).await?;
    }

    if let Some(fanart) = result.fanart {
        send_generic = false;
        send_fanart_search_result_message(&bot, msg.chat.id, &fanart).await?;
    }

    if send_generic && let Some(generic) = result.generic {
        send_generic_search_result_message(&bot, msg.chat.id, &generic).await?;
    }

    Ok(())
}

async fn send_video(bot: &Bot, chat_id: ChatId, url: &str, text: String) -> Result<Message> {
    log::info!("Send video result to: {}", chat_id);
    let input_file = InputFile::url(Url::parse(url).unwrap());
    bot.send_video(chat_id, input_file)
        .caption(text)
        .show_caption_above_media(true)
        .parse_mode(ParseMode::Html)
        .await
        .map_err(anyhow::Error::from)
}

async fn send_image(bot: &Bot, chat_id: ChatId, url: &str, text: String) -> Result<Message> {
    log::info!("Send image result to: {}", chat_id);
    let input_file = InputFile::url(Url::parse(url).unwrap());
    bot.send_photo(chat_id, input_file)
        .caption(text)
        .show_caption_above_media(true)
        .parse_mode(ParseMode::Html)
        .await
        .map_err(anyhow::Error::from)
}

async fn send_text(bot: &Bot, chat_id: ChatId, text: String) -> Result<Message> {
    log::info!("Send text result to: {}", chat_id);
    bot.send_message(chat_id, text)
        .parse_mode(ParseMode::Html)
        .await
        .map_err(anyhow::Error::from)
}

async fn send_generic_search_result_message(
    bot: &Bot,
    chat_id: ChatId,
    generic: &GenericData,
) -> Result<()> {
    log::info!("Sending generic search result");
    let text = display::generic::format(generic);

    send_text(bot, chat_id, text).await?;

    Ok(())
}

async fn send_fanart_search_result_message(
    bot: &Bot,
    chat_id: ChatId,
    fanart: &FanartData,
) -> Result<Message> {
    log::info!("Sending fanart search result");
    let text = display::fanart::format(fanart);

    if let Some(url_data) = &fanart.main_url
        && let Some(url) = &url_data.url
    {
        send_image(bot, chat_id, url, text).await
    } else {
        send_text(bot, chat_id, text).await
    }
}

async fn send_manga_search_result_message(
    bot: &Bot,
    chat_id: ChatId,
    manga: &MangaData,
) -> Result<Message> {
    log::info!("Sending manga search result");
    let text = display::manga::format(manga);

    if let Some(cover) = &manga.cover {
        send_image(bot, chat_id, cover, text).await
    } else {
        send_text(bot, chat_id, text).await
    }
}

async fn send_anime_search_result_message(
    bot: &Bot,
    chat_id: ChatId,
    anime: &AnimeData,
) -> Result<Message> {
    log::info!("Sending anime search result");
    let text = display::anime::format(anime);

    let video = anime
        .episodes
        .clone()
        .and_then(|episodes| episodes.hit_video);
    let image = &anime
        .episodes
        .clone()
        .and_then(|episodes| episodes.hit_image)
        .or(anime.cover.clone());

    if let Some(video) = video {
        send_video(bot, chat_id, &video, text).await
    } else if let Some(image) = image {
        send_image(bot, chat_id, image, text).await
    } else {
        send_text(bot, chat_id, text).await
    }
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
