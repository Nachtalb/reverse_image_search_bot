use thiserror::Error;

#[derive(Error, Debug)]
pub enum Errors {
    /// An error occurred while making an API request to Telegram
    #[error("Telegram API request error: {0}")]
    Request(#[from] teloxide::RequestError),

    /// An I/O error occurred during local file setup (creating the dest file)
    #[error("File setup I/O error: {0}")]
    FileSetup(#[from] std::io::Error),

    /// A error occurred during the file download itself.
    #[error("File download error: {0}")]
    Download(#[from] teloxide::DownloadError),

    /// Media type is not supported
    #[error("Media type not supported: {0}")]
    MediaTypeNotSupported(String),

    /// Failed to retrieve first frame from file
    #[error("Failed to get first frame: {0}")]
    FailedToGetFirstFrame(String),
}
