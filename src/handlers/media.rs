use std::error::Error;

use crate::handlers::file::download_file;
use crate::types::HandlerResponse;

use teloxide::dispatching::UpdateHandler;
use teloxide::prelude::*;

async fn handle_photo(bot: Bot, msg: Message) -> HandlerResponse<()> {
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

                    bot.send_message(
                        chat_id,
                        "Oh no, something went wrong while trying to save the photo.",
                    )
                    .await?;
                    return Err(Box::new(err));
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

pub async fn handle_media(bot: Bot, msg: Message) -> HandlerResponse<()> {
    if msg.photo().is_some() {
        handle_photo(bot, msg).await?
    } else if msg.video().is_some() {
        handle_video(bot, msg).await?
    } else {
        log::warn!("handle_media called with unexpected message");
    }

    Ok(())
}

pub fn branch() -> UpdateHandler<Box<dyn Error + Send + Sync + 'static>> {
    Update::filter_message()
        .filter(|msg: Message| msg.photo().is_some() || msg.video().is_some())
        .endpoint(handle_media)
}

#[cfg(test)]
mod tests {
    use teloxide::dptree;
    use teloxide_tests::{MockBot, MockMessagePhoto, MockMessageVideo};

    use super::*;

    #[tokio::test]
    async fn test_handle_video() {
        let tree = dptree::entry().branch(branch());
        let mut bot = MockBot::new(MockMessageVideo::new(), tree);

        bot.dispatch_and_check_last_text("Received Video").await;
    }

    #[tokio::test]
    async fn test_handle_photo() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessagePhoto::new();
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text(
            "Oh no, something went wrong while trying to save the photo.",
        )
        .await;
    }
}
