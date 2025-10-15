use serde::{Deserialize, Serialize};
use std::collections::HashSet;

use crate::transformers::Service;

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct Episodes {
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
pub struct Chapters {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hit: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hit_image: Option<String>,
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

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct Url {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

impl Url {
    pub fn name(&self, with_emoji: bool) -> String {
        let service = self.url.as_ref().map(|url| Service::from_url(url));

        let name = if let Some(name) = &self.name {
            name.clone()
        } else if let Some(service) = &service {
            service.name()
        } else {
            "Link".to_string()
        };

        if with_emoji {
            if let Some(service) = service {
                format!("{} {}", service.emoji(), name)
            } else {
                format!("{} {}", '🔗', name)
            }
        } else {
            name
        }
    }

    pub fn clean_url(&self) -> Option<String> {
        match &self.url {
            Some(url) => match Service::parse_url(url) {
                Some((service, id)) => service.build_url(id.as_str()).or(self.url.clone()),
                None => self.url.clone(),
            },
            None => self.url.clone(),
        }
    }
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
pub struct Enrichment {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<Title>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub year: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<HashSet<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status: Option<Status>,

    pub artists: Option<HashSet<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub characters: Option<HashSet<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thumbnail: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub video: Option<String>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub episodes: Option<Episodes>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chapters: Option<Chapters>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub main_url: Option<Url>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub urls: Option<Vec<Url>>,

    pub priority: u8,
    pub enrichers: HashSet<String>,
}
