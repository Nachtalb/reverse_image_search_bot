use crate::models::{Enrichment, SearchHit, Url};
use crate::providers::DataProvider;
use crate::transformers::Service;
use async_trait::async_trait;

#[derive(Clone)]
pub struct Generic;

impl Generic {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl DataProvider for Generic {
    fn name(&self) -> &'static str {
        "Generic"
    }

    fn priority(&self) -> u8 {
        0
    }

    fn enabled(&self) -> bool {
        true
    }

    fn extract_key(&self, _: &SearchHit) -> Option<String> {
        None
    }

    fn can_enrich(&self, hit: &SearchHit) -> bool {
        !hit.metadata.is_empty()
    }

    async fn enrich(&self, hit: &SearchHit) -> anyhow::Result<Option<Enrichment>> {
        let mut urls = hit.metadata.iter().filter_map(|(k, v)| {
            Service::from_string(k.as_str()).map(|service| Url {
                url: service.build_url(v.to_string().as_str()),
                name: Some(service.name().to_string()),
            })
        });

        let main_url = urls.next();

        if hit.thumbnail.is_some() || main_url.is_some() {
            let urls: Vec<Url> = urls.collect();
            Ok(Some(Enrichment {
                thumbnail: hit.thumbnail.clone(),
                main_url,
                urls: if urls.is_empty() { None } else { Some(urls) },
                priority: self.priority(),
                enrichers: std::collections::HashSet::from([self.name().to_string()]),
                ..Default::default()
            }))
        } else {
            Ok(None)
        }
    }
}
