use crate::models::Enrichment;
use crate::transformers::tagify;

pub fn format(data: &Enrichment, lang: String) -> String {
    let mut ret = String::new();

    ret.push_str(
        t!(
            "result.from",
            locale = lang,
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
            ret.push_str(t!("result.title.en", locale = lang, title = english).as_ref());
            ret.push('\n');
        }
        if let Some(romaji) = &title.romaji {
            ret.push_str(t!("result.title.romaji", locale = lang, title = romaji).as_ref());
            ret.push('\n');
        }
        if let Some(native) = &title.native {
            ret.push_str(t!("result.title.nativ", locale = lang, title = native).as_ref());
            ret.push('\n');
        }
    }

    if let Some(episodes) = &data.episodes {
        if episodes.total.is_some() && episodes.hit.is_some() {
            ret.push_str(
                t!(
                    "result.episode.hit_total",
                    locale = lang,
                    hit = episodes.hit.unwrap(),
                    total = episodes.total.unwrap()
                )
                .as_ref(),
            );

            if let Some(timestamp) = episodes.hit_timestamp {
                ret.push_str(
                    t!(
                        "result.episode.timestamp",
                        locale = lang,
                        timestamp = timestamp as u64
                    )
                    .as_ref(),
                );
            }
        } else if episodes.total.is_some() {
            ret.push_str(
                t!(
                    "result.episode.total",
                    locale = lang,
                    total = episodes.total.unwrap()
                )
                .as_ref(),
            );
        } else if episodes.hit.is_some() {
            ret.push_str(
                t!(
                    "result.episode.hit",
                    locale = lang,
                    hit = episodes.hit.unwrap()
                )
                .as_ref(),
            );

            if let Some(timestamp) = episodes.hit_timestamp {
                ret.push_str(
                    t!(
                        "result.episode.timestamp",
                        locale = lang,
                        timestamp = timestamp as u64
                    )
                    .as_ref(),
                );
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
                    locale = lang,
                    hit = chapters.hit.unwrap(),
                    total = chapters.total.unwrap()
                )
                .as_ref(),
            );
        } else if chapters.total.is_some() {
            ret.push_str(
                t!(
                    "result.chapter.total",
                    locale = lang,
                    total = chapters.total.unwrap()
                )
                .as_ref(),
            );
        } else if chapters.hit.is_some() {
            ret.push_str(
                t!(
                    "result.chapter.hit",
                    locale = lang,
                    hit = chapters.hit.unwrap()
                )
                .as_ref(),
            );
        }
        ret.push('\n');
    }

    if let Some(status) = &data.status {
        ret.push_str(t!("result.status", locale = lang, status = status).as_ref());
        ret.push('\n');
    }

    if let Some(artist) = &data.artists {
        ret.push_str(
            t!(
                "result.artist",
                locale = lang,
                artist = tagify(artist.iter(), false)
            )
            .as_ref(),
        );
        ret.push('\n');
    }

    if let Some(tags) = &data.tags {
        let tags: &[String] = &tags.iter().cloned().collect::<Vec<_>>()[..8];
        ret.push_str(
            t!(
                "result.tags",
                locale = lang,
                tags = tagify(tags.iter(), false)
            )
            .as_ref(),
        );
        ret.push('\n');
    }

    if let Some(characters) = &data.characters {
        ret.push_str(
            t!(
                "result.characters",
                locale = lang,
                characters = tagify(characters.iter(), false)
            )
            .as_ref(),
        );
    }

    ret
}
