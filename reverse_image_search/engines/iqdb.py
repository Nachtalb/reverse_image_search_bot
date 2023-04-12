from .base import SearchEngine


class IqdbSearchEngine(SearchEngine):
    name = "IQDB"
    description = (
        "IQDB is a reverse image search engine dedicated to finding the source of anime, manga, and similar artwork. It"
        " searches across multiple databases to provide accurate results, including identifying the artists, sources,"
        " and related information for the images."
    )
    pros = ["Anime focused", "Multi-database"]
    cons = ["Limited to anime"]
    credit_url = "https://iqdb.org/"
    query_url_template = "https://iqdb.org/?url={file_url}"

    def __init__(self):
        super().__init__()


class Iqdb3DSearchEngine(SearchEngine):
    name = "3D IQDB"
    description = (
        "3D IQDB reverse image search focused on finding the source of cosplay images ('3D' in otaku jargon refers to"
        " real people). It is useful for identifying cosplayers, events, and related information for the images."
    )
    pros = ["Cosplay focused"]
    cons = ["Limited to cosplay images"]
    credit_url = "https://3d.iqdb.org/"
    query_url_template = "https://3d.iqdb.org/?url={file_url}"

    def __init__(self):
        super().__init__()
