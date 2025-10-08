use opencv::prelude::*;
use opencv::{core, imgcodecs, videoio};
use std::error::Error;

pub fn first_frame(
    video_path_or_url: &str,
    dest_path: &str,
) -> Result<(), Box<dyn Error + Send + Sync + 'static>> {
    let mut video = match videoio::VideoCapture::from_file_def(video_path_or_url) {
        Ok(v) => v,
        Err(e) => {
            log::error!("Failed to open video: {}", e);
            return Err(Box::new(e));
        }
    };

    let mut frame = core::Mat::default();
    if let Err(e) = video.read(&mut frame) {
        log::error!("Failed to read frame: {}", e);
        return Err(Box::new(e));
    };

    imgcodecs::imwrite(dest_path, &frame, &core::Vector::new())?;
    Ok(())
}
