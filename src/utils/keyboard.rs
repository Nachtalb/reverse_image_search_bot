use teloxide::types::InlineKeyboardButton;

fn format_url(template: &str, url: &str) -> reqwest::Url {
    let formatted = template.replace("{}", url);
    reqwest::Url::parse(&formatted).unwrap()
}

pub fn button(text: &str, template: &str, url: &str) -> InlineKeyboardButton {
    InlineKeyboardButton::url(text, format_url(template, url))
}
