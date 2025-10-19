use std::path::PathBuf;

use anyhow::Result;

pub(crate) mod image;
pub(crate) mod local;
pub(crate) mod telegram;
pub(crate) mod upload;

use upload::upload;

pub(crate) async fn get_file_url(file: PathBuf) -> Result<String> {
    upload(file.to_str().unwrap()).await
}
