use anyhow::{Error, Result};
use img_hash::HasherConfig;

pub(crate) fn get_image_hash(path: &str) -> Result<Vec<u8>> {
    log::info!("Getting hash for image {}", path);
    let image = match image::open(path) {
        Ok(image) => image,
        Err(e) => {
            log::error!("Failed to open image {}: {}", path, e);
            return Err(Error::from(e));
        }
    };

    let hasher = HasherConfig::new().preproc_dct().to_hasher();

    Ok(hasher.hash_image(&image).as_bytes().to_vec())
}
