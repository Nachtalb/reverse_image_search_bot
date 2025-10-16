use std::path::PathBuf;

use clap::Parser;
use figment::{
    Figment,
    providers::{Format, Json, Serialized, Toml, Yaml},
};
use normalize_path::NormalizePath;
use resolve_path::PathResolveExt;
use serde::{Deserialize, Serialize};
use tokio::sync::OnceCell;

use crate::cli::CliArgs;

const DEFAULT_CONFIG_PATH: &str = "config.toml";
static CONFIG: OnceCell<Config> = OnceCell::const_new();

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct General {
    /// Path to store downloads
    #[serde(skip_serializing_if = "Option::is_none")]
    pub downloads_dir: Option<std::path::PathBuf>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Telegram {
    /// Telegram bot token
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct RustyPaste {
    /// RustyPaste API token
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    /// RustyPaste base URL
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    /// RustyPaste expiry, format: https://github.com/orhun/rustypaste#expiration
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expiry: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct TraceMoe {
    /// TraceMoe API token
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    /// TraceMoe Default Threshold
    #[serde(skip_serializing_if = "Option::is_none")]
    pub threshold: Option<f32>,
    /// TraceMoe Default Limit
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit: Option<usize>,
    /// TraceMoe Enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Iqdb {
    /// Iqdb Default Threshold
    #[serde(skip_serializing_if = "Option::is_none")]
    pub threshold: Option<f32>,
    /// Iqdb Default Limit
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit: Option<usize>,
    /// Iqdb Enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct SauceNao {
    /// SauceNao API token
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    /// SauceNao Default Threshold
    #[serde(skip_serializing_if = "Option::is_none")]
    pub threshold: Option<f32>,
    /// SauceNao Default Limit
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit: Option<usize>,
    /// SauceNao Enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Danbooru {
    /// Danbooru API token
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    /// Danbooru Username
    #[serde(skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
    /// Danbooru Enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Gelbooru {
    /// Gelbooru Enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Safebooru {
    /// Safebooru Enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct AniList {
    /// AniList Enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct Config {
    pub general: General,
    pub telegram: Telegram,
    pub rustypaste: RustyPaste,
    pub tracemoe: TraceMoe,
    pub iqdb: Iqdb,
    pub saucenao: SauceNao,
    pub danbooru: Danbooru,
    pub gelbooru: Gelbooru,
    pub safebooru: Safebooru,
    pub anilist: AniList,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            general: General {
                downloads_dir: Some(PathBuf::from("./downloads")),
            },
            telegram: Telegram { token: None },
            rustypaste: RustyPaste {
                token: None,
                url: None,
                expiry: None,
            },
            tracemoe: TraceMoe {
                token: None,
                threshold: Some(0.95),
                limit: Some(3),
                enabled: Some(true),
            },
            iqdb: Iqdb {
                threshold: Some(95.0),
                limit: Some(3),
                enabled: Some(true),
            },
            saucenao: SauceNao {
                token: None,
                threshold: Some(65.0),
                limit: Some(3),
                enabled: Some(true),
            },
            danbooru: Danbooru {
                token: None,
                username: None,
                enabled: Some(true),
            },
            gelbooru: Gelbooru {
                enabled: Some(true),
            },
            safebooru: Safebooru {
                enabled: Some(true),
            },
            anilist: AniList {
                enabled: Some(true),
            },
        }
    }
}

impl Config {
    fn normalize(&mut self) {
        self.general.downloads_dir = self
            .general
            .downloads_dir
            .clone()
            .map(|p| p.resolve().normalize());
    }

    fn validate(&self) -> Result<(), Vec<String>> {
        let mut errors: Vec<String> = vec![];
        if self.telegram.token.is_none() {
            errors.push("Telegram token is required".to_string());
        }

        if self.general.downloads_dir.is_none() {
            errors.push("Downloads path is required".to_string());
        }

        if self.rustypaste.url.is_none() {
            errors.push("RustyPaste base URL is required".to_string());
        }

        if !self.tracemoe.enabled.unwrap_or(true) {
            log::warn!("TraceMoe is disabled");
        }

        if !self.iqdb.enabled.unwrap_or(true) {
            log::warn!("IQDB is disabled");
        }

        if !self.saucenao.enabled.unwrap_or(true) {
            log::warn!("SauceNao is disabled");
        }

        if !self.danbooru.enabled.unwrap_or(true) {
            log::warn!("Danbooru is disabled");
        }

        if !self.gelbooru.enabled.unwrap_or(true) {
            log::warn!("Gelbooru is disabled");
        }

        if !self.safebooru.enabled.unwrap_or(true) {
            log::warn!("Safebooru is disabled");
        }

        if !self.anilist.enabled.unwrap_or(true) {
            log::warn!("AniList is disabled");
        }

        if !errors.is_empty() {
            Err(errors)
        } else {
            Ok(())
        }
    }
}

pub(crate) fn get_config() -> &'static Config {
    if !CONFIG.initialized() {
        let config = load_config();
        CONFIG.set(config).unwrap();
    }

    CONFIG.get().unwrap()
}

fn load_config() -> Config {
    log::debug!("Parsing CLI args...");
    let args = CliArgs::parse();

    let mut figment = Figment::from(Serialized::defaults(Config::default()));

    let config_path = std::path::PathBuf::from(
        &args
            .config
            .clone()
            .unwrap_or(DEFAULT_CONFIG_PATH.to_string()),
    );

    if config_path.exists() {
        log::info!("Config file found: {}", config_path.display());
        match config_path.extension() {
            Some(ext) => match ext.to_str() {
                Some("toml") => figment = figment.admerge(Toml::file(config_path)),
                Some("json") => figment = figment.admerge(Json::file(config_path)),
                Some("yaml") | Some("yml") => figment = figment.admerge(Yaml::file(config_path)),
                _ => {
                    log::error!("Cannot identify config file type. Must be .toml, .json or .yaml");
                    std::process::exit(1);
                }
            },
            None => {
                log::error!("Cannot identify config file type. Must be .toml, .json or .yaml");
                std::process::exit(1);
            }
        };
    } else if config_path.to_str() != Some(DEFAULT_CONFIG_PATH) {
        log::warn!("Config file not found: {}", config_path.display());
        std::process::exit(1);
    };

    let mut config: Config = match figment
        .admerge(Serialized::defaults(args.to_config()))
        .extract()
    {
        Ok(config) => config,
        Err(err) => {
            log::error!("{}", err);
            std::process::exit(1);
        }
    };

    log::debug!("Loaded config: {:#?}", config);

    config.normalize();
    match config.validate() {
        Ok(_) => config,
        Err(err) => {
            log::error!("{}", err.join("\n"));
            std::process::exit(1);
        }
    }
}
