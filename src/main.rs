mod bot;
mod error;
mod handlers;
mod types;
mod utils;

#[tokio::main]
async fn main() {
    pretty_env_logger::init();
    log::info!("Starting bot...");

    bot::run().await;

    log::info!("Bot stopped");
}
