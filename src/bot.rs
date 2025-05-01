use std::error::Error;

use crate::handlers;
use teloxide::{dispatching::UpdateHandler, prelude::*};

pub fn handler_tree() -> UpdateHandler<Box<dyn Error + Send + Sync + 'static>> {
    dptree::entry()
        .branch(handlers::command::branch())
        .branch(handlers::media::branch())
}

pub async fn run() {
    let bot = Bot::from_env();

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
