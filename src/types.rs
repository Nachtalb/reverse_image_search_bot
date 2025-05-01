pub type HandlerResponse<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
