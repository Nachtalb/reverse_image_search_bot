use teloxide::types::{ChatId, Message};

use crate::redis::get_redis;

#[derive(Clone)]
pub(crate) enum LangSource<'a> {
    Message(&'a Message),
    ChatId(&'a ChatId),
    Integer(i64),
}

pub(crate) async fn get_chat_lang(source: LangSource<'_>) -> String {
    let chat_id: i64 = match source {
        LangSource::Message(message) => message.chat.id.0,
        LangSource::ChatId(chat_id) => chat_id.0,
        LangSource::Integer(id) => id,
    };

    let mut lang = "en".to_string();
    if let LangSource::Message(msg) = source
        && msg.chat.is_private()
    {
        lang = msg
            .from
            .clone()
            .and_then(|u| u.language_code.clone())
            .unwrap_or(lang);
    }

    let redis = get_redis().await;
    if let Some(redis) = redis {
        match redis.get_locale(chat_id).await {
            Ok(Some(language_code)) => lang = language_code,
            Ok(None) => match redis.set_locale(chat_id, &lang).await {
                Ok(_) => (),
                Err(e) => log::error!("Failed to set locale for chat {}: {}", chat_id, e),
            },
            Err(e) => log::error!("Failed to get locale for chat {}: {}", chat_id, e),
        }
    }

    lang
}

pub(crate) async fn set_chat_lang(source: LangSource<'_>, lang: &str) {
    let chat_id: i64 = match source {
        LangSource::Message(message) => message.chat.id.0,
        LangSource::ChatId(chat_id) => chat_id.0,
        LangSource::Integer(id) => id,
    };

    let redis = get_redis().await;
    if let Some(redis) = redis {
        match redis.set_locale(chat_id, lang).await {
            Ok(_) => (),
            Err(e) => log::error!("Failed to set locale for chat {}: {}", chat_id, e),
        }
    }
}
