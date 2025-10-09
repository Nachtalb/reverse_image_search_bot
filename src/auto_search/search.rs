use reqwest::Url;
use teloxide::types::InputFile;

use crate::auto_search::anilist;
use crate::auto_search::tracemoe::{self};
use crate::types::HandlerResult;

use teloxide::prelude::*;

async fn search_via_trace_moe(bot: &Bot, msg: &Message, url: &str) -> HandlerResult<()> {
    let response = match tracemoe::search_by_url(url).await {
        Ok(response) => response,
        Err(err) => {
            log::error!("{}", err);
            return Ok(());
        }
    };

    if response.result.is_empty() {
        log::info!("No results found for {}", url);
        return Ok(());
    }

    log::info!("Search resulted in {} results", response.result.len());

    if let Some(best) = tracemoe::best_or_none(response, None) {
        log::info!("Best result: {:?}", best);
        let mut text: Option<String> = None;

        match anilist::get_anime(best.anilist as i32).await {
            Ok(details) => {
                let episode = match best.episode {
                    Some(ep) => match ep {
                        trace_moe::tracemoe::Episode::Number(e) => Some(e as u32),
                        trace_moe::tracemoe::Episode::Text(_) => None,
                    },
                    None => None,
                };
                text = Some(anilist::text(&details, episode))
            }
            Err(err) => {
                log::error!(
                    "Did not find any anilist entry for id {}: {}",
                    best.anilist,
                    err
                );
            }
        }

        if let Some(search_result_text) = text {
            let photo_url = match Url::parse(best.image.as_str()) {
                Ok(url) => url,
                Err(e) => {
                    log::error!("Failed to parse url: {}", e);
                    return Ok(());
                }
            };
            bot.send_photo(msg.chat.id, InputFile::url(photo_url))
                .caption(search_result_text)
                .show_caption_above_media(true)
                .parse_mode(teloxide::types::ParseMode::MarkdownV2)
                .await?;
        }
    }

    Ok(())
}

pub(crate) async fn search(bot: &Bot, msg: &Message, url: &str) -> HandlerResult<()> {
    search_via_trace_moe(bot, msg, url).await
}
