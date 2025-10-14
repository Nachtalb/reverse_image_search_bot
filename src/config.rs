use clap::Parser;
use figment::{
    Figment,
    providers::{Format, Json, Serialized, Toml, Yaml},
};
use normalize_path::NormalizePath;
use resolve_path::PathResolveExt;
use serde::{Deserialize, Serialize};
use tokio::sync::OnceCell;

const DEFAULT_CONFIG_PATH: &str = "config.toml";
static CONFIG: OnceCell<Config> = OnceCell::const_new();

#[derive(Parser, Serialize, Debug)]
struct CliArgs {
    /// Telegram bot token
    #[arg(short, long, env = "RIS_TELEGRAM_TOKEN")]
    #[serde(skip_serializing_if = "Option::is_none")]
    token: Option<String>,

    /// Downloads directory (default: "downloads")
    #[arg(short, long, env = "RIS_DOWNLOADS")]
    #[serde(skip_serializing_if = "Option::is_none")]
    downloads: Option<String>,

    /// Config file path (default: "config.toml")
    #[arg(short, long, env = "RIS_CONFIG")]
    #[serde(skip_serializing)]
    config: Option<String>,

    /// RustyPaste API token
    #[arg(long, env = "RIS_RUSTYPASTE_TOKEN")]
    #[serde(skip_serializing_if = "Option::is_none")]
    rustypaste_token: Option<String>,

    /// RustyPaste base URL
    #[arg(long, env = "RIS_RUSTYPASTE_BASE_URL")]
    #[serde(skip_serializing_if = "Option::is_none")]
    rustypaste_base_url: Option<String>,

    /// RustyPaste expiry, format: https://github.com/orhun/rustypaste#expiration (default: 7d)
    #[arg(long, env = "RIS_RUSTYPASTE_EXPIRY")]
    #[serde(skip_serializing_if = "Option::is_none")]
    rustypaste_expiry: Option<String>,

    /// TraceMoe API key
    #[arg(long, env = "RIS_TRACEMOE_API_KEY")]
    #[serde(skip_serializing_if = "Option::is_none")]
    tracemoe_api_key: Option<String>,

    /// TraceMoe Threshold (default : 0.95)
    #[arg(long, env = "RIS_TRACEMOE_THRESHOLD")]
    #[serde(skip_serializing_if = "Option::is_none")]
    tracemoe_threshold: Option<f32>,

    /// TraceMoe Limit (default: 3)
    #[arg(long, env = "RIS_TRACEMOE_LIMIT")]
    #[serde(skip_serializing_if = "Option::is_none")]
    tracemoe_limit: Option<usize>,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct Config {
    /// Telegram bot token
    pub(crate) token: String,
    /// Downloads directory
    pub downloads: std::path::PathBuf,

    /// RustyPaste API token
    pub rustypaste_token: Option<String>,
    /// RustyPaste base URL
    pub rustypaste_base_url: Option<String>,
    /// RustyPaste expiry, format: https://github.com/orhun/rustypaste#expiration
    pub rustypaste_expiry: Option<String>,

    /// TraceMoe API key
    pub tracemoe_api_key: Option<String>,
    /// TraceMoe Default Threshold
    pub tracemoe_threshold: Option<f32>,
    /// TraceMoe Default Limit
    pub tracemoe_limit: Option<usize>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            token: String::from(""),
            downloads: std::path::PathBuf::from("./downloads"),
            rustypaste_token: None,
            rustypaste_base_url: None,
            rustypaste_expiry: None,
            tracemoe_api_key: None,
            tracemoe_threshold: Some(0.95),
            tracemoe_limit: Some(3),
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
                Some("yaml") => figment = figment.admerge(Yaml::file(config_path)),
                Some("yml") => figment = figment.admerge(Yaml::file(config_path)),
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

    let mut config: Config = match figment.admerge(Serialized::defaults(args)).extract() {
        Ok(config) => config,
        Err(err) => {
            log::error!("{}", err);
            std::process::exit(1);
        }
    };

    log::debug!("Loaded config: {:#?}", config);

    config.downloads = config.downloads.resolve().normalize();

    config
}
