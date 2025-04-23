use teloxide::{
    RequestError, net::Download, prelude::*, types::FileMeta, utils::command::BotCommands,
};
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

async fn download_file(bot: Bot, file_meta: &FileMeta) -> Result<std::path::PathBuf, RequestError> {
    let file = bot.get_file(&file_meta.id).await?;
    let filename = format!("{}.jpg", file_meta.id);

    let path = output_directory().join(filename);
    let mut dest = fs::File::create(&path).await.map_err(|io_error| {
        // Map the error if await resulted in Err
        log::error!(
            "Failed to create file asynchronously '{}': {}",
            path.display(),
            io_error
        );
        RequestError::Io(std::sync::Arc::new(io_error)) // Convert to RequestError::Io
    })?; // ? now operates on Result<File, RequestError>

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

            let dest = download_file(bot, &photo.file).await?;
            log::info!("File ID: {} downloaded to {}", file_id, dest.display());
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
