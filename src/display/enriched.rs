use crate::models::Enrichment;
use crate::transformers::tagify;

pub fn format(data: &Enrichment) -> String {
    let mut ret = String::new();

    ret.push_str(
        t!(
            "result.from",
            enrichers = data
                .enrichers
                .iter()
                .map(String::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        )
        .as_ref(),
    );
    ret.push('\n');

    if let Some(title) = &data.title {
        if let Some(english) = &title.english {
            ret.push_str(t!("result.title.en", title = english).as_ref());
            ret.push('\n');
        }
        if let Some(romaji) = &title.romaji {
            ret.push_str(t!("result.title.romaji", title = romaji).as_ref());
            ret.push('\n');
        }
        if let Some(native) = &title.native {
            ret.push_str(t!("result.title.nativ", title = native).as_ref());
            ret.push('\n');
        }
    }

    if let Some(episodes) = &data.episodes {
        if episodes.total.is_some() && episodes.hit.is_some() {
            ret.push_str(
                t!(
                    "result.episode.hit_total",
                    hit = episodes.hit.unwrap(),
                    total = episodes.total.unwrap()
                )
                .as_ref(),
            );

            if let Some(timestamp) = episodes.hit_timestamp {
                ret.push_str(t!("result.episode.timestamp", timestamp = timestamp as u64).as_ref());
            }
        } else if episodes.total.is_some() {
            ret.push_str(t!("result.episode.total", total = episodes.total.unwrap()).as_ref());
        } else if episodes.hit.is_some() {
            ret.push_str(t!("result.episode.hit", hit = episodes.hit.unwrap()).as_ref());

            if let Some(timestamp) = episodes.hit_timestamp {
                ret.push_str(t!("result.episode.timestamp", timestamp = timestamp as u64).as_ref());
            }
        }

        if episodes.total.is_some() || episodes.hit.is_some() {
            ret.push('\n');
        }
    }

    if let Some(chapters) = &data.chapters {
        if chapters.total.is_some() && chapters.hit.is_some() {
            ret.push_str(
                t!(
                    "result.chapter.hit_total",
                    hit = chapters.hit.unwrap(),
                    total = chapters.total.unwrap()
                )
                .as_ref(),
            );
        } else if chapters.total.is_some() {
            ret.push_str(t!("result.chapter.total", total = chapters.total.unwrap()).as_ref());
        } else if chapters.hit.is_some() {
            ret.push_str(t!("result.chapter.hit", hit = chapters.hit.unwrap()).as_ref());
        }
        ret.push('\n');
    }

    if let Some(status) = &data.status {
        ret.push_str(t!("result.status", status = status).as_ref());
        ret.push('\n');
    }

    if let Some(artist) = &data.artists {
        ret.push_str(t!("result.artist", artist = tagify(artist, false)).as_ref());
        ret.push('\n');
    }

    if let Some(tags) = &data.tags {
        ret.push_str(t!("result.tags", tags = tagify(tags, false)).as_ref());
        ret.push('\n');
    }

    if let Some(characters) = &data.characters {
        ret.push_str(t!("result.characters", characters = tagify(characters, false)).as_ref());
    }

    ret
}
