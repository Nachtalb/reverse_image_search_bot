use crate::transformers::titleize;
use regex::Regex;
use reqwest::Url;

fn re_find(regex: &str, input: &str) -> Option<String> {
    let re = Regex::new(regex).unwrap();
    re.captures(input)
        .and_then(|caps| caps.get(1).map(|m| m.as_str().to_string()))
}

#[derive(Debug, Clone, PartialEq)]
pub enum Service {
    Danbooru,
    Safebooru,
    Gelbooru,
    Konachan,
    YandeRe,
    Zerochan,
    AnimePictures,
    IdolComplex,
    SankakuComplex,
    EShuushuu,
    MangaDex,
    MangaDexChapter,
    MangaUpdates,
    MyAnimeList,
    Fakku,
    EHentai,
    AniDB,
    AniList,
    PixivMember,
    PixivArtwork,
    XUser,
    XStatus,
    Unknown(String),
}

impl Service {
    pub fn name(&self) -> String {
        match self {
            Service::Danbooru => "Danbooru".to_string(),
            Service::Safebooru => "Safebooru".to_string(),
            Service::Gelbooru => "Gelbooru".to_string(),
            Service::Konachan => "Konachan".to_string(),
            Service::YandeRe => "Yande.re".to_string(),
            Service::Zerochan => "Zerochan".to_string(),
            Service::AnimePictures => "Anime-Pictures".to_string(),
            Service::IdolComplex => "Idol Complex".to_string(),
            Service::SankakuComplex => "Sankaku Complex".to_string(),
            Service::EShuushuu => "E-Shuushuu".to_string(),
            Service::MangaDex => "MangaDex".to_string(),
            Service::MangaDexChapter => "MangaDexChapter".to_string(),
            Service::MangaUpdates => "Manga Updates".to_string(),
            Service::MyAnimeList => "MyAnimeList".to_string(),
            Service::Fakku => "Fakku".to_string(),
            Service::EHentai => "E-Hentai".to_string(),
            Service::AniDB => "AniDB".to_string(),
            Service::AniList => "AniList".to_string(),
            Service::PixivMember => "Pixiv User".to_string(),
            Service::PixivArtwork => "Pixiv Artwork".to_string(),
            Service::XUser => "X User".to_string(),
            Service::XStatus => "X Status".to_string(),
            Service::Unknown(host) => {
                titleize(&host.rsplit('.').next().unwrap_or(host).replace('-', " "))
            }
        }
    }

    pub fn emoji(&self) -> char {
        match self {
            Service::Danbooru | Service::Safebooru => '📦',
            Service::PixivMember | Service::PixivArtwork => '🅿',
            Service::XUser | Service::XStatus => '𝕏',
            Service::Gelbooru => '🖼',
            Service::Konachan => '🌸',
            Service::EHentai => '🔞',
            Service::MyAnimeList => '📺',
            Service::AniList => '🎬',
            Service::AniDB => '🗄',
            Service::MangaDex | Service::MangaDexChapter | Service::MangaUpdates => '📚',
            Service::Fakku => '💋',
            _ => '🔗',
        }
    }

    pub fn key(&self) -> String {
        match self {
            Service::Danbooru => "danbooru".to_string(),
            Service::Safebooru => "safebooru".to_string(),
            Service::Gelbooru => "gelbooru".to_string(),
            Service::Konachan => "konachan".to_string(),
            Service::YandeRe => "yandere".to_string(),
            Service::Zerochan => "zerochan".to_string(),
            Service::AnimePictures => "anime-pictures".to_string(),
            Service::IdolComplex => "idolcomplex".to_string(),
            Service::SankakuComplex => "sankakucomplex".to_string(),
            Service::EShuushuu => "eshuushuu".to_string(),
            Service::MangaDex => "mangadex".to_string(),
            Service::MangaDexChapter => "mangadex-chapter".to_string(),
            Service::MangaUpdates => "mangaupdates".to_string(),
            Service::MyAnimeList => "myanimelist".to_string(),
            Service::Fakku => "fakku".to_string(),
            Service::EHentai => "ehentai-gallery".to_string(),
            Service::AniDB => "anidb".to_string(),
            Service::AniList => "anilist".to_string(),
            Service::PixivMember => "pixiv-member".to_string(),
            Service::PixivArtwork => "pixiv".to_string(),
            Service::XUser => "x-user".to_string(),
            Service::XStatus => "x-status".to_string(),
            Service::Unknown(host) => format!("unknown-{}", host.to_lowercase()),
        }
    }

