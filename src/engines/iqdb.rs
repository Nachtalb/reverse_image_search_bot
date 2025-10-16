use std::collections::HashMap;

use crate::{engines::ReverseEngine, models::SearchHit, transformers::Service};
use async_trait::async_trait;

use sauce_api::source::{Source, iqdb::Iqdb as Client};
use serde_json::Value;
use tokio::sync::OnceCell;

use anyhow::Result;

use crate::config::get_config;

static CLIENT: OnceCell<Client> = OnceCell::const_new();

pub(crate) async fn get_client() -> Result<&'static Client> {
    if !CLIENT.initialized() {
        let client = Client::create(()).await.unwrap();
        CLIENT.set(client)?;
    }

    Ok(CLIENT.get().unwrap())
}

#[derive(Clone, Debug)]
pub struct Iqdb {
    client: &'static Client,
    threshold: Option<f32>,
    limit: Option<usize>,
}

impl Iqdb {
    pub(crate) async fn create() -> Result<Self> {
        Ok(Self {
            client: get_client().await?,
            threshold: get_config().iqdb_threshold,
            limit: get_config().iqdb_limit,
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

    async fn search(&self, url: &str) -> Result<Vec<SearchHit>> {
        log::info!("Searching iqdb for {}", url);
        let res = self.client.check(url).await;

        match res {
            Ok(output) => Ok(output
                .items
                .iter()
                .map(|item| {
                    let mut metadata =
                        HashMap::from([("hit_url".to_string(), Value::String(item.link.clone()))]);

                    if let Some(tuple) = Service::parse_url(item.link.as_str()) {
                        let (service, id) = tuple;
                        metadata.insert(service.key(), Value::String(id));
                    }

                    log::info!(
                        "IQDB: Found hit with similarity {} and link {}",
                        item.similarity,
                        item.link
                    );

                    SearchHit {
                        engine: self.name().to_string(),
                        similarity: item.similarity,
                        metadata: metadata.to_owned(),
                        ..Default::default()
                    }
                })
                .collect()),
            Err(err) => Err(anyhow::Error::msg(err)),
        }
    }
}
