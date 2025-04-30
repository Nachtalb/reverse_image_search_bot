use crate::error::DownloadError;
use crate::utils::file::output_directory;

use teloxide::{net::Download, prelude::*, types::FileMeta};
use tokio::fs;

pub async fn download_file(
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
