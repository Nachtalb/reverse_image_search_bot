from .base import SearchEngine


class TraceSearchEngine(SearchEngine):
    name = "Tracer"
    description = (
        "Tracer is a reverse image search engine specializing in finding the source of anime scenes and clips. It is"
        " focused on identifying the specific anime series, episodes, and timestamps for the given images or clips."
    )
    pros = ["Anime focused", "Accurate"]
    cons = ["Limited to anime"]
    credit_url = "https://trace.moe/"
    query_url_template = "https://trace.moe/?auto&url={file_url}"

    def __init__(self):
        super().__init__()
