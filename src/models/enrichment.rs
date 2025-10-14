use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum Enrichment {
    Anime(Box<AnimeData>),
    Manga(Box<MangaData>),
    Fanart(Box<FanartData>),
    Generic(Box<GenericData>),
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct Enriched {
    pub anime: Option<Box<AnimeData>>,
    pub manga: Option<Box<MangaData>>,
    pub fanart: Option<Box<FanartData>>,
    pub generic: Option<Box<GenericData>>,
}

impl Enriched {
    pub fn any(&self) -> bool {
        self.anime.is_some()
            || self.manga.is_some()
            || self.fanart.is_some()
            || self.generic.is_some()
    }
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct EpisodesData {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hit: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hit_timestamp: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hit_image: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hit_video: Option<String>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct Title {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub english: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub romaji: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub native: Option<String>,
}

impl Title {
    pub fn title(&self) -> Option<String> {
        self.english
            .clone()
            .or(self.romaji.clone())
            .or(self.native.clone())
    }
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct Url {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

#[derive(strum_macros::Display, Clone, Debug, Serialize, Deserialize)]
pub enum Status {
    Announced,
    Ongoing,
    OnHold,
    Completed,
    Cancelled,
    Unknown,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct AnimeData {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<Title>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub episodes: Option<EpisodesData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<HashSet<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cover: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<Status>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub main_url: Option<Url>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub urls: Option<Vec<Url>>,

    pub enrichers: HashSet<String>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct ChaptersData {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hit: Option<u32>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct MangaData {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<Title>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chapters: Option<ChaptersData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<HashSet<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub cover: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<Status>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<u16>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub main_url: Option<Url>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub urls: Option<Vec<Url>>,

    pub enrichers: HashSet<String>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct FanartData {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<Title>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub artist: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub characters: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<HashSet<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thumbnail: Option<String>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub main_url: Option<Url>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub urls: Option<Vec<Url>>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub anime: Option<AnimeData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub manga: Option<MangaData>,

    pub enrichers: HashSet<String>,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct GenericData {
    pub key_values: HashMap<String, serde_json::Value>,
}
