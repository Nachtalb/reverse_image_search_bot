use teloxide::{dispatching::UpdateHandler, prelude::*, utils::command::BotCommands};

use crate::{handlers::media, types::HandlerResult};

#[derive(BotCommands, Clone, Debug)]
#[command(
    rename_rule = "lowercase",
    description = "These commands are supported"
)]
enum Command {
    #[command()]
    Start,
    #[command(description = "Show a help text")]
    Help,
    #[command(description = "Search for a messages content")]
    Search,
}

async fn handle_search_message(bot: Bot, msg: Message) -> HandlerResult<()> {
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

async fn command_dispatcher(bot: Bot, msg: Message, cmd: Command) -> HandlerResult<()> {
    match cmd {
        Command::Start => {
            bot.send_message(msg.chat.id, "Hello!").await?;
        }
        Command::Help => {
            bot.send_message(msg.chat.id, Command::descriptions().to_string())
                .await?;
        }
        Command::Search => handle_search_message(bot, msg).await?,
    };

    Ok(())
}

pub(crate) fn branch() -> UpdateHandler<Box<dyn std::error::Error + Send + Sync>> {
    Update::filter_message()
        .filter_command::<Command>()
        .endpoint(command_dispatcher)
}
