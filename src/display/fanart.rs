use crate::models::FanartData;

pub fn format(fanart: &FanartData) -> String {
    let mut ret = String::new();

    if let Some(title) = &fanart.title {
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

    if let Some(artist) = &fanart.artist {
        ret.push_str(&format!("Artist: <code>{}</code>\n", artist));
    }

    ret.push_str("Type: <code>FANART</code>\n");
    if let Some(tags) = &fanart.tags {
        ret.push_str(&format!(
            "Tags: <code>{}</code>\n",
            tags.iter()
                .map(|tag| tag.replace(" ", "_"))
                .collect::<Vec<String>>()
                .join(", ")
        ));
    }
    if let Some(characters) = &fanart.characters {
        ret.push_str(&format!(
            "Characters: <code>{}</code>\n",
            characters
                .iter()
                .map(|tag| tag.replace(" ", "_"))
                .collect::<Vec<String>>()
                .join(", ")
        ));
    }

    if let Some(anime) = &fanart.anime
        && let Some(anime_title_data) = &anime.title
        && let Some(anime_title) = anime_title_data.title()
    {
        ret.push_str(&format!("Anime: <code>{}</code>\n", anime_title));
    }

    if let Some(manga) = &fanart.manga
        && let Some(manga_title_data) = &manga.title
        && let Some(manga_title) = manga_title_data.title()
    {
        ret.push_str(&format!("Manga: <code>{}</code>\n", manga_title));
    }

    ret
}
