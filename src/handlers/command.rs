use anyhow::{Error, Result};
use regex::Regex;
use teloxide::{
    Bot,
    dispatching::UpdateHandler,
    prelude::*,
    types::{InlineKeyboardButton, InputFile, LinkPreviewOptions, Message, ReplyMarkup},
    utils::command::BotCommands,
};

use crate::{
    config::get_config,
    handlers::media,
    utils::{LangSource, get_chat_lang, set_chat_lang},
};

#[derive(BotCommands, Clone, Debug)]
#[command(
    rename_rule = "lowercase",
    description = "These commands are supported"
)]
pub(crate) enum Command {
    #[command(description = "Startup message")]
    Start,
    #[command(description = "How to search?")]
    Help,
    #[command(description = "Reply with /search to an image or video.")]
    Search,
    #[command(description = "Set language", alias = "lang")]
    Language,
}

async fn handle_search_message(bot: Bot, msg: Message) -> Result<()> {
    let chat_id = msg.chat.id;
    let chat_lang = get_chat_lang(LangSource::Message(&msg)).await;

    if let Some(reply_to_msg) = msg.reply_to_message() {
        if media::filter_for_media_message(reply_to_msg.clone()) {
            media::handle_media_message(bot, reply_to_msg.clone()).await?
        } else {
            bot.send_message(
                chat_id,
                t!("message.reply_to_media", locale = chat_lang).as_ref(),
            )
            .await?;
        }
    } else {
        bot.send_message(
            chat_id,
            t!("message.reply_to_media", locale = chat_lang).as_ref(),
        )
        .await?;
    }

    Ok(())
}

async fn handle_start_message(bot: Bot, msg: Message) -> Result<()> {
    let preview_options = LinkPreviewOptions {
        url: Some(t!("message.start.preview_url").to_string()),
        is_disabled: false,
        prefer_small_media: true,
        prefer_large_media: false,
        show_above_text: false,
    };
    bot.send_message(
        msg.chat.id,
        t!(
            "message.start",
            locale = get_chat_lang(LangSource::Message(&msg)).await.as_str()
        )
        .as_ref(),
    )
    .link_preview_options(preview_options)
    .parse_mode(teloxide::types::ParseMode::Html)
    .await?;
    Ok(())
}

async fn handle_help_message(bot: Bot, msg: Message) -> Result<()> {
    let image = include_bytes!("../../images/help.jpg");
    let photo = InputFile::memory(image.as_slice());
    let chat_lang = get_chat_lang(LangSource::Message(&msg)).await;
    bot.send_photo(msg.chat.id, photo)
        .caption(t!("message.help", locale = chat_lang).as_ref())
        .show_caption_above_media(true)
        .parse_mode(teloxide::types::ParseMode::Html)
        .await?;
    Ok(())
}

async fn handle_language_message(bot: Bot, msg: Message) -> Result<()> {
    let chat_id = msg.chat.id;
    let config = get_config();
    log::debug!("{} initiated language command", chat_id);

    let mut langs_keyboard: Vec<Vec<InlineKeyboardButton>> = vec![];
    let mut row: Vec<InlineKeyboardButton> = vec![];

    for language in config.general.languages.clone().unwrap_or_default() {
        row.push(InlineKeyboardButton::callback(
            language.name,
            format!("lang:{}:{}", chat_id.0, language.code),
        ));
        if row.len() == 2 {
            langs_keyboard.push(row);
            row = vec![];
        }
    }

    let reply_markup = ReplyMarkup::inline_kb(langs_keyboard);
    let current_lang = get_chat_lang(LangSource::ChatId(&chat_id)).await;
    let current_lang_name = config
        .general
        .languages
        .clone()
        .unwrap()
        .iter()
        .find(|l| l.code == current_lang)
        .map(|l| l.name.clone())
        .unwrap_or(current_lang.clone());

    bot.send_message(
        msg.chat.id,
        t!(
            "message.language.choose",
            locale = current_lang,
            current_lang = current_lang_name
        )
        .as_ref(),
    )
    .reply_markup(reply_markup)
    .parse_mode(teloxide::types::ParseMode::Html)
    .await?;
    Ok(())
}

async fn language_handle_set(
    bot: Bot,
    query: CallbackQuery,
    chat_id: i64,
    lang: String,
) -> Result<()> {
    let config = get_config();
    let available_langs = config.general.languages.clone().unwrap_or_default();
    let current_lang = get_chat_lang(LangSource::Integer(chat_id)).await;

    match available_langs.iter().find(|l| l.code == lang) {
        Some(lang) => {
            log::debug!("Setting language for chat {} to {}", chat_id, lang.code);
            set_chat_lang(LangSource::Integer(chat_id), lang.code.as_str()).await;

            bot.send_message(
                ChatId(chat_id),
                t!(
                    "message.language.set",
                    locale = lang.code.as_str(),
                    lang = lang.name
                )
                .as_ref(),
            )
            .parse_mode(teloxide::types::ParseMode::Html)
            .await?;
        }
        None => {
            log::warn!(
                "Cannot set language for {}, lang {} not available",
                chat_id,
                lang
            );
            bot.send_message(
                ChatId(chat_id),
                t!(
                    "message.language.not_available",
                    locale = current_lang,
                    lang = lang
                )
                .as_ref(),
            )
            .parse_mode(teloxide::types::ParseMode::Html)
            .await?;
        }
    }

    bot.answer_callback_query(query.id).await?;
    Ok(())
}

async fn command_dispatcher(bot: Bot, msg: Message, cmd: Command) -> Result<()> {
    match cmd {
        Command::Start => handle_start_message(bot, msg).await?,
        Command::Help => handle_help_message(bot, msg).await?,
        Command::Search => handle_search_message(bot, msg).await?,
        Command::Language => handle_language_message(bot, msg).await?,
    };

    Ok(())
}

async fn handle_callbacks(bot: Bot, query: CallbackQuery) -> Result<()> {
    let data = query.data.clone().unwrap_or_default();
    let re_lang = Regex::new(r"^lang:(-?\d+):([a-z]+)$").unwrap();

    if let Some(captures) = re_lang.captures(&data) {
        language_handle_set(bot, query, captures[1].parse()?, captures[2].to_string()).await?;
    } else {
        log::warn!("Unrecognized callback data: {}", data);
        bot.answer_callback_query(query.id).await?;
    }

    Ok(())
}

pub(crate) fn branch() -> UpdateHandler<Error> {
    let command_handler = Update::filter_message()
        .filter_command::<Command>()
        .endpoint(command_dispatcher);

    let callback_handler = Update::filter_callback_query().endpoint(handle_callbacks);

    dptree::entry()
        .branch(command_handler)
        .branch(callback_handler)
}
