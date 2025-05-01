use std::error::Error;
use teloxide::types::InlineKeyboardButton;

use crate::handlers::file::download_file;
use crate::types::HandlerResponse;

use teloxide::dispatching::UpdateHandler;
use teloxide::prelude::*;

fn format_url(template: &str, url: &str) -> reqwest::Url {
    let formatted = template.replace("{}", url);
    reqwest::Url::parse(&formatted).unwrap()
}

fn button(text: &str, template: &str, url: &str) -> InlineKeyboardButton {
    InlineKeyboardButton::url(text, format_url(template, url))
}

fn buttons_from_url(url: &str) -> Vec<Vec<InlineKeyboardButton>> {
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

            let keyboard = teloxide::types::InlineKeyboardMarkup::new(buttons_from_url(file_url));

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
    use teloxide::{dptree, types::InlineKeyboardButtonKind};
    use teloxide_tests::{MockBot, MockMessagePhoto, MockMessageVideo};

    use super::*;

    #[tokio::test]
    async fn test_buttons() {
        let expected_url = "https://domain.com";
        let buttons = buttons_from_url(expected_url);
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
