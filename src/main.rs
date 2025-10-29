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

use std::thread;
use tokio::runtime::Builder;

#[macro_use]
extern crate rust_i18n;
i18n!();

fn main() {
    pretty_env_logger::init();
    let config = config::get_config();
    log::info!("Starting bot...");

    let num_threads = match config.general.worker_num {
        None => thread::available_parallelism()
            .map_or(1usize, usize::from)
            .saturating_mul(2),
        Some(num) => num,
    };

    log::info!("Using {} threads", num_threads);

    let rt = Builder::new_multi_thread()
        .worker_threads(num_threads)
        .enable_all()
        .build()
        .unwrap();

    rt.block_on(bot::run(config));
    log::info!("Bot stopped");
}
