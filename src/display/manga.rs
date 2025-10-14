use crate::{models::MangaData, transformers::tagify};

pub fn format(manga: &MangaData) -> String {
    let mut ret = String::new();

    if let Some(title) = &manga.title {
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

    if let Some(chapters) = &manga.chapters {
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
    if let Some(status) = &manga.status {
        ret.push_str(&format!("Status: <code>{}</code>\n", status));
    }
    ret.push_str("Type: <code>MANGA</code>\n");
    if let Some(year) = &manga.year {
        ret.push_str(&format!("Year: <code>{}</code>\n", year));
    }
    if let Some(tags) = &manga.tags {
        ret.push_str(&format!("Tags: <code>{}</code>\n", tagify(tags, false)));
    }

    ret
}
