from .base import SearchEngine


class TineyeSearchEngine(SearchEngine):
    name = "TinEye"
    description = (
        "TinEye is a reverse image search engine known for its unique algorithm and accurate results. It searches for"
        " image sources across the web, although it may have a smaller database compared to some other search engines."
    )
    pros = ["Unique algorithm", "Accurate"]
    cons = ["Smaller database"]
    credit_url = "https://tineye.com/"
    query_url_template = "https://tineye.com/search?url={file_url}"

    def __init__(self):
        super().__init__()
