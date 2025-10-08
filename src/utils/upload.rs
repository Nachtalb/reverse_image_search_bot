use reqwest::multipart::{Form, Part};
use std::error::Error;

use crate::config::get_config;

pub async fn upload_to_rustypaste(
    base_url: &str,
    auth_token: Option<&str>,
    file_path: &str,
    expiry: Option<&str>,
) -> Result<String, Box<dyn Error + Send + Sync + 'static>> {
    let client = reqwest::Client::new();

    let mut request = client
        .post(base_url)
        .multipart(Form::new().part("file", Part::file(file_path).await?));

    if let Some(token) = auth_token {
        request = request.header("Authorization", token);
    }

    let res = request.send().await?;
    let uploaded_url = res.text().await?.trim().to_string();

    log::info!("File uploaded to Rustypaste: {}", uploaded_url);

    Ok(uploaded_url)
}

pub(crate) async fn upload(
    file_path: &str,
) -> Result<String, Box<dyn Error + Send + Sync + 'static>> {
    let config = get_config();

    if let Some(base_url) = &config.rustypaste_base_url {
        log::info!("Uploading file {} to Rustypaste", file_path);

        return upload_to_rustypaste(
            base_url.as_str(),
            config.rustypaste_token.as_deref(),
            file_path,
            config.rustypaste_expiry.as_deref(),
        )
        .await;
    }

    Err("Rustypaste base URL is not set in config".into())
}
