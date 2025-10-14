use std::collections::HashSet;

pub(crate) fn tagify(tags: &HashSet<String>, escape: bool) -> String {
    let prefix = if escape { "\\#" } else { "#" };
    let tags: String = tags
        .iter()
        .map(|tag| {
            let normalized: String = tag
                .chars()
                .map(|c| if c.is_alphanumeric() { c } else { '_' })
                .collect();
            let collapsed: String = normalized
                .split('_')
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
                .join("_");
            format!("{}{}", prefix, collapsed)
        })
        .collect::<Vec<_>>()
        .join(", ");
    log::info!("Tags: {}", tags);
    tags
}
