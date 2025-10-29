use crate::config::get_config;
use crate::models::{Enrichment, Episodes, SearchHit, Status, Title, Url};
use crate::providers::DataProvider;
use anilist_moe::client::AniListClient;
use anilist_moe::enums::media::MediaStatus;
use async_trait::async_trait;

#[derive(Clone)]
pub struct Anilist {
    client: AniListClient,
}

impl Anilist {
    pub fn new() -> Self {
        Self {
            client: AniListClient::new(),
        }
    }

    fn str_to_i32(&self, s: &str) -> Option<i32> {
        s.parse().ok()
    }

    fn extract_key(&self, hit: &SearchHit) -> Option<String> {
        let id = match hit.metadata.get("anilist_id") {
            Some(id) => match id {
                serde_json::Value::Number(number) => number.as_i64().map(|n| n.to_string()),
                serde_json::Value::String(string) => self.str_to_i32(string).map(|n| n.to_string()),
                _ => None,
            },
            None => None,
        };
        log::debug!("Extracted anilist id 3: {:?}", id);
        id
    }
}

#[async_trait]
impl DataProvider for Anilist {
    fn name(&self) -> &'static str {
        "AniList"
    }

    fn priority(&self) -> u8 {
        10
    }

    fn enabled(&self) -> bool {
        get_config().anilist.enabled.unwrap()
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        log::debug!("Checking if can enrich anilist: {:?}", hit);
        self.extract_key(hit).is_some()
    }

    async fn enrich(&self, hit: &SearchHit) -> anyhow::Result<Option<Enrichment>> {
        if let Some(string_id) = self.extract_key(hit) {
            log::debug!("Enriching anilist: {}", string_id);
            let id = self.str_to_i32(&string_id).unwrap();

            match self.client.anime().get_anime_by_id(id).await {
                Ok(anime) => {
                    let media = anime.data.media;
                    let title = match media.title {
                        Some(media_title) => Some(Title {
                            english: media_title.english,
                            romaji: media_title.romaji,
                            native: media_title.native,
                        }),
                        _ => None,
                    };

                    let data = Enrichment {
                        title,
                        episodes: Some(Episodes {
                            total: media.episodes.and_then(|x| u32::try_from(x).ok()),
                            ..Default::default()
                        }),
                        thumbnail: media.cover_image.and_then(|x| x.extra_large),
                        tags: Some(
                            media
                                .tags
                                .unwrap_or_default()
                                .into_iter()
                                .filter_map(|tag| tag.name)
                                .collect(),
                        ),

                        main_url: Some(Url {
                            url: media.site_url,
                        }),
                        urls: Some(
                            media
                                .external_links
                                .unwrap_or_default()
                                .into_iter()
                                .filter(|x| x.url.is_some())
                                .map(|link| Url { url: link.url })
                                .collect(),
                        ),
                        year: media.season_year.and_then(|x| x.try_into().ok()),
                        status: media.status.map(|status| match status {
                            MediaStatus::Finished => Status::Completed,
                            MediaStatus::Releasing => Status::Ongoing,
                            MediaStatus::NotYetReleased => Status::Announced,
                            MediaStatus::Cancelled => Status::Cancelled,
                            MediaStatus::Hiatus => Status::OnHold,
                        }),
                        priority: self.priority(),
                        enrichers: std::collections::HashSet::from([self.name().to_string()]),
                        ..Default::default()
                    };

                    Ok(Some(data))
                }
                Err(e) => {
                    log::debug!("Error in Anilist API: {}", e);
                    Err(Box::new(e).into())
                }
            }
        } else {
            log::info!("No anilist id found");
            Ok(None)
        }
    }
}
