mod bot;
mod config;
mod error;
mod handlers;
mod types;
mod utils;

#[tokio::main]
async fn main() {
    pretty_env_logger::init();

    let config = config::get_config();

    if config.token.is_empty() {
        log::error!(
            "Set Telegram token with `--token`, `-t` or `RIS_TELEGRAM_TOKEN` env var or in config file"
        );
        std::process::exit(1);
    }

    log::info!("Starting bot...");
    bot::run(config).await;
    log::info!("Bot stopped");
}
