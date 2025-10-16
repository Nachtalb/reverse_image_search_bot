use std::path::PathBuf;

use clap::Parser;
use serde::Serialize;

use crate::config::{
    AniList, Config, Danbooru, Gelbooru, General, Iqdb, RustyPaste, Safebooru, SauceNao, Telegram,
    TraceMoe,
};

#[derive(Parser, Serialize, Debug)]
pub(crate) struct CliArgs {
    /// Telegram bot token
    #[arg(short, long, env = "RIS_TELEGRAM_TOKEN")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) token: Option<String>,

    /// Downloads directory (default: "downloads")
    #[arg(short, long, env = "RIS_DOWNLOADS")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) downloads: Option<String>,

    /// Config file path (default: "config.toml")
    #[arg(short, long, env = "RIS_CONFIG")]
    #[serde(skip_serializing)]
    pub(crate) config: Option<String>,

    /// RustyPaste API token
    #[arg(long, env = "RIS_RUSTYPASTE_TOKEN")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) rustypaste_token: Option<String>,

    /// RustyPaste base URL
    #[arg(long, env = "RIS_RUSTYPASTE_BASE_URL")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) rustypaste_base_url: Option<String>,

    /// RustyPaste expiry, format: https://github.com/orhun/rustypaste#expiration (default: 7d)
    #[arg(long, env = "RIS_RUSTYPASTE_EXPIRY")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) rustypaste_expiry: Option<String>,

    /// TraceMoe API token
    #[arg(long, env = "RIS_TRACEMOE_token")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) tracemoe_token: Option<String>,

    /// TraceMoe Threshold (default : 0.95)
    #[arg(long, env = "RIS_TRACEMOE_THRESHOLD")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) tracemoe_threshold: Option<f32>,

    /// TraceMoe Limit (default: 3)
    #[arg(long, env = "RIS_TRACEMOE_LIMIT")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) tracemoe_limit: Option<usize>,

    /// Disable TraceMoe
    #[arg(long, env = "RIS_TRACEMOE_DISABLED")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) tracemoe_disabled: Option<bool>,

    /// IQDB Threshold (default : 0.95)
    #[arg(long, env = "RIS_IQDB_THRESHOLD")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) iqdb_threshold: Option<f32>,

    /// IQDB Limit (default: 3)
    #[arg(long, env = "RIS_IQDB_LIMIT")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) iqdb_limit: Option<usize>,

    /// Disable IQDB
    #[arg(long, env = "RIS_IQDB_DISABLED")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) iqdb_disabled: Option<bool>,

    /// SauceNao API token
    #[arg(long, env = "RIS_SAUCENAO_token")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) saucenao_token: Option<String>,

    /// SauceNao Threshold (default : 0.95)
    #[arg(long, env = "RIS_SAUCENAO_THRESHOLD")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) saucenao_threshold: Option<f32>,

    /// SauceNao Limit (default: 3)
    #[arg(long, env = "RIS_SAUCENAO_LIMIT")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) saucenao_limit: Option<usize>,

    /// Disable SauceNao
    #[arg(long, env = "RIS_SAUCENAO_DISABLED")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) saucenao_disabled: Option<bool>,

    /// Danbooru API
    #[arg(long, env = "RIS_DANBOORU_token")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) danbooru_token: Option<String>,

    /// Danbooru Username
    #[arg(long, env = "RIS_DANBOORU_USERNAME")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) danbooru_username: Option<String>,

    /// Disable Danbooru
    #[arg(long, env = "RIS_DANBOORU_DISABLED")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) danbooru_disabled: Option<bool>,

    /// Disable Gelbooru
    #[arg(long, env = "RIS_GELBOORU_DISABLED")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) gelbooru_disabled: Option<bool>,

    /// Disable Safebooru
    #[arg(long, env = "RIS_SAFEBOORU_DISABLED")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) safebooru_disabled: Option<bool>,

    /// Disable Anilist
    #[arg(long, env = "RIS_ANILIST_DISABLED")]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) anilist_disabled: Option<bool>,
}

impl CliArgs {
    pub fn to_config(self) -> Config {
        Config {
            general: General {
                downloads_dir: self.downloads.and_then(|p| Some(PathBuf::from(p))),
            },
            telegram: Telegram { token: self.token },
            rustypaste: RustyPaste {
                token: self.rustypaste_token,
                url: self.rustypaste_base_url,
                expiry: self.rustypaste_expiry,
            },
            tracemoe: TraceMoe {
                token: self.tracemoe_token,
                threshold: self.tracemoe_threshold,
                limit: self.tracemoe_limit,
                enabled: self.tracemoe_disabled.and_then(|b| Some(!b)),
            },
            iqdb: Iqdb {
                threshold: self.iqdb_threshold,
                limit: self.iqdb_limit,
                enabled: self.iqdb_disabled.and_then(|b| Some(!b)),
            },
            saucenao: SauceNao {
                token: self.saucenao_token,
                threshold: self.saucenao_threshold,
                limit: self.saucenao_limit,
                enabled: self.saucenao_disabled.and_then(|b| Some(!b)),
            },
            danbooru: Danbooru {
                token: self.danbooru_token,
                username: self.danbooru_username,
                enabled: self.danbooru_disabled.and_then(|b| Some(!b)),
            },
            gelbooru: Gelbooru {
                enabled: self.gelbooru_disabled.and_then(|b| Some(!b)),
            },
            safebooru: Safebooru {
                enabled: self.safebooru_disabled.and_then(|b| Some(!b)),
            },
            anilist: AniList {
                enabled: self.anilist_disabled.and_then(|b| Some(!b)),
            },
        }
    }
}
