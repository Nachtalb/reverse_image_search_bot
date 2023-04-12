from .base import SearchEngine


class SogouSearchEngine(SearchEngine):
    name = "Sogou"
    description = (
        "Sogou reverse image search is a Chinese search engine that provides general image search results across"
        " various categories and genres. It is not focused on any specific genre or category."
    )
    pros = ["Large database", "Supports Chinese content"]
    cons = ["Less accurate", "Region limited"]
    credit_url = "https://pic.sogou.com/"
    query_url_template = "https://pic.sogou.com/ris?flag=1&drag=0&query={file_url}"

    def __init__(self):
        super().__init__()
