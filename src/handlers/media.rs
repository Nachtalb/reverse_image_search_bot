use std::error::Error;
use std::path::PathBuf;
use teloxide::types::{FileMeta, InlineKeyboardButton};

use crate::types::HandlerResult;
use crate::utils::{file, keyboard::button};

use teloxide::dispatching::UpdateHandler;
use teloxide::prelude::*;

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

async fn download(
    bot: &Bot,
    msg: &Message,
    file_meta: &FileMeta,
) -> Result<PathBuf, Box<dyn Error + Send + Sync + 'static>> {
    match file::download_file(&bot, &file_meta).await {
        Ok(dest) => {
            log::info!("File ID: {} downloaded to {}", file_meta.id, dest.display());
            Ok(dest)
        }
        Err(err) => {
            log::error!("Failed to download/save file ID {}: {}", file_meta.id, err);

            bot.send_message(
                msg.chat.id,
                "Oh no, something went wrong while receiving your file.",
            )
            .await?;
            Err(Box::new(err))
        }
    }
}

async fn send_search_message(bot: Bot, msg: Message, url: &str) -> HandlerResult<()> {
    let keyboard = teloxide::types::InlineKeyboardMarkup::new(search_buttons(&url));

    bot.send_message(msg.chat.id, "Search for Image")
        .reply_markup(keyboard)
        .await?;

    Ok(())
}

fn get_file_url(file: PathBuf) -> String {
    // DEBUG
    return "https://ris.naa.gg/f/AQADuMsxG0FIKFN8.jpg".to_string();
}

async fn handle_photo_message(bot: Bot, msg: Message) -> HandlerResult<()> {
    let chat_id = msg.chat.id;

    log::info!("Received Photo in chat {}", chat_id);
    bot.send_message(chat_id, "Received Photo").await?;
    if let Some(photo_size) = msg.photo() {
        if let Some(photo) = photo_size.last() {
            let dest = download(&bot, &msg, &photo.file).await?;
            send_search_message(bot, msg, &get_file_url(dest)).await?
        }
    }
    Ok(())
}

async fn handle_video_message(bot: Bot, msg: Message) -> HandlerResult<()> {
    log::info!("Received Video in chat {}", msg.chat.id);
    send_not_implemented(bot, msg).await
}

async fn send_not_implemented(bot: Bot, msg: Message) -> HandlerResult<()> {
    bot.send_message(msg.chat.id, "Not implemented yet").await?;
    Ok(())
}
async fn send_not_supported(bot: Bot, msg: Message) -> HandlerResult<()> {
    bot.send_message(msg.chat.id, "Not supported").await?;
    Ok(())
}

async fn handle_document_message(bot: Bot, msg: Message) -> HandlerResult<()> {
    log::info!("Received document in chat {}", msg.chat.id);

    if let Some(document) = msg.document() {
        let mut main_type: String = "".to_string();
        if let Some(mime_type) = &document.mime_type {
            main_type = mime_type.type_().as_str().to_string();
        }
        if let Some(filename) = &document.file_name {
            let guess = mime_guess::from_path(filename);
            if let Some(mime_type) = guess.first() {
                main_type = mime_type.type_().as_str().to_string();
            }
        }

        match main_type.as_str() {
            "image" => {
                let dest = download(&bot, &msg, &document.file).await?;
                send_search_message(bot, msg, &get_file_url(dest)).await?
            }
            "video" => send_not_implemented(bot, msg).await?,
            _ => send_not_supported(bot, msg).await?,
        }
    } else {
        send_not_supported(bot, msg).await?
    }

    Ok(())
}

async fn handle_sticker_message(bot: Bot, msg: Message) -> HandlerResult<()> {
    log::info!("Received sticker in chat {}", msg.chat.id);

    if let Some(sticker) = msg.sticker() {
        if sticker.is_regular() && sticker.is_static() {
            let dest = download(&bot, &msg, &sticker.file).await?;
            send_search_message(bot, msg, &get_file_url(dest)).await?;
        } else if sticker.is_regular() && sticker.is_regular() && sticker.is_video() {
            send_not_implemented(bot, msg).await?;
        } else {
            send_not_supported(bot, msg).await?;
        }
    }

    Ok(())
}

async fn handle_animation_message(bot: Bot, msg: Message) -> HandlerResult<()> {
    log::info!("Received animation in chat {}", msg.chat.id);
    send_not_implemented(bot, msg).await?;
    Ok(())
}

