use crate::{
    engines::ReverseEngine,
    models::{Enrichment, Episodes, SearchHit},
    providers::DataProvider,
};
use async_trait::async_trait;

use serde_json::Value;
use trace_moe::client::Client;
use trace_moe::tracemoe::{SearchQuery, SearchResponse, new_client_with_key};

use anyhow::Result;

use crate::config::get_config;

#[derive(Clone, Debug)]
pub struct TraceMoe {
    client: Client,
    threshold: Option<f32>,
    limit: Option<usize>,
}

impl TraceMoe {
    pub fn new() -> Self {
        Self {
            client: new_client_with_key(get_config().tracemoe.token.as_deref()).unwrap(),
            threshold: get_config().tracemoe.threshold,
            limit: get_config().tracemoe.limit,
        }
    }

    fn name(&self) -> &'static str {
        "TraceMoe"
    }
}

#[async_trait]
impl DataProvider for TraceMoe {
    fn name(&self) -> &'static str {
        <TraceMoe>::name(self)
    }

    fn priority(&self) -> u8 {
        1
    }

    fn enabled(&self) -> bool {
        get_config().tracemoe.enabled.unwrap()
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        hit.engine == self.name()
    }

    async fn enrich(&self, hit: &SearchHit) -> Result<Option<Enrichment>> {
        if !self.can_enrich(hit) {
            return Ok(None);
        }

        Ok(Some(Enrichment {
            episodes: hit.metadata.get("hit_episode").and_then(|episode| {
                if let Value::Number(n) = episode {
                    let ep = n.as_u64().map(|n| n as u32)?;
                    hit.metadata.get("hit_timestamp").and_then(|timestamp| {
                        if let Value::Number(n) = timestamp {
                            let ts = n.as_f64()?;
                            Some(Episodes {
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
            priority: self.priority(),
            enrichers: std::collections::HashSet::from([String::from(self.name())]),
            ..Default::default()
        }))
    }
}

#[async_trait]
impl ReverseEngine for TraceMoe {
    fn name(&self) -> &'static str {
        <TraceMoe>::name(self)
    }

    fn threshold(&self) -> Option<f32> {
        self.threshold
    }

    fn limit(&self) -> Option<usize> {
        self.limit
    }

    fn enabled(&self) -> bool {
        get_config().tracemoe.enabled.unwrap()
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
                    engine: self.name().to_string(),
                    metadata,
                }
            })
            .collect())
    }
}
