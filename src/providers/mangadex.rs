use std::collections::{HashMap, HashSet};

use crate::models::{Chapters, Enrichment, SearchHit, Status, Title, Url};
use crate::providers::DataProvider;
use crate::transformers::Service;
use anyhow::Result;
use async_trait::async_trait;
use reqwest::header::HeaderMap;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
static APP_USER_AGENT: &str = concat!(env!("CARGO_PKG_NAME"), "/", env!("CARGO_PKG_VERSION"),);

#[derive(Serialize, Deserialize)]
struct Response {
    result: String,
    response: Option<String>,
    #[serde(deserialize_with = "deserialize_entity")]
    data: Option<Entity>,
    error: Option<ApiError>,
}

#[derive(Serialize, Deserialize)]
struct ApiError {
    status: u16,
    detail: String,
}

#[derive(Serialize, Deserialize)]
enum Entity {
    Manga(Manga),
    Chapter(Chapter),
}

fn deserialize_entity_from_value(value: Value) -> Result<Entity> {
    let type_str = value["type"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("missing field `type`"))?;

    match type_str {
        "manga" => {
            let manga: Manga = serde_json::from_value(value)?;
            Ok(Entity::Manga(manga))
        }
        "chapter" => {
            let chapter: Chapter = serde_json::from_value(value)?;
            Ok(Entity::Chapter(chapter))
        }
        _ => Err(anyhow::anyhow!(
            "unknown variant `{type_str}`, expected `manga` or `chapter`"
        )),
    }
}

fn deserialize_entity<'de, D>(deserializer: D) -> Result<Option<Entity>, D::Error>
where
    D: Deserializer<'de>,
{
    let value: Value = Value::deserialize(deserializer)?;
    match deserialize_entity_from_value(value) {
        Ok(entity) => Ok(Some(entity)),
        Err(err) => Err(serde::de::Error::custom(err)),
    }
}

fn manga_from_relationships<'de, D>(deserializer: D) -> Result<Option<Manga>, D::Error>
where
    D: Deserializer<'de>,
{
    let values: Vec<Value> = Vec::deserialize(deserializer)?;
    match values
        .into_iter()
        .map(deserialize_entity_from_value)
        .filter_map(|res| match res {
            Ok(Entity::Manga(manga)) => Some(manga),
            _ => None,
        })
        .next()
    {
        Some(manga) => Ok(Some(manga)),
        None => Err(serde::de::Error::custom("No manga found")), // Should never happen
    }
}

#[derive(Serialize, Deserialize)]
struct Manga {
    id: String,
    attributes: MangaInfo,
}

#[derive(Serialize, Deserialize)]
struct Chapter {
    id: String,
    attributes: ChapterInfo,
    #[serde(
        rename = "relationships",
        deserialize_with = "manga_from_relationships"
    )]
    manga: Option<Manga>,
}

