use crate::models::{Enrichment, SearchHit};
use async_trait::async_trait;

#[async_trait]
pub trait ReverseEngine {
    fn name(&self) -> &'static str;
    fn threshold(&self) -> Option<f32>;
    fn limit(&self) -> Option<usize>;

    async fn search(&self, url: &str) -> anyhow::Result<Vec<SearchHit>>;

    fn enrichment(&self, hit: &SearchHit) -> Option<Enrichment>;

    async fn filter_search(
        &self,
        url: &str,
        limit: Option<usize>,
        threshold: Option<f32>,
    ) -> anyhow::Result<Vec<SearchHit>> {
        let mut hits = self.search(url).await.unwrap();

        let limit = limit.or(self.limit());
        let threshold = threshold.or(self.threshold());

        hits = if let Some(limit) = limit {
            hits.into_iter().take(limit).collect()
        } else {
            hits
        };

        hits = if let Some(threshold) = threshold {
            hits.into_iter()
                .filter(|hit| hit.similarity >= threshold)
                .collect()
        } else {
            hits
        };

        Ok(hits)
    }
}

pub mod tracemoe;
// pub mod saucenao;

pub use tracemoe::TraceMoe;
// pub use saucenao::SauceNao;
