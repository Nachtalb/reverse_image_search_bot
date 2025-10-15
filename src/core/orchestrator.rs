use std::{collections::HashMap, sync::Arc};

use crate::{
    engines::{Iqdb, ReverseEngine, SauceNao, TraceMoe},
    models::Enrichment,
    providers::{Anilist, Danbooru, DataProvider, Gelbooru, Safebooru},
};
use anyhow::Result;
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
    let (tx, rx) = mpsc::channel(32);
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
        let tx = tx.clone();
        let url = url.clone();
        let providers = Arc::clone(&providers);

        tokio::spawn(async move {
            log::info!("Spawning engine {}", engine.name());

            if let Ok(hits) = engine.filter_search(&url, Some(1), None).await {
                log::info!("Found {} hits", hits.len());

                for hit in hits {
                    let tx = tx.clone();
                    let hit = Arc::new(hit);
                    let providers = Arc::clone(&providers);

                    tokio::spawn(async move {
                        log::info!("Spawning provider enrichments");

                        let mut enrichments: Vec<Enrichment> = vec![];
                        let mut handlers: HashMap<String, JoinHandle<Result<Option<Enrichment>>>> =
                            HashMap::new();

                        for provider in providers.iter().filter(|p| p.can_enrich(&hit)) {
                            let provider = Arc::clone(provider);
                            let hit = Arc::clone(&hit);
                            let name = provider.name().to_string();

                            let handler = tokio::spawn(async move { provider.enrich(&hit).await });

                            handlers.insert(name, handler);
                        }

                        for (name, handler) in handlers {
                            match handler.await {
                                Ok(Ok(None)) => (),
                                Ok(Ok(Some(enrichment))) => {
                                    enrichments.push(enrichment);
                                }
                                Ok(Err(e)) => log::error!("Failed to enrich {}: {}", name, e),
                                Err(e) => log::error!("Failed to enrich {}: {}", name, e),
                            }
                        }

                        log::info!("{} enrichments", enrichments.len());
                        if let Some(merged) = merge_enrichments(enrichments) {
                            let _ = tx.send(Ok(merged)).await;
                        };
                    });
                }
            }
        });
    }

    drop(tx);
    rx
}
