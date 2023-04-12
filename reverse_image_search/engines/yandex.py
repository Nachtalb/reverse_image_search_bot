from .base import SearchEngine


class YandexSearchEngine(SearchEngine):
    name = "Yandex"
    description = (
        "Yandex reverse image search is a powerful search engine with a large database that provides general image"
        " search results. It is not focused on any specific genre or category but is known for its accuracy in"
        " identifying image sources."
    )
    pros = ["Large database", "Accurate"]
    cons = ["Region limited"]
    credit_url = "https://yandex.com/images/"
    query_url_template = "https://yandex.com/images/search?url={file_url}&rpt=imageview"

    def __init__(self):
        super().__init__()