    pub fn from_url(url_str: &str) -> Service {
        let url = match Url::parse(url_str) {
            Ok(u) => u,
            Err(_) => return Service::Unknown(url_str.to_string()),
        };
        let host = match url.host_str() {
            Some(h) => h.to_string(),
            None => return Service::Unknown(url_str.to_string()),
        };
        let path = url.path();
        let segments: Vec<_> = url.path_segments().unwrap().collect();

        match host.as_str() {
            h if h.contains("danbooru.donmai.us") => Service::Danbooru,
            h if h.contains("safebooru.org") => Service::Safebooru,
            h if h.contains("gelbooru.com") => Service::Gelbooru,
            h if h.contains("konachan.com") => Service::Konachan,
            h if h.contains("yande.re") => Service::YandeRe,
            h if h.contains("zerochan.net") => Service::Zerochan,
            h if h.contains("anime-pictures.net") => Service::AnimePictures,
            h if h.contains("idolcomplex.com") || h.contains("idol.sankakucomplex.com") => {
                Service::IdolComplex
            }
            h if h.contains("sankakucomplex.com") => Service::SankakuComplex,
            h if h.contains("e-shuushuu.net") => Service::EShuushuu,
            h if h.contains("mangadex.org") && path.contains("title") => Service::MangaDex,
            h if h.contains("mangadex.org") && path.contains("chapter") => Service::MangaDexChapter,
            h if h.contains("mangaupdates.com") => Service::MangaUpdates,
            h if h.contains("myanimelist.net") => Service::MyAnimeList,
            h if h.contains("fakku.net") => Service::Fakku,
            h if h.contains("e-hentai.org") => Service::EHentai,
            h if h.contains("anidb.net") => Service::AniDB,
            h if h.contains("anilist.co") => Service::AniList,
            h if (h.contains("pixiv.net") && path.contains("artworks"))
                || h.contains("pximg.net") =>
            {
                Service::PixivArtwork
            }
            h if h.contains("pixiv.net") && path.contains("users") => Service::PixivMember,
            h if (h == "twitter.com" || h == "x.com") && path.contains("status") => {
                Service::XStatus
            }
            h if (h == "twitter.com" || h == "x.com") && segments.len() == 1 => Service::XUser,
            _ => Service::Unknown(host),
        }
    }

    pub fn get_id(&self, url_str: &str) -> Option<String> {
        let url = Url::parse(url_str).ok()?;
        let host = url.host_str()?;
        let path = url.path();
        let query_id = url
            .query_pairs()
            .find(|(k, _)| k == "id")
            .map(|(_, v)| v.to_string());
        let segments: Vec<_> = url.path_segments().unwrap().collect();

        match self {
            Service::Safebooru | Service::Gelbooru => query_id,
            Service::Danbooru | Service::Konachan | Service::YandeRe | Service::AnimePictures => {
                re_find(r"/posts?(?:/show)?/(\d+)", path)
            }
            Service::Zerochan => Some(path.trim_start_matches('/').to_string()),
            Service::IdolComplex | Service::SankakuComplex => {
                re_find(r"/posts?/([a-zA-Z-0-9]+)", path)
            }
            Service::EShuushuu => re_find(r"/image/(\d+)", path),
            Service::MangaDex => re_find(r"/title/([a-zA-Z-0-9]+)", path),
            Service::MangaDexChapter => re_find(r"/chapter/([a-zA-Z-0-9]+)", path),
            Service::MangaUpdates => query_id.or_else(|| re_find(r"/series/([a-zA-Z-0-9]+)", path)),
            Service::MyAnimeList => re_find(r"/anime/(\d+)", path),
            Service::Fakku => re_find(r"/hentai/([a-zA-Z-0-9]+)", path),
            Service::EHentai => re_find(r"/g/([a-zA-Z-0-9]+/[a-zA-Z-0-9]+)", path),
            Service::AniDB => re_find(r"/anime/(\d+)", path),
            Service::AniList => re_find(r"/anime/(\d+)", path),
            Service::PixivMember => re_find(r"/users/(\d+)", path),
            Service::PixivArtwork => {
                if host.contains("pixiv.net") {
                    re_find(r"/artworks/(\d+)", path)
                } else {
                    re_find(r"(\d+)_p\d", path)
                }
            }
            Service::XUser => {
                if segments.len() == 1 {
                    segments.first().map(|s| s.to_string())
                } else {
                    None
                }
            }
            Service::XStatus => re_find(r"/status/(\d+)", path),
            Service::Unknown(_) => None,
        }
    }

