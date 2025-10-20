use std::sync::Arc;

use crate::config::get_config;
use crate::models::{Enrichment, SearchHit, Url};
use crate::providers::DataProvider;
use crate::transformers::Service;
use async_trait::async_trait;
use booru::Client;
use booru::danbooru::DanbooruClient;
use booru::gelbooru::GelbooruClient;
use booru::safebooru::SafebooruClient;

#[derive(Clone)]
pub struct Danbooru {
    client: Arc<DanbooruClient>,
}

#[derive(Clone)]
pub struct Gelbooru {
    client: Arc<GelbooruClient>,
}

#[derive(Clone)]
pub struct Safebooru {
    client: Arc<SafebooruClient>,
}

impl Danbooru {
    pub fn new() -> Self {
        let config = get_config();
        let client = if let Some(token) = &config.danbooru.token
            && let Some(username) = &config.danbooru.username
        {
            DanbooruClient::builder()
                .set_credentials(token.clone(), username.clone())
                .build()
        } else {
            DanbooruClient::builder().build()
        };

        Self {
            client: Arc::new(client),
        }
    }
}

impl Gelbooru {
    pub fn new() -> Self {
        Self {
            client: Arc::new(GelbooruClient::builder().build()),
        }
    }
}

impl Safebooru {
    pub fn new() -> Self {
        Self {
            client: Arc::new(SafebooruClient::builder().build()),
        }
    }
}

fn str_to_u32(s: &str) -> Option<u32> {
    s.parse().ok()
}

fn extract_key(hit: &SearchHit, name: &str) -> Option<String> {
    let string_id = &name.to_lowercase();
    let raw_value = hit
        .metadata
        .get(string_id)
        .or(hit.metadata.get(format!("{}_id", string_id).as_str()));

    let id = match raw_value {
        Some(value) => match value {
            serde_json::Value::Number(number) => number.as_u64().map(|n| n.to_string()),
            serde_json::Value::String(string) => str_to_u32(string).map(|n| n.to_string()),
            _ => None,
        },
        None => None,
    };
    log::debug!("Extracted {} id 3: {:?}", name, id);
    id
}

#[async_trait]
impl DataProvider for Danbooru {
    fn name(&self) -> &'static str {
        "danbooru"
    }

    fn priority(&self) -> u8 {
        10
    }

    fn enabled(&self) -> bool {
        get_config().danbooru.enabled.unwrap()
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        log::debug!("Checking if can enrich {}: {:?}", self.name(), hit);
        extract_key(hit, self.name()).is_some()
    }

    async fn enrich(&self, hit: &SearchHit) -> anyhow::Result<Option<Enrichment>> {
        if let Some(string_id) = extract_key(hit, self.name()) {
            log::debug!("Enriching {}: {}", self.name(), string_id);
            let id = str_to_u32(&string_id).unwrap();

            match self.client.get_by_id(id).await {
                Ok(post) => {
                    let image_not_public = post.is_deleted
                        || post.is_banned
                        || (post.tag_string_general.contains(" loli ")
                            || post.tag_string_general.ends_with(" loli")
                            || post.tag_string_general.starts_with("loli "));

                    let video = if !image_not_public {
                        match post.file_ext.as_str() {
                            "gif" | "mp4" | "webm" => post.file_url.clone(),
                            _ => None,
                        }
                    } else {
                        None
                    };

                    let thumbnail = if !image_not_public {
                        match post.file_ext.as_str() {
                            "jpg" | "jpeg" | "png" | "webp" => post
                                .file_url
                                .or(post.large_file_url.or(post.preview_file_url)),
                            _ => None,
                        }
                    } else {
                        None
                    };

                    let data = Enrichment {
                        thumbnail,
                        video,
                        tags: Some(
                            post.tag_string_general
                                .split(' ')
                                .map(|x| x.to_string())
                                .collect(),
                        ),
                        artists: Some(
                            post.tag_string_artist
                                .split(' ')
                                .map(|x| x.to_string())
                                .collect(),
                        ),
                        characters: Some(
                            post.tag_string_character
                                .split(' ')
                                .map(|x| x.to_string())
                                .collect(),
                        ),

                        main_url: Some(Url {
                            url: Some(post.source),
                            name: None,
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

#[async_trait]
impl DataProvider for Gelbooru {
    fn name(&self) -> &'static str {
        "gelbooru"
    }

    fn priority(&self) -> u8 {
        5
    }

    fn enabled(&self) -> bool {
        get_config().gelbooru.enabled.unwrap()
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        log::debug!("Checking if can enrich {}: {:?}", self.name(), hit);
        extract_key(hit, self.name()).is_some()
    }

    async fn enrich(&self, hit: &SearchHit) -> anyhow::Result<Option<Enrichment>> {
        if let Some(string_id) = extract_key(hit, self.name()) {
            log::debug!("Enriching {}: {}", self.name(), string_id);
            let id = str_to_u32(&string_id).unwrap();

            match self.client.get_by_id(id).await {
                Ok(post) => {
                    let ext = post.file_url.split('.').last().unwrap();
                    let video = match ext {
                        "gif" | "mp4" | "webm" => Some(post.file_url.clone()),
                        _ => None,
                    };
                    let thumbnail = match ext {
                        "jpg" | "jpeg" | "png" | "webp" => Some(post.file_url.clone()),
                        _ => None,
                    };

                    let data = Enrichment {
                        thumbnail,
                        video,
                        tags: Some(post.tags.split(' ').map(|x| x.to_string()).collect()),

                        main_url: Some(Url {
                            url: Some(post.source),
                            name: None,
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

#[async_trait]
impl DataProvider for Safebooru {
    fn name(&self) -> &'static str {
        "safebooru"
    }

    fn priority(&self) -> u8 {
        5
    }

    fn enabled(&self) -> bool {
        get_config().safebooru.enabled.unwrap()
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        log::debug!("Checking if can enrich {}: {:?}", self.name(), hit);
        extract_key(hit, self.name()).is_some()
    }

    async fn enrich(&self, hit: &SearchHit) -> anyhow::Result<Option<Enrichment>> {
        if let Some(string_id) = extract_key(hit, self.name()) {
            log::debug!("Enriching {}: {}", self.name(), string_id);
            let id = str_to_u32(&string_id).unwrap();

            match self.client.get_by_id(id).await {
                Ok(post) => {
                    let ext = post.image.split('.').last().unwrap();
                    let thumbnail = match ext {
                        "jpg" | "jpeg" | "png" | "webp" => Some(post.image.clone()),
                        _ => None,
                    };
                    let video = match ext {
                        "gif" => Some(post.image.clone()),
                        _ => None,
                    };

                    let data = Enrichment {
                        thumbnail,
                        video,
                        tags: Some(post.tags.split(' ').map(|x| x.to_string()).collect()),

                        main_url: Some(Url {
                            url: Service::Safebooru.build_url(&string_id),
                            name: None,
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
