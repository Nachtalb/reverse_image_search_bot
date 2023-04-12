from .base import SearchEngine


class GoogleSearchEngine(SearchEngine):
    """
    Google reverse image search engine implementation.

    Inherits from SearchEngine.
    """

    name = "Google"
    description = "Google reverse image search"
    pros = ["Popular", "Large database"]
    cons = ["Limited results"]
    credit_url = "https://www.google.com"
    query_url_template = "https://www.google.com/searchbyimage?safe=off&sbisrc=tg&image_url={file_url}"

    def __init__(self):
        super().__init__()
