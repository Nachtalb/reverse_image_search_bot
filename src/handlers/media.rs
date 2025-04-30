use crate::error::DownloadError;
use crate::handlers::file::download_file;

use teloxide::prelude::*;

async fn handle_photo(bot: Bot, msg: Message) -> ResponseResult<()> {
    let chat_id = msg.chat.id;

    log::info!("Received Photo in chat {}", chat_id);
    bot.send_message(chat_id, "Received Photo").await?;
    if let Some(photo_size) = msg.photo() {
        if let Some(photo) = photo_size.last() {
            let file_id = &photo.file.id;
            log::info!("File ID: {}", file_id);

            match download_file(&bot, &photo.file).await {
                Ok(dest) => {
                    log::info!("File ID: {} downloaded to {}", file_id, dest.display());
                }
                Err(err) => {
                    log::error!("Failed to download/save file ID {}: {}", file_id, err);

                    if let DownloadError::Request(req_err) = err {
                        return Err(req_err);
                    } else {
                        bot.send_message(
                            chat_id,
                            "Oh no, something went wrong while trying to save the photo.",
                        )
                        .await?;
                    }
                }
            }

            let file_url = "https://ris.naa.gg/f/AQADgMgxGy2sWFB8.jpg";

            let buttons = vec![vec![teloxide::types::InlineKeyboardButton::url(
                "Google Search",
                reqwest::Url::parse(
                    format!(
                        "https://www.google.com/searchbyimage?safe=off&sbisrc=tg&image_url={}",
                        file_url
                    )
                    .as_str(),
                )
                .unwrap(),
            )]];
            let keyboard = teloxide::types::InlineKeyboardMarkup::new(buttons);

            bot.send_message(chat_id, "Search for Image")
                .reply_markup(keyboard)
                .await?;
        }
    }

    Ok(())
}

async fn handle_video(bot: Bot, msg: Message) -> ResponseResult<()> {
    log::info!("Received Video in chat {}", msg.chat.id);
    bot.send_message(msg.chat.id, "Received Video").await?;
    Ok(())
}

pub async fn handle_media(bot: Bot, msg: Message) -> ResponseResult<()> {
    if msg.photo().is_some() {
        handle_photo(bot, msg).await?
    } else if msg.video().is_some() {
        handle_video(bot, msg).await?
    } else {
        log::warn!("handle_media called with unexpected message");
    }

    Ok(())
}
