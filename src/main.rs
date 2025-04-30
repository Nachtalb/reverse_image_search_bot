mod bot;
mod error;
mod handlers;
mod utils;

// use teloxide::{net::Download, prelude::*, types::FileMeta, utils::command::BotCommands};

#[tokio::main]
async fn main() {
    pretty_env_logger::init();
    log::info!("Starting bot...");

    bot::run().await;

    log::info!("Bot stopped");
}
