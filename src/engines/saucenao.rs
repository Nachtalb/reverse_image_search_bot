use std::collections::HashMap;

use crate::{
    engines::ReverseEngine,
    models::{Enrichment, SearchHit, Url},
    providers::DataProvider,
    transformers::Service,
};
use async_trait::async_trait;

use rustnao::{Handler as Client, HandlerBuilder, Sauce};
use serde_json::Value;

use anyhow::Result;

use crate::config::get_config;

fn get_client() -> Client {
    let config = get_config();
    if let Some(api_key) = config.saucenao_api_key.clone() {
        HandlerBuilder::default().api_key(api_key.as_str()).build()
    } else {
        HandlerBuilder::default().build()
    }
}

#[derive(Clone, Debug)]
pub struct SauceNao {
    threshold: Option<f32>,
    limit: Option<usize>,
}

impl SauceNao {
    pub(crate) fn new() -> Self {
        Self {
            threshold: get_config().saucenao_threshold,
            limit: get_config().saucenao_limit,
        }
    }

    fn name(&self) -> &'static str {
        "saucenao"
    }
}

#[async_trait]
impl DataProvider for SauceNao {
    fn name(&self) -> &'static str {
        <SauceNao>::name(self)
    }

    fn priority(&self) -> u8 {
        1
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        hit.engine == self.name()
    }

    fn extract_key(&self, _: &SearchHit) -> Option<String> {
        None
    }

    async fn enrich(&self, hit: &SearchHit) -> Result<Option<Enrichment>> {
        if !self.can_enrich(hit) {
            return Ok(None);
        }

        let mut urls: Vec<Url> = Vec::new();
        for (k, v) in &hit.metadata {
            let id = if let Some(id) = v.as_str() {
                id
            } else {
                continue;
            };
            match Service::from_string(k.as_str()) {
                Some(Service::Unknown(_)) => continue,
                Some(serv) => {
                    if let Some(url) = serv.build_url(id) {
                        urls.push(Url {
                            url: Some(url),
                            ..Default::default()
                        });
                    }
                }
                None => continue,
            }
        }

        Ok(if urls.is_empty() {
            None
        } else {
            Some(Enrichment {
                urls: Some(urls),
                thumbnail: hit.thumbnail.clone(),
                enrichers: std::collections::HashSet::from([String::from(self.name())]),
                priority: self.priority(),
                ..Default::default()
            })
        })
    }
}

#[async_trait]
impl ReverseEngine for SauceNao {
    fn name(&self) -> &'static str {
        <SauceNao>::name(self)
    }

    fn threshold(&self) -> Option<f32> {
        self.threshold
    }

    fn limit(&self) -> Option<usize> {
        self.limit
    }

    async fn search(&self, url: &str) -> Result<Vec<SearchHit>> {
        let client = get_client();
        let sauce = match client.get_sauce(url, None, None) {
            Ok(sauce) => sauce,
            Err(e) => {
                log::error!("Saucenao error: {}", e);
                return Err(anyhow::anyhow!(e));
            }
        };

        log::debug!("Saucenao hits: {:#?}", sauce.first().unwrap());

        Ok(sauce
            .iter()
            .map(|item: &Sauce| {
                let mut metadata = match item.additional_fields.clone() {
                    Some(fields) => match fields.as_object() {
                        Some(obj) => obj.iter().map(|(k, v)| (k.clone(), v.clone())).collect(),
                        None => HashMap::new(),
                    },
                    None => HashMap::new(),
                };

                item.ext_urls
                    .iter()
                    .map(|u| u.as_str())
                    .filter_map(Service::parse_url)
                    .for_each(|(service, id)| {
                        metadata.insert(service.key(), Value::String(id));
                    });

                SearchHit {
                    engine: self.name().to_string(),
                    similarity: item.similarity,
                    thumbnail: Some(item.thumbnail.clone()),
                    metadata: metadata.to_owned(),
                    ..Default::default()
                }
            })
            .collect())
    }
}
