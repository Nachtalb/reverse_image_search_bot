use std::{collections::HashMap, time::Duration};

use crate::{engines::ReverseEngine, models::SearchHit, transformers::Service};
use async_trait::async_trait;

use reqwest::Client;
use scraper::ElementRef;
use serde_json::Value;

use anyhow::Result;

use crate::config::get_config;

const IQDB_URL: &str = "https://iqdb.org";

macro_rules! sel {
    ($sel:literal) => {
        &scraper::Selector::parse($sel).expect("invalid selector")
    };
}

#[derive(Clone, Debug)]
pub struct Iqdb {
    client: Client,
    threshold: Option<f32>,
    limit: Option<usize>,
}

impl Iqdb {
    pub(crate) fn new() -> Self {
        Self {
            client: Client::new(),
            threshold: get_config().iqdb.threshold,
            limit: get_config().iqdb.limit,
        }
    }

    fn parse_result(&self, result: ElementRef) -> Option<SearchHit> {
        let image_ref = result.select(sel!(".image img")).next()?;
        let thumbnail = image_ref.value().attr("src")?;

        let thumbnail = if !thumbnail.contains(IQDB_URL) {
            format!("{IQDB_URL}{thumbnail}")
        } else {
            thumbnail.to_string()
        };

        let mut metadata = HashMap::new();
        for link in result.select(sel!("a")) {
            let url = link.value().attr("href")?;
            let url = if url.starts_with("//") {
                format!("https:{url}")
            } else {
                url.to_string()
            };

            let service = Service::from_url(url.as_str());
            if let Some(id) = service.get_id(url.as_str()) {
                metadata.insert(service.key(), Value::String(id));
            } else {
                metadata.insert(service.key(), Value::String(url));
            }
        }

        let score = result.select(sel!("tr:last-child > td")).next()?;
        let score = score.text().collect::<String>();
        let score = score.split_once('%')?.0.parse::<f32>().ok()? / 100.0;

        Some(SearchHit {
            thumbnail: Some(thumbnail.to_string()),
            similarity: score,
            engine: self.name().to_string(),
            metadata,
        })
    }
}

#[async_trait]
impl ReverseEngine for Iqdb {
    fn name(&self) -> &'static str {
        "iqdb"
    }

    fn threshold(&self) -> Option<f32> {
        self.threshold
    }

    fn limit(&self) -> Option<usize> {
        self.limit
    }

    fn enabled(&self) -> bool {
        get_config().iqdb.enabled.unwrap()
    }

    async fn search(&self, url: &str) -> Result<Vec<SearchHit>> {
        log::info!("Searching iqdb for {}", url);
        let request = self
            .client
            .get(IQDB_URL)
            .query(&[
                ("url", url),
                ("service[]", "11"), // Zerochan
                ("service[]", "13"), // Anime-Pictures
                                     // All other services are already covered by saucenao
            ])
            .timeout(Duration::from_secs(get_config().iqdb.timeout.unwrap()));

        let response = request.send().await?;
        let html = scraper::Html::parse_document(&response.text().await?);

        Ok(html
            .select(sel!("#pages > div"))
            .skip(1)
            .filter_map(|el| self.parse_result(el))
            .collect())
    }
}
