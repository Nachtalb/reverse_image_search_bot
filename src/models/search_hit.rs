use std::collections::HashMap;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SearchHit {
    /// Similarity score
    pub similarity: f32,
    /// Search result thumbnail url
    pub thumbnail: Option<String>,

    /// Search engine used
    pub engine: String,

    /// Various data used for enrichment
    pub metadata: HashMap<String, serde_json::Value>,
}
