pub type HandlerResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
