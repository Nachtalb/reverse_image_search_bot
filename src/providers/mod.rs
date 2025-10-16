use crate::models::{Enrichment, SearchHit};
use anyhow::Result;
use async_trait::async_trait;

#[async_trait]
pub trait DataProvider: Send + Sync {
    fn name(&self) -> &'static str;
    fn priority(&self) -> u8;
    fn enabled(&self) -> bool;
    fn can_enrich(&self, hit: &SearchHit) -> bool;
    fn extract_key(&self, hit: &SearchHit) -> Option<String>;
    async fn enrich(&self, hit: &SearchHit) -> Result<Option<Enrichment>>;
}

pub mod anilist;
pub mod booru;
// pub mod pixiv;
// pub mod anidb;
// pub mod myanilist;

pub use anilist::Anilist;
pub use booru::{Danbooru, Gelbooru, Safebooru};
// pub use mangadex::Mangadex;
// pub use pixiv::Pixiv;
// pub use anidb::Anidb;
// pub use myanilist::MyAniList;
