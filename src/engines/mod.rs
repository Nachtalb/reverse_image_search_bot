use crate::models::SearchHit;
use async_trait::async_trait;

#[async_trait]
pub trait ReverseEngine {
    fn name(&self) -> &'static str;
    fn threshold(&self) -> Option<f32>;
    fn limit(&self) -> Option<usize>;

    async fn search(&self, url: &str) -> anyhow::Result<Vec<SearchHit>>;

    async fn filter_search(
        &self,
        url: &str,
        limit: Option<usize>,
        threshold: Option<f32>,
    ) -> anyhow::Result<Vec<SearchHit>> {
        let mut hits = self.search(url).await?;

        let limit = limit.or(self.limit());
        let threshold = threshold.or(self.threshold());

        log::info!(
            "Filtering {} from {} hits with threshold {} and limit {}",
            hits.len(),
            self.name(),
            threshold.unwrap_or(0.0),
            limit.unwrap_or(0)
        );

        log::debug!(
            "Similarities: {}",
            hits.iter()
                .map(|hit| hit.similarity.to_string())
                .collect::<Vec<String>>()
                .join(", ")
        );

        hits = if let Some(threshold) = threshold {
            hits.into_iter()
                .filter(|hit| hit.similarity >= threshold)
                .collect()
        } else {
            hits
        };

        hits = if let Some(limit) = limit {
            hits.into_iter().take(limit).collect()
        } else {
            hits
        };

        log::info!("{} hits left from {} hits", hits.len(), self.name(),);

        Ok(hits)
    }
}

pub mod iqdb;
pub mod saucenao;
pub mod tracemoe;

pub use iqdb::Iqdb;
pub use saucenao::SauceNao;
pub use tracemoe::TraceMoe;
