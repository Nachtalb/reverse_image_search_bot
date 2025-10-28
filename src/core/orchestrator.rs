use std::{collections::HashMap, sync::Arc};

use crate::{
    engines::{BoxedReverseEngine, ENGINES},
    models::{Enrichment, SearchHit},
    providers::PROVIDERS,
};
use anyhow::{Error, Result};
use figment::{Figment, providers::Serialized};
use tokio::{
    sync::mpsc::{self, Receiver},
    task::JoinHandle,
};

fn merge_enrichments(mut enrichments: Vec<Enrichment>) -> Option<Enrichment> {
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

async fn process_enrichments(hit: Arc<SearchHit>, tx: mpsc::Sender<Result<Enrichment>>) {
    log::info!("Spawning provider enrichments");
    let providers = PROVIDERS.clone();

    let mut enrichments: Vec<Enrichment> = vec![];
    let mut handles: HashMap<String, JoinHandle<Result<Option<Enrichment>>>> = HashMap::new();

    for provider in providers.iter().filter(|p| p.can_enrich(&hit)) {
        let provider = provider.clone();
        if !provider.enabled() {
            log::debug!("Skipping disabled provider {}", provider.name());
            continue;
        }
        let hit = Arc::clone(&hit);
        let name = provider.name().to_string();

        log::info!("Enriching with {}", name);
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
                let err = Error::msg(format!("Failed to enrich {} (JoinError): {}", name, e));
                let _ = tx.send(Err(err)).await;
            }
        }
    }

    log::info!("{} enrichments", enrichments.len());
    if let Some(merged) = merge_enrichments(enrichments) {
        let _ = tx.send(Ok(merged)).await;
    };
}

async fn process_engine(
    engine: Arc<BoxedReverseEngine>,
    url: String,
    tx: mpsc::Sender<Result<Enrichment>>,
) {
    log::info!("Spawning engine {}", engine.name());

    let hits = match engine.filter_search(&url, Some(1), None).await {
        Ok(hits) => hits,
        Err(e) => {
            let err = Error::msg(format!("Search error in engine {}: {}", engine.name(), e));
            let _ = tx.send(Err(err)).await;
            return;
        }
    };

    log::info!("Found {} hits for {}", hits.len(), engine.name());
    for hit in hits {
        let tx = tx.clone();
        let hit = Arc::new(hit);

        tokio::spawn(async move { process_enrichments(hit.clone(), tx.clone()).await });
    }
}

pub async fn reverse_search(url: String) -> Receiver<Result<Enrichment>> {
    log::info!("Reverse search for {}", url);
    let (tx, rx) = mpsc::channel::<Result<Enrichment>>(32);
    let engines = ENGINES.clone();

    for engine in engines.iter() {
        if !engine.enabled() {
            log::info!("Skipping disabled engine {}", engine.name());
            continue;
        }
        let url = url.clone();
        let tx = tx.clone();
        let engine = engine.clone();

        tokio::spawn(async move {
            process_engine(engine, url, tx).await;
        });
    }

    drop(tx);
    rx
}
