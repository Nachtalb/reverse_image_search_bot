use crate::{
    engines::ReverseEngine,
    models::{AnimeData, Enrichment, EpisodesData, SearchHit},
};
use async_trait::async_trait;

use serde_json::Value;
use tokio::sync::OnceCell;
use trace_moe::client::Client;
use trace_moe::tracemoe::{SearchQuery, SearchResponse, new_client_with_key};

use anyhow::Result;

use crate::config::get_config;

static CLIENT: OnceCell<Client> = OnceCell::const_new();

pub(crate) fn get_client() -> Result<&'static Client> {
    if !CLIENT.initialized() {
        let config = get_config();
        let client = new_client_with_key(config.tracemoe_api_key.as_deref());
        CLIENT.set(client?)?;
    }

    Ok(CLIENT.get().unwrap())
}

#[derive(Clone, Debug)]
pub struct TraceMoe {
    client: &'static Client,
    threshold: Option<f32>,
    limit: Option<usize>,
}

impl TraceMoe {
    pub fn new() -> Self {
        Self {
            client: get_client().unwrap(),
            threshold: get_config().tracemoe_threshold,
            limit: get_config().tracemoe_limit,
        }
    }
}

#[async_trait]
impl ReverseEngine for TraceMoe {
    fn name(&self) -> &'static str {
        "tracemoe"
    }

    fn threshold(&self) -> Option<f32> {
        self.threshold
    }

    fn limit(&self) -> Option<usize> {
        self.limit
    }

    fn enrichment(&self, hit: &SearchHit) -> Option<Enrichment> {
        if hit.engine == "tracemoe" {
            Some(Enrichment::Anime(Box::new(AnimeData {
                episodes: hit.metadata.get("hit_episode").and_then(|episode| {
                    if let Value::Number(n) = episode {
                        let ep = n.as_u64().map(|n| n as u32)?;
                        hit.metadata.get("hit_timestamp").and_then(|timestamp| {
                            if let Value::Number(n) = timestamp {
                                let ts = n.as_f64()?;
                                Some(EpisodesData {
                                    hit: Some(ep),
                                    hit_timestamp: Some(ts),
                                    hit_image: hit
                                        .metadata
                                        .get("hit_image")
                                        .unwrap()
                                        .as_str()
                                        .map(|s| s.to_string()),
                                    hit_video: hit
                                        .metadata
                                        .get("hit_video")
                                        .unwrap()
                                        .as_str()
                                        .map(|s| s.to_string()),
                                    ..Default::default()
                                })
                            } else {
                                None
                            }
                        })
                    } else {
                        None
                    }
                }),
                enrichers: std::collections::HashSet::from([String::from("tracemoe")]),
                ..Default::default()
            })))
        } else {
            None
        }
    }

    async fn search(&self, url: &str) -> anyhow::Result<Vec<SearchHit>> {
        let query = SearchQuery {
            url: Some(url.to_string()),
            anilist_id: None,
            cut_borders: Some(true),
            anilist_info: Some(false),
        };

        let response: SearchResponse<i128> = self.client.tracemoe_search_by_url(&query).await?;

        Ok(response
            .result
            .iter()
            .map(|result| {
                let mut metadata = std::collections::HashMap::from([
                    (
                        "anilist_id".to_string(),
                        Value::Number(serde_json::Number::from_i128(result.anilist).unwrap()),
                    ),
                    (
                        "hit_timestamp".to_string(),
                        Value::Number(serde_json::Number::from_f64(result.at).unwrap()),
                    ),
                    ("hit_image".to_string(), Value::String(result.image.clone())),
                    ("hit_video".to_string(), Value::String(result.video.clone())),
                ]);

                if let Some(episode) = &result.episode {
                    match episode {
                        trace_moe::tracemoe::Episode::Number(ep) => {
                            metadata.insert(
                                "hit_episode".to_string(),
                                Value::Number(serde_json::Number::from_i128(*ep as i128).unwrap()),
                            );
                        }
                        trace_moe::tracemoe::Episode::Text(ep) => {
                            metadata.insert("episode".to_string(), Value::String(ep.clone()));
                        }
                    }
                }

                SearchHit {
                    similarity: result.similarity as f32,
                    thumbnail: Some(result.image.clone()),
                    engine: "tracemoe".to_string(),
                    metadata,
                }
            })
            .collect())
    }
}