#[derive(Serialize, Deserialize)]
struct ChapterInfo {
    chapter: Option<String>,
    title: String,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MangaInfo {
    title: HashMap<String, String>,
    alt_titles: Vec<HashMap<String, String>>,
    links: HashMap<String, String>,
    official_links: Option<HashMap<String, String>>,
    last_chapter: Option<String>,
    status: String,
    year: Option<u16>,
    tags: Vec<Tag>,
    original_language: String,
}

#[derive(Serialize, Deserialize)]
struct Tag {
    attributes: TagAttributes,
}

#[derive(Serialize, Deserialize)]
struct TagAttributes {
    name: HashMap<String, String>,
}

#[derive(Clone)]
pub struct MangaDex {
    client: reqwest::Client,
}

impl MangaDex {
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder()
                .user_agent(APP_USER_AGENT)
                .build()
                .unwrap(),
        }
    }

    fn id_map(sn_id: &str) -> &str {
        match sn_id {
            "al" => "anilist",
            "mal" => "myanimelist",
            "mu" => "mangaupdates",
            "kt" => "kitsu",
            "ap" => "anime-planet",
            "bw" => "bookwalker",
            _ => sn_id,
        }
    }

    async fn enrich_manga(
        &self,
        hit: &SearchHit,
        manga: &Manga,
        chapter: Option<&Chapter>,
    ) -> Option<Enrichment> {
        let native_lang = &manga.attributes.original_language;
        let all_titles =
            std::iter::once(&manga.attributes.title).chain(manga.attributes.alt_titles.iter());
        let title = Title {
            english: all_titles
                .clone()
                .filter_map(|t| t.get("en").cloned())
                .next(),
            romaji: all_titles
                .clone()
                .filter_map(|t| t.get("rj").cloned())
                .next(),
            native: all_titles
                .filter_map(|t| t.get(native_lang).cloned())
                .next(),
        };

        let mut links: HashMap<String, String> = manga.attributes.links.clone();
        if let Some(official_links) = &manga.attributes.official_links {
            links.extend(official_links.clone());
        }

        let mut urls: HashSet<Url> = HashSet::new();
        let main_url: Option<Url> = Some(Url {
            url: Service::MangaDex.build_url(&manga.id),
        });

        for link in links.iter() {
            let service = Service::from_string(Self::id_map(link.0.as_str()))
                .unwrap_or_else(|| Service::from_url(link.1));

            if let Service::Unknown(_) = service
                && !link.1.starts_with("http")
            {
                continue;
            }

            urls.insert(Url {
                url: service.build_url(link.1),
            });
        }

        let chapters = chapter.map(|chapter| Chapters {
            total: manga
                .attributes
                .last_chapter
                .clone()
                .and_then(|c| c.parse().ok()),
            hit: chapter
                .attributes
                .chapter
                .clone()
                .and_then(|c| c.parse().ok()),
            ..Default::default()
        });

        let status = match manga.attributes.status.as_str() {
            "completed" => Status::Completed,
            "ongoing" => Status::Ongoing,
            "cancelled" => Status::Cancelled,
            "hiatus" => Status::OnHold,
            _ => Status::Unknown,
        };

        let tags: HashSet<String> = manga
            .attributes
            .tags
            .iter()
            .filter_map(|tag| tag.attributes.name.values().next().cloned())
            .collect();

        Some(Enrichment {
            title: Some(title),
            main_url,
            urls: Some(urls),
            year: manga.attributes.year,
            chapters,
            tags: Some(tags),
            status: Some(status),
            thumbnail: hit.thumbnail.clone(),
            enrichers: std::collections::HashSet::from([String::from(self.name())]),
            priority: self.priority(),
            ..Default::default()
        })
    }
}

#[async_trait]
impl DataProvider for MangaDex {
    fn name(&self) -> &'static str {
        "MangaDex"
    }

    fn priority(&self) -> u8 {
        10
    }

    fn enabled(&self) -> bool {
        true
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        hit.metadata.contains_key("mangadex") || hit.metadata.contains_key("mangadex-chapter")
    }

    async fn enrich(&self, hit: &SearchHit) -> Result<Option<Enrichment>> {
        let mut headers = HeaderMap::new();
        headers.insert("Accept", "application/json".parse().unwrap());

        let mut url = "https://api.mangadex.org".to_string();
        if let Some(manga_id) = hit.metadata.get("mangadex") {
            log::debug!("manga_id: {manga_id}");
            url = format!("{url}/manga/{}", manga_id.as_str().unwrap());
        } else if let Some(chapter_id) = hit.metadata.get("mangadex-chapter") {
            log::debug!("chapter_id: {chapter_id}");
            url = format!("{url}/chapter/{}", chapter_id.as_str().unwrap());
        } else {
            log::warn!("No manga_id or chapter_id found");
            return Ok(None);
        }

        let body = self
            .client
            .get(url)
            .query(&[("includes[]", "manga")])
            .headers(headers)
            .send()
            .await?
            .error_for_status()?
            .text()
            .await?;

        let response: Response = serde_json::from_str(&body).map_err(|e| {
            log::error!("Serde JSON decode error: {}", e);
            log::error!("Affected json: {}", body);
            e
        })?;

        if let Some(error) = response.error {
            return Err(anyhow::anyhow!(format!(
                "{}: {}",
                error.status, error.detail
            )));
        }

        match response.data {
            Some(Entity::Manga(manga)) => Ok(self.enrich_manga(hit, &manga, None).await),
            Some(Entity::Chapter(chapter)) => {
                match &chapter.manga {
                    Some(manga) => Ok(self.enrich_manga(hit, manga, Some(&chapter)).await),
                    _ => Err(anyhow::anyhow!("No manga found")), // Should never happen
                }
            }
            None => Err(anyhow::anyhow!("No data found")),
        }
    }
}
