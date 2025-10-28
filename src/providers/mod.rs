use std::sync::Arc;

use crate::{
    engines::{SauceNao, TraceMoe},
    models::{Enrichment, SearchHit},
};
use anyhow::Result;
use async_trait::async_trait;

use once_cell::sync::Lazy;

#[async_trait]
pub trait DataProvider: Send + Sync {
    fn name(&self) -> &'static str;
    fn priority(&self) -> u8;
    fn enabled(&self) -> bool;
    fn can_enrich(&self, hit: &SearchHit) -> bool;
    async fn enrich(&self, hit: &SearchHit) -> Result<Option<Enrichment>>;
}

pub mod anilist;
pub mod booru;
pub mod generic;
pub mod mangadex;
// pub mod pixiv;
// pub mod anidb;
// pub mod myanilist;

pub use anilist::Anilist;
pub use booru::{Danbooru, Gelbooru, Safebooru};
pub use generic::Generic;
pub use mangadex::MangaDex;
// pub use mangadex::Mangadex;
// pub use pixiv::Pixiv;
// pub use anidb::Anidb;
// pub use myanilist::MyAniList;

pub(crate) type BoxedDataProvider = Box<dyn DataProvider + Send + Sync>;
pub(crate) static PROVIDERS: Lazy<Arc<Vec<Arc<BoxedDataProvider>>>> = Lazy::new(|| {
    Arc::new(vec![
        Arc::new(Box::new(Generic::new())),
        Arc::new(Box::new(Anilist::new())),
        Arc::new(Box::new(MangaDex::new())),
        Arc::new(Box::new(TraceMoe::new())),
        Arc::new(Box::new(SauceNao::new())),
        Arc::new(Box::new(Danbooru::new())),
        Arc::new(Box::new(Gelbooru::new())),
        Arc::new(Box::new(Safebooru::new())),
    ])
});
