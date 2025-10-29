/// Converts a list of tags to a string
/// Test_!_Tag => test_tag
pub(crate) fn tagify<'a>(tags: impl Iterator<Item = &'a String>, escape: bool) -> String {
    let prefix = if escape { "\\#" } else { "#" };
    let tags: String = tags
        .map(|tag| {
            let normalized: String = tag
                .to_lowercase()
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
    tags
}

pub(crate) fn titleize(s: &str) -> String {
    let mut result = String::new();
    let mut capitalize_next = true;
    for c in s.chars() {
        if capitalize_next && c.is_alphabetic() {
            result.push(c.to_uppercase().next().unwrap());
            capitalize_next = false;
        } else {
            result.push(c);
            if c == ' ' {
                capitalize_next = true;
            }
        }
    }
    result
}
