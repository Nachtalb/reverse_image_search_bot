use std::{collections::HashMap, sync::Arc};

use crate::{
    engines::{Iqdb, ReverseEngine, SauceNao, TraceMoe},
    models::Enrichment,
    providers::{Anilist, Danbooru, DataProvider, Gelbooru, Safebooru},
};
use anyhow::{Error, Result};
use figment::{Figment, providers::Serialized};
use tokio::{
    sync::mpsc::{self, Receiver},
    task::JoinHandle,
};

fn merge_enrichments(enrichments: Vec<Enrichment>) -> Option<Enrichment> {
    let mut enrichments = enrichments.clone();

    if enrichments.is_empty() {
        None
    } else if enrichments.len() == 1 {
        Some(enrichments.pop().unwrap())
    } else {
        enrichments.sort_by_key(|e| e.priority);

        let mut figment = Figment::from(Serialized::defaults(&enrichments[0]));
        for item in enrichments.into_iter().skip(1) {
            figment = figment.admerge(Serialized::defaults(&item));
        }
        figment.extract().ok()
    }
}

pub async fn reverse_search(url: String) -> Receiver<Result<Enrichment>> {
    log::info!("Reverse search for {}", url);
    let (tx, rx) = mpsc::channel::<Result<Enrichment>>(32);
    let mut engines: Vec<Box<dyn ReverseEngine + Send + Sync>> =
        vec![Box::new(TraceMoe::new()), Box::new(SauceNao::new())];

    match Iqdb::create().await {
        Ok(iqdb) => engines.push(Box::new(iqdb)),
        Err(e) => log::error!("Failed to create iqdb engine: {}", e),
    };

    let providers: Arc<Vec<Arc<Box<dyn DataProvider + Send + Sync>>>> = Arc::new(vec![
        Arc::new(Box::new(Anilist::new())),
        Arc::new(Box::new(TraceMoe::new())),
        Arc::new(Box::new(SauceNao::new())),
        Arc::new(Box::new(Danbooru::new())),
        Arc::new(Box::new(Gelbooru::new())),
        Arc::new(Box::new(Safebooru::new())),
    ]);
    for engine in engines {
        if !engine.enabled() {
            log::info!("Skipping disabled engine {}", engine.name());
            continue;
        }
        let tx = tx.clone();
        let url = url.clone();
        let providers = Arc::clone(&providers);

        tokio::spawn(async move {
            log::info!("Spawning engine {}", engine.name());

            let hits = match engine.filter_search(&url, Some(1), None).await {
                Ok(hits) => hits,
                Err(e) => {
                    let err =
                        Error::msg(format!("Search error in engine {}: {}", engine.name(), e));
                    let _ = tx.send(Err(err)).await;
                    return;
                }
            };

            log::info!("Found {} hits for {}", hits.len(), engine.name());
            for hit in hits {
                let tx = tx.clone();
                let hit = Arc::new(hit);
                let providers = Arc::clone(&providers);

                tokio::spawn(async move {
                    log::info!("Spawning provider enrichments");

                    let mut enrichments: Vec<Enrichment> = vec![];
                    let mut handles: HashMap<String, JoinHandle<Result<Option<Enrichment>>>> =
                        HashMap::new();

                    for provider in providers.iter().filter(|p| p.can_enrich(&hit)) {
                        let provider = Arc::clone(provider);
                        if !provider.enabled() {
                            log::debug!("Skipping disabled provider {}", provider.name());
                            continue;
                        }
                        let hit = Arc::clone(&hit);
                        let name = provider.name().to_string();

                        let handle = tokio::spawn(async move { provider.enrich(&hit).await });

                        handles.insert(name, handle);
                    }

                    for (name, handle) in handles {
                        match handle.await {
                            Ok(Ok(None)) => (),
                            Ok(Ok(Some(enrichment))) => {
                                enrichments.push(enrichment);
                            }
                            Ok(Err(e)) => {
                                let err = Error::msg(format!("Failed to enrich {}: {}", name, e));
                                let _ = tx.send(Err(err)).await;
                            }
                            Err(e) => {
                                let err = Error::msg(format!(
                                    "Failed to enrich {} (JoinError): {}",
                                    name, e
                                ));
                                let _ = tx.send(Err(err)).await;
                            }
                        }
                    }

                    log::info!("{} enrichments", enrichments.len());
                    if let Some(merged) = merge_enrichments(enrichments) {
                        let _ = tx.send(Ok(merged)).await;
                    };
                });
            }
        });
    }

    drop(tx);
    rx
}
