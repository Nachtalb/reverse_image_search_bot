use teloxide::{dispatching::UpdateHandler, prelude::*, utils::command::BotCommands};

use crate::types::HandlerResult;

#[derive(BotCommands, Clone, Debug)]
#[command(
    rename_rule = "lowercase",
    description = "These commands are supported"
)]
enum Command {
    #[command()]
    Start,
    #[command(description = "show this text")]
    Help,
    #[command(description = "roll a dice")]
    Roll,
}

async fn command_dispatcher(bot: Bot, msg: Message, cmd: Command) -> HandlerResult<()> {
    match cmd {
        Command::Start => bot.send_message(msg.chat.id, "Hello!").await?,
        Command::Help => {
            bot.send_message(msg.chat.id, Command::descriptions().to_string())
                .await?
        }
        Command::Roll => bot.send_dice(msg.chat.id).await?,
    };

    Ok(())
}

pub(crate) fn branch() -> UpdateHandler<Box<dyn std::error::Error + Send + Sync>> {
    Update::filter_message()
        .filter_command::<Command>()
        .endpoint(command_dispatcher)
}
