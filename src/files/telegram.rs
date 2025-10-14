use crate::{config::get_config, error::Errors};

use teloxide::{net::Download, prelude::*, types::FileId};

use crate::files::local;
use tokio::fs;

pub(crate) async fn file_url(path: &str) -> Result<reqwest::Url, Errors> {
    let token = &get_config().token;
    let mut url = reqwest::Url::parse(teloxide::net::TELEGRAM_API_URL).unwrap();

    {
        let mut segments = url
            .path_segments_mut()
            .expect("base url cannot be a cannot-be-a-base");
        segments.push("file");
        segments.push(&format!("bot{token}"));
        segments.push(path);
    }

    Ok(url)
}

pub(crate) async fn download_file(
    bot: &Bot,
    file_id: FileId,
    file_extension: String,
) -> Result<std::path::PathBuf, Errors> {
    let filename = format!("{}.{}", file_id, file_extension);
    let file = bot.get_file(file_id).await?;

    let path = local::download_path(filename);
    let mut dest = fs::File::create(&path).await?;

    bot.download_file(&file.path, &mut dest).await?;

    Ok(path)
}