    pub fn parse_url(url_str: &str) -> Option<(Service, String)> {
        let service = Service::from_url(url_str);
        let id = service.get_id(url_str);
        id.map(|id| (service, id))
    }

    pub fn from_string(key: &str) -> Option<Service> {
        let binding = key
            .strip_suffix("_id")
            .unwrap_or(key.strip_suffix("-id").unwrap_or(key))
            .to_lowercase()
            .replace('_', "-");
        let normalized = binding.as_str();

        match normalized {
            "danbooru" => Some(Service::Danbooru),
            "safebooru" => Some(Service::Safebooru),
            "gelbooru" => Some(Service::Gelbooru),
            "konachan" => Some(Service::Konachan),
            "yandere" => Some(Service::YandeRe),
            "zerochan" => Some(Service::Zerochan),
            "anime-pictures" => Some(Service::AnimePictures),
            "idolcomplex" => Some(Service::IdolComplex),
            "sankakucomplex" => Some(Service::SankakuComplex),
            "eshuushuu" => Some(Service::EShuushuu),
            "mangadex" => Some(Service::MangaDex),
            "mangadex-chapter" => Some(Service::MangaDexChapter),
            "mangaupdates" => Some(Service::MangaUpdates),
            "myanimelist" => Some(Service::MyAnimeList),
            "fakku" => Some(Service::Fakku),
            "ehentai-gallery" => Some(Service::EHentai),
            "anidb" => Some(Service::AniDB),
            "anilist" => Some(Service::AniList),
            "pixiv-user" | "pixiv-artist" | "pixiv-member" => Some(Service::PixivMember),
            "pixiv-artwork" | "pixiv" => Some(Service::PixivArtwork),
            "x-user" => Some(Service::XUser),
            "x-status" => Some(Service::XStatus),
            id if id.starts_with("unknown-") => Some(Service::Unknown(id[8..].to_string())),
            _ => None,
        }
    }

