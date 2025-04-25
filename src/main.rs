use teloxide::{net::Download, prelude::*, types::FileMeta, utils::command::BotCommands};
use thiserror::Error;
use tokio::fs;

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

async fn answer(bot: Bot, msg: Message, cmd: Command) -> ResponseResult<()> {
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

#[derive(Error, Debug)]
pub enum DownloadError {
    /// An error occurred while making an API request to Telegram
    #[error("Telegram API request error: {0}")]
    Request(#[from] teloxide::RequestError),

    /// An I/O error occurred during local file setup (creating the dest file)
    #[error("File setup I/O error: {0}")]
    FileSetup(#[from] std::io::Error),

    // A error occurred during the file download itself.
    #[error("File download error: {0}")]
    Download(#[from] teloxide::DownloadError),
}

async fn download_file(
    bot: &Bot,
    file_meta: &FileMeta,
) -> Result<std::path::PathBuf, DownloadError> {
    let file = bot.get_file(&file_meta.id).await?;
    let filename = format!("{}.jpg", file_meta.id);

    let path = output_directory().join(filename);
    let mut dest = fs::File::create(&path).await?;

    bot.download_file(&file.path, &mut dest).await?;

    Ok(path)
}

async fn handle_media(bot: Bot, msg: Message) -> ResponseResult<()> {
    let chat_id = msg.chat.id;

    if let Some(photo_size) = msg.photo() {
        log::info!("Received Photo in chat {}", chat_id);
        bot.send_message(chat_id, "Received Photo").await?;

        if let Some(photo) = photo_size.last() {
            let file_id = &photo.file.id;
            log::info!("File ID: {}", file_id);

            match download_file(&bot, &photo.file).await {
                Ok(dest) => {
                    log::info!("File ID: {} downloaded to {}", file_id, dest.display());
                }
                Err(err) => {
                    log::error!("Failed to download/save file ID {}: {}", file_id, err);

                    if let DownloadError::Request(req_err) = err {
                        return Err(req_err);
                    } else {
                        bot.send_message(
                            chat_id,
                            "Oh no, something went wrong while trying to save the photo.",
                        )
                        .await?;
                    }
                }
            }
        }
    } else if msg.video().is_some() {
        log::info!("Received Video in chat {}", chat_id);
        bot.send_message(chat_id, "Received Video").await?;
    } else {
        log::warn!("handle_media called with unexpected message");
    }

    Ok(())
}

fn output_directory() -> std::path::PathBuf {
    let cwd = std::env::current_dir().unwrap();
    let dir = cwd.join("output");
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[tokio::main]
async fn main() {
    pretty_env_logger::init();
    log::info!("Starting bot...");

    let bot = Bot::from_env();

    let handler = dptree::entry()
        .branch(
            Update::filter_message()
                .filter_command::<Command>()
                .endpoint(answer),
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

    log::info!("Bot stopped");
}
