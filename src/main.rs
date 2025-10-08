mod bot;
mod error;
mod handlers;
mod types;
mod utils;

#[tokio::main]
async fn main() {
    pretty_env_logger::init();
    log::info!("Starting bot...");

    if std::env::var("TELOXIDE_TOKEN").is_err() {
        log::error!("TELOXIDE_TOKEN not set");
        std::process::exit(1);
    }

    bot::run().await;

    log::info!("Bot stopped");
}
