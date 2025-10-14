use crate::error::Errors;
use std::path::PathBuf;
use teloxide::types::FileId;

use crate::handlers::search::search;
use crate::{files, transformers};
use anyhow::{Error, Result};

use teloxide::dispatching::UpdateHandler;
use teloxide::prelude::*;

async fn send_not_supported(bot: &Bot, msg: &Message) -> Result<()> {
    bot.send_message(msg.chat.id, "Not supported").await?;
    Ok(())
}

async fn send_error_message(bot: &Bot, msg: &Message) -> Result<()> {
    bot.send_message(msg.chat.id, "An error occurred").await?;
    Ok(())
}

async fn image_from_video(bot: &Bot, file_id: FileId, _: Option<String>) -> Result<PathBuf> {
    let filename = format!("{}.jpeg", file_id);
    let file_url = files::telegram::file_url(bot.get_file(file_id).await?.path.as_str()).await?;
    let download_path = files::local::download_path(filename);

    transformers::get_first_frame(file_url.as_str(), download_path)
}

async fn handle_image_file(
    bot: &Bot,
    file_id: FileId,
    extension: Option<String>,
) -> Result<PathBuf> {
    let downloaded_file =
        files::telegram::download_file(bot, file_id, extension.unwrap_or("jpeg".to_string()))
            .await?;
    Ok(downloaded_file)
}

#[derive(Debug)]
enum MediaType {
    Image,
    Video,
    Unknown,
}

async fn get_media_type(msg: &Message) -> Result<(MediaType, FileId, Option<String>)> {
    let (media_type, file_id, extension) = if let Some(photo) = &msg.photo() {
        (
            MediaType::Image,
            photo.last().unwrap().file.id.clone(),
            Some("jpeg".to_string()),
        )
    } else if let Some(video) = &msg.video() {
        (MediaType::Video, video.file.id.clone(), None)
    } else if let Some(animation) = &msg.animation() {
        (
            MediaType::Video,
            animation.file.id.clone(),
            Some("mp4".to_string()),
        )
    } else if let Some(video_note) = &msg.video_note() {
        (
            MediaType::Video,
            video_note.file.id.clone(),
            Some("mp4".to_string()),
        )
    } else if let Some(sticker) = &msg.sticker()
        && sticker.is_regular()
    {
        let (mt, ext) = if sticker.is_video() {
            (MediaType::Video, Some("mp4".to_string()))
        } else if sticker.is_static() {
            (MediaType::Image, Some("webp".to_string()))
        } else {
            (MediaType::Unknown, None)
        };

        (mt, sticker.file.id.clone(), ext)
    } else if let Some(document) = &msg.document() {
        let file = document;
        let ext = document
            .file_name
            .clone()
            .and_then(|name| name.rsplit_once('.').map(|(_, ext)| ext.to_string()));
        let guess = mime_guess::from_path(file.file_name.as_deref().unwrap_or(""));
        let mt = if let Some(mime_type) = guess.first() {
            match mime_type.type_().as_str() {
                "image" => match mime_type.subtype().as_str() {
                    "gif" => MediaType::Video,
                    _ => MediaType::Image,
                },
                "video" => MediaType::Video,
                _ => MediaType::Unknown,
            }
        } else {
            MediaType::Unknown
        };
        (mt, file.file.id.clone(), ext)
    } else {
        return Err(anyhow::anyhow!(Errors::MediaTypeNotSupported(
            "Unknown".to_string()
        )));
    };
    Ok((media_type, file_id, extension))
}

pub(crate) async fn handle_media_message(bot: Bot, msg: Message) -> Result<()> {
    log::info!("Received media in chat {}", msg.chat.id);
    let (media_type, file_id, extension) = get_media_type(&msg).await?;

    let downloaded_file = match media_type {
        MediaType::Image => handle_image_file(&bot, file_id, extension).await?,
        MediaType::Video => image_from_video(&bot, file_id, extension).await?,
        _ => {
            send_not_supported(&bot, &msg).await?;
            log::error!("Media with {extension:?} is not supported (id: {file_id})");
            return Err(anyhow::anyhow!(Errors::MediaTypeNotSupported(format!(
                "Media with {extension:?} is not supported (id: {file_id})"
            ))));
        }
    };

    let file_url = match files::get_file_url(downloaded_file).await {
        Ok(url) => url,
        Err(e) => {
            log::error!("Failed to get file url: {}", e);
            send_error_message(&bot, &msg).await?;
            return Err(e);
        }
    };

    search(&bot, &msg, &file_url).await?;

    Ok(())
}

pub(crate) fn filter_for_media_message(msg: Message) -> bool {
    msg.photo().is_some()
        || msg.video().is_some()
        || msg.document().is_some()
        || msg.sticker().is_some()
        || msg.animation().is_some()
}

pub(crate) fn branch() -> UpdateHandler<Error> {
    Update::filter_message()
        .filter(filter_for_media_message)
        .endpoint(handle_media_message)
}
