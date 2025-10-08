use std::env;

use crate::error::DownloadError;

use teloxide::{net::Download, prelude::*, types::FileMeta};
use tokio::fs;

pub async fn file_url(bot: &Bot, file_meta: &FileMeta) -> Result<reqwest::Url, DownloadError> {
    let file = bot.get_file(file_meta.id.clone()).await?;
    let file_path = file.path;

    let token = env::var("TELOXIDE_TOKEN").expect("TELOXIDE_TOKEN must be set");
    let mut url = reqwest::Url::parse(teloxide::net::TELEGRAM_API_URL).unwrap();

    {
        let mut segments = url
            .path_segments_mut()
            .expect("base url cannot be a cannot-be-a-base");
        segments.push("file");
        segments.push(&format!("bot{token}"));
        segments.push(file_path.as_str());
    }

    Ok(url)
}

pub fn output_directory() -> std::path::PathBuf {
    let cwd = std::env::current_dir().unwrap();
    let dir = cwd.join("output");
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

pub fn file_path(file_meta: &FileMeta) -> std::path::PathBuf {
    let filename = format!("{}.jpg", file_meta.id);
    output_directory().join(filename)
}

pub async fn download_file(
    bot: &Bot,
    file_meta: &FileMeta,
) -> Result<std::path::PathBuf, DownloadError> {
    let file = bot.get_file(file_meta.id.clone()).await?;
    let path = file_path(file_meta);

    let mut dest = fs::File::create(&path).await?;

    bot.download_file(&file.path, &mut dest).await?;

    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn creates_output_directory() {
        let dir = output_directory();
        assert!(dir.ends_with("output"));
        assert!(dir.exists());
        assert!(dir.is_dir());

        // Cleanup
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn idempotent_output_directory() {
        let first = output_directory();
        let second = output_directory();
        assert_eq!(first, second);

        // Cleanup
        fs::remove_dir_all(&first).unwrap();
    }
}
