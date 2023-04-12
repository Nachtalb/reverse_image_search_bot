from .base import SearchEngine


class SauceNaoSearchEngine(SearchEngine):
    """
    SauceNAO reverse image search engine implementation.

    Inherits from SearchEngine.
    """

    name = "SauceNAO"
    description = "SauceNAO reverse image search"
    pros = ["Anime and manga focused", "Fast results"]
    cons = ["Limited to specific sources"]
    credit_url = "https://saucenao.com"
    query_url_template = "https://saucenao.com/search.php?url={file_url}"

    def __init__(self):
        super().__init__()
