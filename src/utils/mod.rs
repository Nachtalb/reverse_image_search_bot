use std::time::{SystemTime, UNIX_EPOCH};

pub(crate) mod keyboard;
pub(crate) mod locale;

pub(crate) fn get_timestamp() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("Time went backwards")
        .as_nanos()
}

pub(crate) use locale::{LangSource, get_chat_lang, set_chat_lang};
