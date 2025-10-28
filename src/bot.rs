use anyhow::Error;

use crate::{
    config::Config,
    handlers::{self, command::Command},
};
use teloxide::{dispatching::UpdateHandler, prelude::*, utils::command::BotCommands};

fn handler_tree() -> UpdateHandler<Error> {
    dptree::entry()
        .branch(handlers::command::branch())
        .branch(handlers::media::branch())
}

pub async fn run(config: &Config) {
    let bot = Bot::new(config.telegram.token.clone().unwrap());
    match bot.set_my_commands(Command::bot_commands()).await {
        Ok(_) => (),
        Err(e) => log::error!("Failed to set bot commands: {}", e),
    }

    log::info!("Dispatcher configured, starting dispatch...");

    Dispatcher::builder(bot, handler_tree())
        .default_handler(|upd| async move {
            log::warn!("Unhandled update: {:?}", upd);
        })
        .error_handler(LoggingErrorHandler::with_custom_text(
            "An error has occurred in the dispatcher",
        ))
        .enable_ctrlc_handler()
        .build()
        .dispatch()
        .await;
}
