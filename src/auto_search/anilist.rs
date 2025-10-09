use std::error::Error;

use anilist_moe::client::AniListClient;
use anilist_moe::objects::media::Media;
use tokio::sync::OnceCell;

static CLIENT: OnceCell<AniListClient> = OnceCell::const_new();

async fn get_client() -> &'static AniListClient {
    if !CLIENT.initialized() {
        let client = AniListClient::new();
        CLIENT.set(client).unwrap();
    }
    CLIENT.get().unwrap()
}

pub(crate) async fn get_anime(id: i32) -> Result<Media, Box<dyn Error + Send + Sync + 'static>> {
    let client = get_client().await;
    match client.anime().get_anime_by_id(id).await {
        Ok(anime) => Ok(anime.data.media),
        Err(e) => Err(Box::new(e)),
    }
}

pub(crate) fn text(anime: &Media, episode: Option<u32>) -> String {
    let mut lines = Vec::new();

    if let Some(title) = &anime.title {
        if let Some(english) = &title.english {
            lines.push(format!("Title: `{}`", english));
        }
        if let Some(romaji) = &title.romaji {
            lines.push(format!("Title [romaji]: `{}`", romaji));
        }
    }

    if let Some(episodes) = &anime.episodes {
        lines.push(if let Some(ep) = episode {
            format!("Episode: `{}/{}`", ep, episodes)
        } else {
            format!("Episodes: `{}`", episodes)
        });
    }

    if let Some(format) = &anime.format {
        lines.push(format!(
            "Format: `{}`",
            serde_json::to_string(format).unwrap().replace("\"", "")
        ));
    }

    if let Some(status) = &anime.status {
        lines.push(format!(
            "Status: `{}`",
            serde_json::to_string(status).unwrap().replace("\"", "")
        ));
    }

    if let Some(season_year) = &anime.season_year
        && let Some(season) = &anime.season
    {
        lines.push(format!(
            "Season: `{}` `{}`",
            season_year,
            serde_json::to_string(season).unwrap().replace("\"", "")
        ));
    }

    if let Some(is_adult) = &anime.is_adult {
        lines.push(format!(
            "18\\+ Audience: `{}`",
            if *is_adult { "Yes" } else { "No" }
        ));
    }

    if let Some(tags) = &anime.tags {
        let tags = tags
            .iter()
            .take(5)
            .map(|tag| format!("\\#{}", tag.name.clone().unwrap().replace(" ", "")))
            .collect::<Vec<String>>()
            .join(", ");
        lines.push(format!("Tags: {}", tags));
    }

    lines.join("\n")
}
