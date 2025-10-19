mod bot;
mod cli;
mod config;
mod core;
mod display;
mod engines;
mod error;
mod files;
mod handlers;
mod models;
mod providers;
mod redis;
mod transformers;
mod utils;

#[tokio::main]
async fn main() {
    pretty_env_logger::init();

    let config = config::get_config();

    log::info!("Starting bot...");
    bot::run(config).await;
    log::info!("Bot stopped");
}
