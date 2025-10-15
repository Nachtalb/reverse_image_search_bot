use crate::models::Enrichment;
use crate::transformers::tagify;

pub fn format(data: &Enrichment) -> String {
    let mut ret = String::new();

    ret.push_str(
        format!(
            "Data from: {}\n",
            data.enrichers
                .iter()
                .map(String::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        )
        .as_str(),
    );

    if let Some(title) = &data.title {
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

    if let Some(episodes) = &data.episodes {
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

    if let Some(chapters) = &data.chapters {
        if chapters.total.is_some() && chapters.hit.is_some() {
            ret.push_str(&format!(
                "Chapter: <code>{}/{}</code>\n",
                chapters.hit.unwrap(),
                chapters.total.unwrap()
            ));
        } else if chapters.total.is_some() {
            ret.push_str(&format!(
                "Chapters: <code>{}</code>\n",
                chapters.total.unwrap()
            ));
        } else if chapters.hit.is_some() {
            ret.push_str(&format!(
                "Chapter: <code>{}</code>\n",
                chapters.hit.unwrap()
            ));
        }
    }

    if let Some(status) = &data.status {
        ret.push_str(&format!("Status: <code>{}</code>\n", status));
    }

    if let Some(artist) = &data.artists {
        ret.push_str(&format!("Artist: {}\n", tagify(artist, false)));
    }

    if let Some(tags) = &data.tags {
        ret.push_str(&format!("Tags: {}\n", tagify(tags, false)));
    }

    if let Some(characters) = &data.characters {
        ret.push_str(&format!("characters: {}\n", tagify(characters, false)));
    }

    ret
}
