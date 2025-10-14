use std::sync::Arc;

use crate::{
    engines::{ReverseEngine, TraceMoe},
    models::{AnimeData, Enriched, Enrichment, FanartData, GenericData, MangaData},
    providers::{Anilist, DataProvider},
};
use anyhow::Result;
use figment::{Figment, providers::Serialized};
use futures::future::join_all;
use serde::{Deserialize, Serialize};
use tokio::sync::mpsc::{self, Receiver};

fn merge_enrichments(enrichments: Vec<Enrichment>) -> Enriched {
    let mut anime = vec![];
    let mut manga = vec![];
    let mut fanart = vec![];
    let mut generic = vec![];

    for e in enrichments {
        match e {
            Enrichment::Anime(a) => anime.push(a),
            Enrichment::Manga(m) => manga.push(m),
            Enrichment::Fanart(f) => fanart.push(f),
            Enrichment::Generic(g) => generic.push(g),
        }
    }

    let anime = merge_vec::<AnimeData>(anime);
    let manga = merge_vec::<MangaData>(manga);
    let fanart = merge_vec::<FanartData>(fanart);
    let generic = merge_vec::<GenericData>(generic);

    Enriched {
        anime,
        manga,
        fanart,
        generic,
    }
}

fn merge_vec<T>(mut vec: Vec<Box<T>>) -> Option<Box<T>>
where
    T: Default + Serialize + for<'de> Deserialize<'de> + Clone,
{
    if vec.is_empty() {
        None
    } else if vec.len() == 1 {
        Some(vec.pop().unwrap())
    } else {
        let mut figment = Figment::from(Serialized::defaults(&vec[0]));
        for item in vec.into_iter().skip(1) {
            figment = figment.admerge(Serialized::defaults(&item));
        }
        figment.extract().ok()
    }
}

pub async fn reverse_search(url: String) -> Receiver<Result<Enriched>> {
    log::info!("Reverse search for {}", url);
    let (tx, rx) = mpsc::channel(32);
    // let engines = vec![Saucenao::new(), TraceMoe::new()];
    let engines = vec![TraceMoe::new()];
    // let providers = Arc::new(vec![Anilist::new(), Mangadex::new(), Pixiv::new()]);
    let providers = Arc::new(vec![Anilist::new()]);

    for engine in engines {
        let tx = tx.clone();
        let providers = providers.clone();
        let url = url.clone();
        tokio::spawn(async move {
            log::info!("Spawning engine {}", engine.name());

            if let Ok(hits) = engine.filter_search(&url, Some(1), None).await {
                log::info!("Found {} hits", hits.len());

                for hit in hits {
                    let tx = tx.clone();
                    let providers = providers.clone();
                    let hit = hit.clone(); // If not Clone, adjust
                    let engine_enrichment = engine.enrichment(&hit).clone();

                    tokio::spawn(async move {
                        log::info!("Spawning provider enrichments");

                        let mut enrichments: Vec<Enrichment> = vec![];

                        if let Some(enrichment) = engine_enrichment {
                            enrichments.push(enrichment.clone());
                        }

                        if !hit.metadata.is_empty() {
                            enrichments.push(Enrichment::Generic(Box::new(GenericData {
                                key_values: hit.metadata.clone(),
                            })));
                        }

                        let enrich_futures = providers
                            .iter()
                            .filter(|p| p.can_enrich(&hit))
                            .map(|p| p.enrich(&hit));
                        let enrich_results: Vec<Result<Option<Enrichment>>> =
                            join_all(enrich_futures).await;
                        enrichments.extend(
                            enrich_results
                                .into_iter()
                                .filter_map(|r| r.ok().and_then(|o| o))
                                .collect::<Vec<Enrichment>>(),
                        );
                        log::info!("{} enrichments", enrichments.len());
                        let merged = merge_enrichments(enrichments);
                        if merged.any() {
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
