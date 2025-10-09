use std::error::Error;

use tokio::sync::OnceCell;
use trace_moe::client::Client;
use trace_moe::tracemoe::{SearchQuery, SearchResponse, SearchResult, new_client_with_key};

use crate::config::get_config;

static CLIENT: OnceCell<Client> = OnceCell::const_new();

pub(crate) async fn get_client() -> Result<&'static Client, Box<dyn Error + Send + Sync + 'static>>
{
    if !CLIENT.initialized() {
        let config = get_config();
        let client = new_client_with_key(config.tracemoe_api_key.as_deref());
        match client {
            Ok(client) => {
                CLIENT.set(client).unwrap();
            }
            Err(err) => {
                return Err(Box::new(err));
            }
        }
    }

    Ok(CLIENT.get().unwrap())
}

pub(crate) async fn search_by_url(
    url: &str,
) -> Result<SearchResponse, Box<dyn Error + Send + Sync + 'static>> {
    let query = SearchQuery {
        url: Some(url.to_string()),
        anilist_id: None,
        cut_borders: Some(true),
        anilist_info: Some(false),
    };

    let client = get_client().await?;
    match client.tracemoe_search_by_url(&query).await {
        Ok(resp) => Ok(resp),
        Err(err) => Err(Box::new(err)),
    }
}

pub(crate) fn best_or_none(
    response: SearchResponse,
    threshold: Option<f64>,
) -> Option<SearchResult> {
    if response.result.is_empty() {
        return None;
    }

    let threshold_used = match threshold {
        Some(threshold) => threshold,
        None => get_config().tracemoe_threshold.unwrap_or(0.0),
    };

    if threshold_used == 0.0 {
        response.result.into_iter().next()
    } else {
        response
            .result
            .into_iter()
            .find(|result| result.similarity >= threshold_used)
    }
}
