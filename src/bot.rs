use crate::handlers;
use teloxide::{dispatching::UpdateHandler, prelude::*};

pub fn handler_tree() -> UpdateHandler<teloxide::RequestError> {
    dptree::entry()
        .branch(handlers::command::branch())
        .branch(handlers::media::branch())
}

pub async fn run() {
    let bot = Bot::from_env();

    log::info!("Dispatcher configured, starting dispatch...");

    Dispatcher::builder(bot, handler_tree())
        .enable_ctrlc_handler()
        .build()
        .dispatch()
        .await;
}
