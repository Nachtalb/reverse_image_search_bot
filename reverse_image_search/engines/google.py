from .base import SearchEngine


class GoogleSearchEngine(SearchEngine):
    """
    Google reverse image search engine implementation.

    Inherits from SearchEngine.
    """

    name = "Google"
    description = (
        "Google reverse image search is a popular and widely-used search engine with a vast database. It provides"
        " general image search results and is not focused on any specific genre or category."
    )
    pros = ["Popular", "Large database"]
    cons = ["Limited results"]
    credit_url = "https://www.google.com"
    query_url_template = "https://www.google.com/searchbyimage?safe=off&sbisrc=tg&image_url={file_url}"

    def __init__(self):
        super().__init__()
