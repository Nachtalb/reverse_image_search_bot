from .base import SearchEngine


class Ascii2dSearchEngine(SearchEngine):
    name = "Ascii2d"
    description = (
        "Ascii2d is a reverse image search engine specializing in finding the source of anime, manga, and similar"
        " artwork. It uses colour and texture search algorithms to provide accurate results, although its focus is"
        " limited to anime and related content."
    )
    pros = ["Anime focused", "Colour and texture search"]
    cons = ["Limited to anime"]
    credit_url = "https://ascii2d.net/"
    query_url_template = "https://ascii2d.net/search/url/{file_url}"

    def __init__(self):
        super().__init__()
