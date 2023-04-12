from .base import SearchEngine


class SauceNaoSearchEngine(SearchEngine):
    """
    SauceNAO reverse image search engine implementation.

    Inherits from SearchEngine.
    """

    name = "SauceNAO"
    description = (
        "SauceNAO is a reverse image search engine specializing in finding the source of anime, manga, and similar"
        " artwork. It has a large database and can provide accurate results for identifying the artists, sources, and"
        " related information for the images."
    )
    pros = ["Anime and manga focused", "Fast results"]
    cons = ["Limited to specific sources"]
    credit_url = "https://saucenao.com"
    query_url_template = "https://saucenao.com/search.php?url={file_url}"

    def __init__(self):
        super().__init__()
