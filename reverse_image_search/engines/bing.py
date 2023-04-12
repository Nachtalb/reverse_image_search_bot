from .base import SearchEngine


class BingSearchEngine(SearchEngine):
    name = "Bing"
    description = (
        "Bing reverse image search is a general image search engine with a large database. It provides search results"
        " across various categories and genres but may be less accurate compared to other search engines."
    )
    pros = ["Large database"]
    cons = ["Less accurate"]
    credit_url = "https://www.bing.com/images/"
    query_url_template = "https://www.bing.com/images/search?q=imgurl:{file_url}&view=detailv2&iss=sbi"

    def __init__(self):
        super().__init__()
