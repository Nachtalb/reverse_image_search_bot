use anyhow::{Error, Result};
use redis::{
    AsyncCommands, Client, HashFieldExpirationOptions, SetExpiry, Value,
    aio::{ConnectionLike, ConnectionManager},
    cmd,
};
use serde::{Deserialize, Serialize};
use tokio::sync::OnceCell;

use crate::config::get_config;

const HASH_INDEX: &str = "phash_idx";

async fn setup_redis_data(connection: &mut impl ConnectionLike) -> Result<()> {
    let mut info_cmd = cmd("FT.INFO");
    info_cmd.arg(HASH_INDEX);
    match info_cmd.query_async::<Value>(connection).await {
        Ok(_) => {
            log::info!("pHash index exists");
            Ok(())
        }
        Err(_) => {
            log::info!("Creating pHash index");
            let mut create_cmd = cmd("FT.CREATE");
            create_cmd
                .arg(HASH_INDEX)
                .arg("ON")
                .arg("HASH")
                .arg("PREFIX")
                .arg(1i64)
                .arg("image:")
                .arg("PAYLOAD_FIELD")
                .arg("payload")
                .arg("SCHEMA")
                .arg("id")
                .arg("TAG");
            create_cmd
                .query_async::<()>(connection)
                .await
                .map_err(|e| anyhow::anyhow!("Failed to create pHash index: {}", e))?;
            Ok(())
        }
    }
}

async fn setup_redis() -> Option<Redis> {
    let config = get_config();
    let client = match Client::open(format!(
        "redis://{}:{}",
        config.redis.host.clone().unwrap(),
        config.redis.port.unwrap()
    )) {
        Ok(client) => client,
        Err(err) => {
            log::error!("Failed to create a redis client - disabling redis: {}", err);
            return None;
        }
    };

    let manager = match client.get_connection_manager().await {
        Ok(mut manager) => match setup_redis_data(&mut manager).await {
            Ok(_) => manager,
            Err(err) => {
                log::error!("Failed to setup redis data - disabling redis: {}", err);
                return None;
            }
        },
        Err(err) => {
            log::error!("Failed to connect to redis - disabling redis: {}", err);
            return None;
        }
    };

    Some(Redis {
        conn_manager: manager,
        expiry: config.redis.expiry,
    })
}

static REDIS: OnceCell<Option<Redis>> = OnceCell::const_new();

pub(crate) async fn get_redis() -> &'static Option<Redis> {
    REDIS.get_or_init(setup_redis).await
}

pub(crate) struct Redis {
    conn_manager: ConnectionManager,
    expiry: Option<u64>,
}

impl Redis {
    fn connection(&self) -> impl ConnectionLike {
        self.conn_manager.clone()
    }

    pub(crate) async fn get(&self, key: &str) -> redis::RedisResult<Option<String>> {
        self.connection().get(key).await
    }

    pub(crate) async fn store(&self, key: &str, value: String) -> redis::RedisResult<()> {
        let mut connection = self.connection();

        if let Some(expiry) = self.expiry {
            connection.set_ex(key, value, expiry).await
        } else {
            connection.set(key, value).await
        }
    }

    pub(crate) async fn store_struct(&self, key: &str, value: impl Serialize) -> Result<()> {
        let value = match serde_json::to_string(&value) {
            Ok(value) => value,
            Err(e) => {
                log::error!("Failed to serialize value: {}", e);
                return Err(Error::msg(format!("Failed to serialize value: {}", e)));
            }
        };
        self.store(key, value).await.map_err(|e| e.into())
    }
    pub(crate) async fn invalidate(&self, key: &str) -> redis::RedisResult<()> {
        self.connection().del(key).await
    }

    pub(crate) async fn get_structs<T>(&self, keys: Vec<String>) -> Result<Vec<T>>
    where
        T: for<'de> Deserialize<'de>,
    {
        match self.connection().mget(&keys).await {
            Ok::<Vec<Option<String>>, _>(values) => {
                let mut result = Vec::new();
                for (value, key) in values
                    .into_iter()
                    .zip(keys)
                    .filter_map(|(v, k)| v.map(|v| (v, k)))
                {
                    match serde_json::from_str(&value) {
                        Ok(value) => result.push(value),
                        Err(e) => {
                            log::error!("Failed to deserialize value - invalidating it: {}", e);
                            if let Err(err) = self.invalidate(key.as_str()).await {
                                log::error!("Failed to invalidate key: {}", err);
                            }
                        }
                    }
                }
                Ok(result)
            }
            Err(e) => Err(e.into()),
        }
    }

    pub(crate) async fn get_keys(&self, pattern: &str) -> redis::RedisResult<Vec<String>> {
        self.connection().keys(pattern).await
    }

    pub(crate) async fn store_phash(&self, id: &str, phash: Vec<u8>) -> redis::RedisResult<()> {
        let key = format!("image:{}", id);
        if let Some(expiry) = self.expiry {
            let expiry =
                HashFieldExpirationOptions::default().set_expiration(SetExpiry::EX(expiry));

            self.connection()
                .hset_ex(&key, &expiry, &[("payload", phash)])
                .await
        } else {
            self.connection().hset(&key, "payload", phash).await
        }
    }

    pub(crate) async fn find_similar(&self, query_phash: &[u8]) -> Result<Vec<(String, u32)>> {
        let config = get_config();
        let threshold = config.cache.phash_max_distance.unwrap();
        let max_results = config.cache.max_search_results.unwrap();

        let mut connection = self.connection();
        let mut search_cmd = cmd("FT.SEARCH");
        search_cmd
            .arg(HASH_INDEX)
            .arg("*")
            .arg("PAYLOAD")
            .arg(query_phash)
            .arg("SCORER")
            .arg("HAMMING")
            .arg("WITHSCORES")
            .arg("RETURN")
            .arg(0i64)
            .arg("LIMIT")
            .arg(0i64)
            .arg(max_results as i64);

        let result: Vec<Value> = match search_cmd.query_async(&mut connection).await {
            Ok(result) => result,
            Err(e) => {
                log::error!("Failed to search index: {}", e);
                return Err(Error::msg(format!("Failed to search index: {}", e)));
            }
        };

        if result.is_empty() {
            return Err(Error::msg("Invalid return value"));
        }

        let total: i64 = match result[0] {
            Value::Int(total) => total,
            _ => return Err(Error::msg("Invalid total")),
        };

        let mut similar = Vec::new();
        for i in 0..total.min(max_results as i64) as usize {
            let idx = 1 + 2 * i;
            let key_val = &result[idx];
            let score_val = &result[idx + 1];
            let key = match key_val {
                Value::SimpleString(value) => value.to_owned(),
                Value::BulkString(value) => std::str::from_utf8(value)
                    .map(|s| {
                        s.strip_prefix('"')
                            .and_then(|s| s.strip_suffix('"'))
                            .unwrap_or(s)
                            .to_string()
                    })
                    .unwrap_or_default(),
                other => return Err(Error::msg(format!("Invalid key: {:?}", other))),
            };

            let score = match score_val {
                Value::BulkString(value) => {
                    std::str::from_utf8(value).map(|s| s.parse::<f64>().unwrap())?
                }
                other => return Err(Error::msg(format!("Invalid score: {:?}", other))),
            };

            let dist = (1.0 / score - 1.0) as u32;
            if dist <= threshold
                && let Some(id) = key.strip_prefix("image:")
            {
                similar.push((id.to_string(), dist));
            }
        }
        similar.sort_by(|a, b| b.1.cmp(&a.1));
        Ok(similar)
    }
}
