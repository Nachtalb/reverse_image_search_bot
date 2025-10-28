use anyhow::{Error, Result};
use teloxide::{dispatching::UpdateHandler, prelude::*, utils::command::BotCommands};

use crate::handlers::media;

#[derive(BotCommands, Clone, Debug)]
#[command(
    rename_rule = "lowercase",
    description = "These commands are supported"
)]
pub(crate) enum Command {
    #[command(description = "Startup message")]
    Start,
    #[command(description = "Show a help text")]
    Help,
    #[command(description = "Reply with this to an image / video to search")]
    Search,
}

async fn handle_search_message(bot: Bot, msg: Message) -> Result<()> {
    let chat_id = msg.chat.id;

    if let Some(reply_to_msg) = msg.reply_to_message() {
        if media::filter_for_media_message(reply_to_msg.clone()) {
            media::handle_media_message(bot, reply_to_msg.clone()).await?
        } else {
            bot.send_message(
                chat_id,
                "Please reply to a message that contains media content.",
            )
            .await?;
        }
    } else {
        bot.send_message(
            chat_id,
            "Please reply to a message to search for its content.",
        )
        .await?;
    }

    Ok(())
}

async fn handle_start_message(bot: Bot, msg: Message) -> Result<()> {
    bot.send_message(
        msg.chat.id,
        "Send me a video or image you want to search for!",
    )
    .await?;
    Ok(())
}

async fn handle_help_message(bot: Bot, msg: Message) -> Result<()> {
    bot.send_message(msg.chat.id, "Coming Soon ™").await?;
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
