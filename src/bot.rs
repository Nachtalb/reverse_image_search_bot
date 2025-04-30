use crate::handlers::media::handle_media;
use teloxide::{prelude::*, utils::command::BotCommands};

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

async fn command_dispatcher(bot: Bot, msg: Message, cmd: Command) -> ResponseResult<()> {
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

pub async fn run() {
    let bot = Bot::from_env();

    let handler = dptree::entry()
        .branch(
            Update::filter_message()
                .filter_command::<Command>()
                .endpoint(command_dispatcher),
        )
        .branch(
            Update::filter_message()
                .filter(|msg: Message| msg.photo().is_some() || msg.video().is_some())
                .endpoint(handle_media),
        );

    log::info!("Dispatcher configured, starting dispatch...");

    Dispatcher::builder(bot, handler)
        .enable_ctrlc_handler()
        .build()
        .dispatch()
        .await;
}
