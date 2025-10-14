use crate::models::{Enrichment, SearchHit};
use async_trait::async_trait;

#[async_trait]
pub trait DataProvider: Send + Sync {
    fn can_enrich(&self, hit: &SearchHit) -> bool;
    fn extract_key(&self, hit: &SearchHit) -> Option<String>;
    async fn enrich(&self, hit: &SearchHit) -> anyhow::Result<Option<Enrichment>>;
}

pub mod anilist;
// pub mod mangadex;
// pub mod pixiv;
// pub mod anidb;
// pub mod myanilist;

pub use anilist::Anilist;
// pub use mangadex::Mangadex;
// pub use pixiv::Pixiv;
// pub use anidb::Anidb;
// pub use myanilist::MyAniList;
