use crate::error::Errors;
use anyhow::Result;
use opencv::prelude::*;
use opencv::{core, imgcodecs, videoio};
use std::path::PathBuf;

pub(crate) fn get_first_frame(video_path_or_url: &str, dest_path: PathBuf) -> Result<PathBuf> {
    let mut video = match videoio::VideoCapture::from_file_def(video_path_or_url) {
        Ok(v) => v,
        Err(e) => {
            log::error!("Failed to open video: {}", e);
            return Err(anyhow::anyhow!(Errors::FailedToGetFirstFrame(
                e.to_string()
            )));
        }
    };

    let mut frame = core::Mat::default();
    if let Err(e) = video.read(&mut frame) {
        log::error!("Failed to read frame: {}", e);
        return Err(anyhow::anyhow!(Errors::FailedToGetFirstFrame(
            e.to_string()
        )));
    };

    let str_path = match dest_path.to_str() {
        Some(p) => p,
        None => {
            log::error!("Failed to get path");
            return Err(anyhow::anyhow!(Errors::FailedToGetFirstFrame(
                "Failed to get path".to_string()
            )));
        }
    };

    imgcodecs::imwrite(str_path, &frame, &core::Vector::new())?;
    Ok(dest_path)
}
