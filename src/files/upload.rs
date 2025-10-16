use anyhow::Result;
use reqwest::multipart::{Form, Part};

use crate::config::get_config;

async fn upload_to_rustypaste(
    base_url: &str,
    auth_token: Option<&str>,
    file_path: &str,
    expiry: Option<&str>,
) -> Result<String> {
    let client = reqwest::Client::new();

    let mut request = client
        .post(base_url)
        .multipart(Form::new().part("file", Part::file(file_path).await?));

    if let Some(token) = auth_token {
        request = request.header("Authorization", token);
    }

    if let Some(expiry) = expiry {
        request = request.header("expire", expiry);
    }

    let res = match request.send().await {
        Ok(res) => res,
        Err(err) => {
            log::error!("Failed to upload file to Rustypaste: {}", err);
            return Err(anyhow::anyhow!(
                "Failed to upload file to Rustypaste: {}",
                err
            ));
        }
    };

    res.error_for_status_ref().map_err(|err| {
        log::error!("Failed to upload file to Rustypaste: {}", err);
        anyhow::anyhow!("Failed to upload file to Rustypaste: {}", err)
    })?;

    let uploaded_url = res.text().await?.trim().to_string();

    log::info!("File uploaded to Rustypaste: {}", uploaded_url);

    Ok(uploaded_url)
}

pub(crate) async fn upload(file_path: &str) -> Result<String> {
    let config = get_config();

    if let Some(base_url) = &config.rustypaste.url {
        log::info!("Uploading file {}", file_path);

        upload_to_rustypaste(
            base_url.as_str(),
            config.rustypaste.token.as_deref(),
            file_path,
            config.rustypaste.expiry.as_deref(),
        )
        .await
    } else {
        log::warn!("Rustypaste base URL is not set in config");
        Err(anyhow::anyhow!("Rustypaste base URL is not set in config"))
    }
}
