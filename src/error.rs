use thiserror::Error;

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
