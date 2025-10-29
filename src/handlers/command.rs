use anyhow::{Error, Result};
use teloxide::{
    dispatching::UpdateHandler,
    prelude::*,
    types::{InputFile, LinkPreviewOptions},
    utils::command::BotCommands,
};

use crate::handlers::media;

#[derive(BotCommands, Clone, Debug)]
#[command(
    rename_rule = "lowercase",
    description = "These commands are supported"
)]
pub(crate) enum Command {
    #[command(description = "Startup message")]
    Start,
    #[command(description = "How to search?")]
    Help,
    #[command(description = "Reply with /search to an image or video.")]
    Search,
}

async fn handle_search_message(bot: Bot, msg: Message) -> Result<()> {
    let chat_id = msg.chat.id;

    if let Some(reply_to_msg) = msg.reply_to_message() {
        if media::filter_for_media_message(reply_to_msg.clone()) {
            media::handle_media_message(bot, reply_to_msg.clone()).await?
        } else {
            bot.send_message(chat_id, t!("message.reply_to_media").as_ref())
                .await?;
        }
    } else {
        bot.send_message(chat_id, t!("message.reply_to_media").as_ref())
            .await?;
    }

    Ok(())
}

async fn handle_start_message(bot: Bot, msg: Message) -> Result<()> {
    let preview_options = LinkPreviewOptions {
        url: Some(t!("message.start.preview_url").to_string()),
        is_disabled: false,
        prefer_small_media: true,
        prefer_large_media: false,
        show_above_text: false,
    };
    bot.send_message(msg.chat.id, t!("message.start").as_ref())
        .link_preview_options(preview_options)
        .parse_mode(teloxide::types::ParseMode::Html)
        .await?;
    Ok(())
}

async fn handle_help_message(bot: Bot, msg: Message) -> Result<()> {
    let image = include_bytes!("../../images/help.jpg");
    let photo = InputFile::memory(image.as_slice());
    bot.send_photo(msg.chat.id, photo)
        .caption(t!("message.help").as_ref())
        .show_caption_above_media(true)
        .parse_mode(teloxide::types::ParseMode::Html)
        .await?;
    Ok(())
}

async fn command_dispatcher(bot: Bot, msg: Message, cmd: Command) -> Result<()> {
    match cmd {
        Command::Start => handle_start_message(bot, msg).await?,
        Command::Help => handle_help_message(bot, msg).await?,
        Command::Search => handle_search_message(bot, msg).await?,
    };

    Ok(())
}

pub(crate) fn branch() -> UpdateHandler<Error> {
    Update::filter_message()
        .filter_command::<Command>()
        .endpoint(command_dispatcher)
}
