use crate::config::get_config;

fn ensure_downloads_dir() -> std::path::PathBuf {
    let config = get_config();
    let dir = config.general.downloads_dir.clone().unwrap();
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

pub(crate) fn download_path(filename: String) -> std::path::PathBuf {
    ensure_downloads_dir().join(filename.as_str())
}
