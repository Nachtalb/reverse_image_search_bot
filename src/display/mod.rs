pub mod enriched;

use teloxide::types::InlineKeyboardButton;

use crate::models::enrichment::Url;

pub(crate) fn telegram_buttons(
    main_url: &Option<Url>,
    urls: &Option<Vec<Url>>,
) -> Vec<Vec<InlineKeyboardButton>> {
    let mut buttons: Vec<Vec<InlineKeyboardButton>> = vec![];
    if let Some(url) = main_url
        && let Some(url_string) = url.clean_url()
        && let Ok(parsed) = reqwest::Url::parse(url_string.as_str())
    {
        buttons.push(vec![InlineKeyboardButton::url(url.name(true), parsed)]);
    }

    if let Some(more_urls) = urls {
        let mut row: Vec<InlineKeyboardButton> = vec![];
        for url in more_urls {
            if let Some(url_string) = url.clean_url()
                && let Ok(parsed) = reqwest::Url::parse(url_string.as_str())
            {
                row.push(InlineKeyboardButton::url(url.name(true), parsed));
            }

            if row.len().is_multiple_of(3) {
                buttons.push(row);
                row = vec![];
            }
        }

        if !row.is_empty() {
            buttons.push(row);
        }
    }

    buttons
}
