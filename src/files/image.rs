use anyhow::{Error, Result};
use img_hash::HasherConfig;

pub(crate) async fn get_image_hash(path: &str) -> Result<Vec<u8>> {
    let path = path.to_string();
    tokio::task::spawn_blocking(move || {
        log::info!("Getting hash for image {}", path);
        let image = match image::open(path.as_str()) {
            Ok(image) => image,
            Err(e) => {
                log::error!("Failed to open image {}: {}", path, e);
                return Err(Error::from(e));
            }
        };

        let hasher = HasherConfig::new().preproc_dct().to_hasher();

        Ok(hasher.hash_image(&image).as_bytes().to_vec())
    })
    .await?
}