pub async fn handle_media_message(bot: Bot, msg: Message) -> HandlerResult<()> {
    if msg.photo().is_some() {
        handle_photo_message(bot, msg).await?
    } else if msg.video().is_some() {
        handle_video_message(bot, msg).await?
    } else if msg.document().is_some() {
        handle_document_message(bot, msg).await?
    } else if msg.sticker().is_some() {
        handle_sticker_message(bot, msg).await?
    } else if msg.animation().is_some() {
        handle_animation_message(bot, msg).await?
    } else {
        log::warn!("handle_media called with unexpected message");
        send_not_supported(bot, msg).await?
    }

    Ok(())
}

pub fn branch() -> UpdateHandler<Box<dyn Error + Send + Sync + 'static>> {
    Update::filter_message()
        .filter(|msg: Message| {
            msg.photo().is_some()
                || msg.video().is_some()
                || msg.document().is_some()
                || msg.sticker().is_some()
                || msg.animation().is_some()
        })
        .endpoint(handle_media_message)
}

#[cfg(test)]
mod tests {
    use teloxide::{
        dptree,
        types::{
            InlineKeyboardButtonKind, MaskPoint, MaskPosition, StickerFormatFlags, StickerKind,
        },
    };
    use teloxide_tests::{
        MockBot, MockMessageAnimation, MockMessageDocument, MockMessagePhoto, MockMessageSticker,
        MockMessageVideo,
    };

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

    #[tokio::test]
    async fn test_handle_video() {
        let tree = dptree::entry().branch(branch());
        let mut bot = MockBot::new(MockMessageVideo::new(), tree);

        bot.dispatch_and_check_last_text("Not implemented yet")
            .await;
    }

    #[tokio::test]
    async fn test_handle_document() {
        let tree = dptree::entry().branch(branch());
        let mut bot = MockBot::new(MockMessageDocument::new(), tree);

        bot.dispatch_and_check_last_text("Not supported").await;
    }

    #[tokio::test]
    async fn test_handle_document_message_no_document() {
        let tree = dptree::entry().branch(branch());
        let mut bot = MockBot::new(MockMessageDocument::new(), tree);

        bot.dispatch_and_check_last_text("Not supported").await;
    }

    #[tokio::test]
    async fn test_handle_document_message_image() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageDocument::new().file_name("image.jpg");
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Search for Image").await;
    }

    #[tokio::test]
    async fn test_handle_document_message_video() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageDocument::new().file_name("video.mp4");
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Not implemented yet")
            .await;
    }

    #[tokio::test]
    async fn test_handle_document_message_other() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageDocument::new().file_name("file.pdf");
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Not supported").await;
    }

    #[tokio::test]
    async fn test_handle_sticker_regular() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageSticker::new().flags(StickerFormatFlags {
            is_animated: false,
            is_video: false,
        });
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Search for Image").await;
    }

    #[tokio::test]
    async fn test_handle_sticker_animated() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageSticker::new().flags(StickerFormatFlags {
            is_animated: true,
            is_video: false,
        });
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Not supported").await;
    }

    #[tokio::test]
    async fn test_handle_sticker_video() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageSticker::new().flags(StickerFormatFlags {
            is_animated: false,
            is_video: true,
        });
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Not implemented yet")
            .await;
    }

    #[tokio::test]
    async fn test_handle_sticker_mask() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageSticker::new().kind(StickerKind::Mask {
            mask_position: MaskPosition::new(MaskPoint::Eyes, 0.0, 0.0, 0.0),
        });
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Not supported").await;
    }

    #[tokio::test]
    async fn test_handle_sticker_emoji() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessageSticker::new().kind(StickerKind::CustomEmoji {
            custom_emoji_id: "".to_string(),
        });
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Not supported").await;
    }

    #[tokio::test]
    async fn test_handle_animation() {
        let tree = dptree::entry().branch(branch());
        let mut bot = MockBot::new(MockMessageAnimation::new(), tree);

        bot.dispatch_and_check_last_text("Not implemented yet")
            .await;
    }

    #[tokio::test]
    async fn test_handle_photo() {
        let tree = dptree::entry().branch(branch());
        let message = MockMessagePhoto::new();
        let mut bot = MockBot::new(message, tree);

        bot.dispatch_and_check_last_text("Oh no, something went wrong while receiving your file.")
            .await;
    }
}