    pub fn build_url(&self, id: &str) -> Option<String> {
        match self {
            Service::Danbooru => Some(format!("https://danbooru.donmai.us/posts/{}", id)),
            Service::Safebooru => Some(format!(
                "https://safebooru.org/index.php?page=post&s=view&id={}",
                id
            )),
            Service::Gelbooru => Some(format!(
                "https://gelbooru.com/index.php?page=post&s=view&id={}",
                id
            )),
            Service::Konachan => Some(format!("https://konachan.com/post/show/{}", id)),
            Service::YandeRe => Some(format!("https://yande.re/post/show/{}", id)),
            Service::Zerochan => Some(format!("https://www.zerochan.net/{}", id)),
            Service::AnimePictures => Some(format!("https://anime-pictures.net/posts/{}", id)),
            Service::IdolComplex => Some(format!("https://www.idolcomplex.com/posts/{}", id)),
            Service::SankakuComplex => Some(format!("https://www.sankakucomplex.com/posts/{}", id)),
            Service::EShuushuu => Some(format!("https://e-shuushuu.net/image/{}", id)),
            Service::MangaDex => Some(format!("https://mangadex.org/title/{}", id)),
            Service::MangaDexChapter => Some(format!("https://mangadex.org/chapter/{}", id)),
            Service::MangaUpdates => {
                if id.parse::<u64>().is_ok() {
                    Some(format!(
                        "https://www.mangaupdates.com/series.html?id={}",
                        id
                    ))
                } else {
                    Some(format!("https://www.mangaupdates.com/series/{}", id))
                }
            }
            Service::MyAnimeList => Some(format!("https://myanimelist.net/anime/{}", id)),
            Service::Fakku => Some(format!("https://www.fakku.net/hentai/{}", id)),
            Service::EHentai => {
                if let Some((gid, token)) = id.split_once('/') {
                    Some(format!("https://e-hentai.org/g/{}/{}", gid, token))
                } else {
                    None
                }
            }
            Service::AniDB => Some(format!("https://anidb.net/anime/{}", id)),
            Service::AniList => Some(format!("https://anilist.co/anime/{}", id)),
            Service::PixivMember => Some(format!("https://www.pixiv.net/en/users/{}", id)),
            Service::PixivArtwork => Some(format!("https://www.pixiv.net/en/artworks/{}", id)),
            Service::XUser => Some(format!("https://x.com/{}", id)),
            Service::XStatus => Some(format!("https://x.com/i/status/{}", id)),
            Service::Unknown(host) => Some(format!("https://{}/{}", host, id)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_every_key() {
        let mut key = Service::Danbooru.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::Danbooru));
        key = Service::Safebooru.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::Safebooru));
        key = Service::Gelbooru.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::Gelbooru));
        key = Service::Konachan.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::Konachan));
        key = Service::YandeRe.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::YandeRe));
        key = Service::Zerochan.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::Zerochan));
        key = Service::AnimePictures.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::AnimePictures)
        );
        key = Service::IdolComplex.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::IdolComplex)
        );
        key = Service::SankakuComplex.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::SankakuComplex)
        );
        key = Service::EShuushuu.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::EShuushuu));
        key = Service::MangaDex.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::MangaDex));
        key = Service::MangaDexChapter.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::MangaDexChapter)
        );
        key = Service::MangaUpdates.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::MangaUpdates)
        );
        key = Service::MyAnimeList.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::MyAnimeList)
        );
        key = Service::Fakku.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::Fakku));
        key = Service::EHentai.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::EHentai));
        key = Service::AniDB.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::AniDB));
        key = Service::AniList.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::AniList));
        key = Service::PixivMember.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::PixivMember)
        );
        key = Service::PixivArtwork.key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::PixivArtwork)
        );
        key = Service::XUser.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::XUser));
        key = Service::XStatus.key();
        assert_eq!(Service::from_string(key.as_str()), Some(Service::XStatus));
        key = Service::Unknown("example.com".to_string()).key();
        assert_eq!(
            Service::from_string(key.as_str()),
            Some(Service::Unknown("example.com".to_string()))
        );
    }

    #[test]
    fn test_danbooru_parsing() {
        assert_eq!(
            Service::from_url("https://danbooru.donmai.us/posts/1234"),
            Service::Danbooru
        );
        assert_eq!(
            Service::from_url("https://danbooru.donmai.us/posts/show/1234"),
            Service::Danbooru
        );
    }

    #[test]
    fn test_danbooru_id() {
        assert_eq!(
            Service::Danbooru.get_id("https://danbooru.donmai.us/posts/1234"),
            Some("1234".to_string())
        );
        assert_eq!(
            Service::Danbooru.get_id("https://danbooru.donmai.us/posts/show/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_danbooru_url_builder() {
        assert_eq!(
            Service::Danbooru.build_url("1234"),
            Some("https://danbooru.donmai.us/posts/1234".to_string())
        );
    }

    #[test]
    fn test_danbooru_from_id() {
        assert_eq!(Service::from_string("danbooru"), Some(Service::Danbooru));
        assert_eq!(Service::from_string("danbooru_id"), Some(Service::Danbooru));
        assert_eq!(Service::from_string("danbooru-id"), Some(Service::Danbooru));
    }

    #[test]
    fn test_safebooru_parsing() {
        assert_eq!(
            Service::from_url("https://safebooru.org/index.php?page=post&s=view&id=1234"),
            Service::Safebooru
        );
    }

    #[test]
    fn test_safebooru_id() {
        assert_eq!(
            Service::Safebooru.get_id("https://safebooru.org/index.php?page=post&s=view&id=1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_safebooru_url_builder() {
        assert_eq!(
            Service::Safebooru.build_url("1234"),
            Some("https://safebooru.org/index.php?page=post&s=view&id=1234".to_string())
        );
    }

    #[test]
    fn test_gelbooru_parsing() {
        assert_eq!(
            Service::from_url("https://gelbooru.com/index.php?page=post&s=view&id=1234"),
            Service::Gelbooru
        );
    }

    #[test]
    fn test_gelbooru_id() {
        assert_eq!(
            Service::Gelbooru.get_id("https://gelbooru.com/index.php?page=post&s=view&id=1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_gelbooru_url_builder() {
        assert_eq!(
            Service::Gelbooru.build_url("1234"),
            Some("https://gelbooru.com/index.php?page=post&s=view&id=1234".to_string())
        );
    }

    #[test]
    fn test_konachan_parsing() {
        assert_eq!(
            Service::from_url("https://konachan.com/post/show/1234"),
            Service::Konachan
        );
    }

    #[test]
    fn test_konachan_id() {
        assert_eq!(
            Service::Konachan.get_id("https://konachan.com/post/show/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_konachan_url_builder() {
        assert_eq!(
            Service::Konachan.build_url("1234"),
            Some("https://konachan.com/post/show/1234".to_string())
        );
    }

    #[test]
    fn test_yandere_parsing() {
        assert_eq!(
            Service::from_url("https://yande.re/post/show/1234"),
            Service::YandeRe
        );
    }

    #[test]
    fn test_yandere_id() {
        assert_eq!(
            Service::YandeRe.get_id("https://yande.re/post/show/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_yandere_url_builder() {
        assert_eq!(
            Service::YandeRe.build_url("1234"),
            Some("https://yande.re/post/show/1234".to_string())
        );
    }

    #[test]
    fn test_zerochan_parsing() {
        assert_eq!(
            Service::from_url("https://www.zerochan.net/1234"),
            Service::Zerochan
        );
    }

    #[test]
    fn test_zerochan_id() {
        assert_eq!(
            Service::Zerochan.get_id("https://www.zerochan.net/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_zerochan_url_builder() {
        assert_eq!(
            Service::Zerochan.build_url("1234"),
            Some("https://www.zerochan.net/1234".to_string())
        );
    }

    #[test]
    fn test_animepictures_parsing() {
        assert_eq!(
            Service::from_url("https://www.anime-pictures.net/pictures/view_post/1234"),
            Service::AnimePictures
        );
    }

    #[test]
    fn test_animepictures_id() {
        assert_eq!(
            Service::AnimePictures.get_id("https://anime-pictures.net/posts/1234?lang=en"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_animepictures_url_builder() {
        assert_eq!(
            Service::AnimePictures.build_url("1234"),
            Some("https://anime-pictures.net/posts/1234".to_string())
        );
    }

    #[test]
    fn test_idolcomplex_parsing() {
        assert_eq!(
            Service::from_url("https://idol.sankakucomplex.com/post/abcd"),
            Service::IdolComplex
        );
        assert_eq!(
            Service::from_url("https://www.idolcomplex.com/posts/abcd"),
            Service::IdolComplex
        );
    }

    #[test]
    fn test_idolcomplex_id() {
        assert_eq!(
            Service::IdolComplex.get_id("https://idol.sankakucomplex.com/post/abcd"),
            Some("abcd".to_string())
        );
        assert_eq!(
            Service::IdolComplex.get_id("https://wwww.idolcomplex.com/posts/abcd"),
            Some("abcd".to_string())
        );
    }

    #[test]
    fn test_idolcomplex_url_builder() {
        assert_eq!(
            Service::IdolComplex.build_url("abcd"),
            Some("https://www.idolcomplex.com/posts/abcd".to_string())
        );
    }

    #[test]
    fn test_sankakucomplex_parsing() {
        assert_eq!(
            Service::from_url("https://www.sankakucomplex.com/posts/1234"),
            Service::SankakuComplex
        );
        assert_eq!(
            Service::from_url("https://chan.sankakucomplex.com/post/1234"),
            Service::SankakuComplex
        );
    }

    #[test]
    fn test_sankakucomplex_id() {
        assert_eq!(
            Service::SankakuComplex.get_id("https://www.sankakucomplex.com/posts/1234"),
            Some("1234".to_string())
        );
        assert_eq!(
            Service::SankakuComplex.get_id("https://chan.sankakucomplex.com/post/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_sankakucomplex_url_builder() {
        assert_eq!(
            Service::SankakuComplex.build_url("1234"),
            Some("https://www.sankakucomplex.com/posts/1234".to_string())
        );
    }

    #[test]
    fn test_eshuushuu_parsing() {
        assert_eq!(
            Service::from_url("https://e-shuushuu.net/image/1234"),
            Service::EShuushuu
        );
    }

    #[test]
    fn test_eshuushuu_id() {
        assert_eq!(
            Service::EShuushuu.get_id("https://e-shuushuu.net/image/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_eshuushuu_url_builder() {
        assert_eq!(
            Service::EShuushuu.build_url("1234"),
            Some("https://e-shuushuu.net/image/1234".to_string())
        );
    }

    #[test]
    fn test_mangadex_parsing() {
        assert_eq!(
            Service::from_url("https://mangadex.org/title/abcd"),
            Service::MangaDex
        );
    }

    #[test]
    fn test_mangadex_id() {
        assert_eq!(
            Service::MangaDex.get_id("https://mangadex.org/title/abcd"),
            Some("abcd".to_string())
        );
    }

    #[test]
    fn test_mangadex_url_builder() {
        assert_eq!(
            Service::MangaDex.build_url("abcd"),
            Some("https://mangadex.org/title/abcd".to_string())
        );
    }

    #[test]
    fn test_mangaupdates_parsing() {
        assert_eq!(
            Service::from_url("https://www.mangaupdates.com/series.html?id=1234"),
            Service::MangaUpdates
        );
    }

    #[test]
    fn test_mangaupdates_id() {
        assert_eq!(
            Service::MangaUpdates.get_id("https://www.mangaupdates.com/series.html?id=1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_mangaupdates_url_builder() {
        assert_eq!(
            Service::MangaUpdates.build_url("1234"),
            Some("https://www.mangaupdates.com/series.html?id=1234".to_string())
        );
    }

    #[test]
    fn test_myanimelist_parsing() {
        assert_eq!(
            Service::from_url("https://myanimelist.net/anime/1234"),
            Service::MyAnimeList
        );
    }

    #[test]
    fn test_myanimelist_id() {
        assert_eq!(
            Service::MyAnimeList.get_id("https://myanimelist.net/anime/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_myanimelist_url_builder() {
        assert_eq!(
            Service::MyAnimeList.build_url("1234"),
            Some("https://myanimelist.net/anime/1234".to_string())
        );
    }

    #[test]
    fn test_fakku_parsing() {
        assert_eq!(
            Service::from_url("https://www.fakku.net/hentai/title-name"),
            Service::Fakku
        );
    }

    #[test]
    fn test_fakku_id() {
        assert_eq!(
            Service::Fakku.get_id("https://www.fakku.net/hentai/title-name"),
            Some("title-name".to_string())
        );
    }

    #[test]
    fn test_fakku_url_builder() {
        assert_eq!(
            Service::Fakku.build_url("title-name"),
            Some("https://www.fakku.net/hentai/title-name".to_string())
        );
    }

    #[test]
    fn test_ehentai_parsing() {
        assert_eq!(
            Service::from_url("https://e-hentai.org/g/1234/abcd"),
            Service::EHentai
        );
    }

    #[test]
    fn test_ehentai_id() {
        assert_eq!(
            Service::EHentai.get_id("https://e-hentai.org/g/1234/abcd"),
            Some("1234/abcd".to_string())
        );
    }

    #[test]
    fn test_ehentai_url_builder() {
        assert_eq!(
            Service::EHentai.build_url("1234/abcd"),
            Some("https://e-hentai.org/g/1234/abcd".to_string())
        );
    }

    #[test]
    fn test_anidb_parsing() {
        assert_eq!(
            Service::from_url("https://anidb.net/anime/1234"),
            Service::AniDB
        );
    }

    #[test]
    fn test_anidb_id() {
        assert_eq!(
            Service::AniDB.get_id("https://anidb.net/anime/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_anidb_url_builder() {
        assert_eq!(
            Service::AniDB.build_url("1234"),
            Some("https://anidb.net/anime/1234".to_string())
        );
    }

    #[test]
    fn test_anilist_parsing() {
        assert_eq!(
            Service::from_url("https://anilist.co/anime/1234"),
            Service::AniList
        );
    }

    #[test]
    fn test_anilist_id() {
        assert_eq!(
            Service::AniList.get_id("https://anilist.co/anime/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_anilist_url_builder() {
        assert_eq!(
            Service::AniList.build_url("1234"),
            Some("https://anilist.co/anime/1234".to_string())
        );
    }

    #[test]
    fn test_pixivmember_parsing() {
        assert_eq!(
            Service::from_url("https://www.pixiv.net/en/users/1234"),
            Service::PixivMember
        );
    }

    #[test]
    fn test_pixivmember_id() {
        assert_eq!(
            Service::PixivMember.get_id("https://www.pixiv.net/en/users/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_pixivmember_url_builder() {
        assert_eq!(
            Service::PixivMember.build_url("1234"),
            Some("https://www.pixiv.net/en/users/1234".to_string())
        );
    }

    #[test]
    fn test_pixivartwork_parsing() {
        assert_eq!(
            Service::from_url("https://www.pixiv.net/en/artworks/1234"),
            Service::PixivArtwork
        );
        assert_eq!(
            Service::from_url(
                "https://i.pximg.net/img-original/img/2025/02/19/22/15/44/127420438_p0.jpg"
            ),
            Service::PixivArtwork
        );
    }

    #[test]
    fn test_pixivartwork_id() {
        assert_eq!(
            Service::PixivArtwork.get_id("https://www.pixiv.net/en/artworks/1234"),
            Some("1234".to_string())
        );
        assert_eq!(
            Service::PixivArtwork.get_id(
                "https://i.pximg.net/img-original/img/2025/02/19/22/15/44/127420438_p0.jpg"
            ),
            Some("127420438".to_string())
        );
    }

    #[test]
    fn test_pixivartwork_url_builder() {
        assert_eq!(
            Service::PixivArtwork.build_url("1234"),
            Some("https://www.pixiv.net/en/artworks/1234".to_string())
        );
    }

    #[test]
    fn test_xuser_parsing() {
        assert_eq!(Service::from_url("https://x.com/1234"), Service::XUser);
    }

    #[test]
    fn test_xuser_id() {
        assert_eq!(
            Service::XUser.get_id("https://x.com/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_xuser_url_builder() {
        assert_eq!(
            Service::XUser.build_url("1234"),
            Some("https://x.com/1234".to_string())
        );
    }

    #[test]
    fn test_xstatus_parsing() {
        assert_eq!(
            Service::from_url("https://x.com/user/status/1234"),
            Service::XStatus
        );
    }

    #[test]
    fn test_xstatus_id() {
        assert_eq!(
            Service::XStatus.get_id("https://x.com/user/status/1234"),
            Some("1234".to_string())
        );
    }

    #[test]
    fn test_xstatus_url_builder() {
        assert_eq!(
            Service::XStatus.build_url("1234"),
            Some("https://x.com/i/status/1234".to_string())
        );
    }
}
