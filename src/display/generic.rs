use crate::models::GenericData;

pub fn format(fanart: &GenericData) -> String {
    let mut ret = String::new();

    for (key, value) in &fanart.key_values {
        ret.push_str(&format!("{}: <code>{}</code>\n", key, value));
    }

    ret
}
