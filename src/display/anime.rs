use crate::models::AnimeData;
use crate::transformers::tagify;

pub fn format(anime: &AnimeData) -> String {
    let mut ret = String::new();

    if let Some(title) = &anime.title {
        if let Some(english) = &title.english {
            ret.push_str(&format!("Title: <code>{}</code>\n", english));
        }
        if let Some(romaji) = &title.romaji {
            ret.push_str(&format!("Title [romaji]: <code>{}</code>\n", romaji));
        }
        if let Some(native) = &title.native {
            ret.push_str(&format!("Title [native]: <code>{}</code>\n", native));
        }
    }

    if let Some(episodes) = &anime.episodes {
        if episodes.total.is_some() && episodes.hit.is_some() {
            ret.push_str(&format!(
                "Episode: <code>{}/{}</code>",
                episodes.hit.unwrap(),
                episodes.total.unwrap()
            ));

            if let Some(timestamp) = episodes.hit_timestamp {
                ret.push_str(&format!(" (at <code>{}s</code>)", timestamp as u64));
            }
        } else if episodes.total.is_some() {
            ret.push_str(&format!(
                "Episodes: <code>{}</code>",
                episodes.total.unwrap()
            ));
        } else if episodes.hit.is_some() {
            ret.push_str(&format!("Episode: <code>{}</code>", episodes.hit.unwrap()));

            if let Some(timestamp) = episodes.hit_timestamp {
                ret.push_str(&format!(" (at <code>{}s</code>)", timestamp as u64));
            }
        }

        if episodes.total.is_some() || episodes.hit.is_some() {
            ret.push('\n');
        }
    }
    if let Some(status) = &anime.status {
        ret.push_str(&format!("Status: <code>{}</code>\n", status));
    }
    ret.push_str("Type: <code>ANIME</code>\n");
    if let Some(year) = anime.year {
        ret.push_str(&format!("Year: <code>{}</code>\n", year));
    }
    if let Some(tags) = &anime.tags {
        ret.push_str(&format!("Tags: {}\n", tagify(tags, false)));
    }

    ret
}
