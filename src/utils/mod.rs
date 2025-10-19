use std::time::{SystemTime, UNIX_EPOCH};

pub(crate) mod keyboard;

pub(crate) fn get_timestamp() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("Time went backwards")
        .as_nanos()
}
