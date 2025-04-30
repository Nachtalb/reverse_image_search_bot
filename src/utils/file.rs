pub fn output_directory() -> std::path::PathBuf {
    let cwd = std::env::current_dir().unwrap();
    let dir = cwd.join("output");
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

// tests

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn creates_output_directory() {
        let dir = output_directory();
        assert!(dir.ends_with("output"));
        assert!(dir.exists());
        assert!(dir.is_dir());

        // Cleanup
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn idempotent_output_directory() {
        let first = output_directory();
        let second = output_directory();
        assert_eq!(first, second);

        // Cleanup
        fs::remove_dir_all(&first).unwrap();
    }
}
