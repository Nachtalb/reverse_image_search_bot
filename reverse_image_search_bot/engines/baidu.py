from urllib.parse import quote_plus

from yarl import URL

from .generic import PreWorkEngine


class BaiduEngine(PreWorkEngine):
    name = "Baidu"
    description = "Baidu, Inc. is a Chinese multinational technology company specializing in Internet-related services."
    provider_url = URL("https://baidu.com/")
    types = ["All-in-one"]
    recommendation = ["Anything Chinese"]

    pre_url = "https://graph.baidu.com/upload?image={query_url}&from=pc"
    has_session = True

    def get_search_link_by_url(self, url: URL) -> URL | None:
        pre_url = self.pre_url.format(query_url=quote_plus(str(url)))

        response = self.session.get(pre_url)
        if response.status_code == 200 and (search_url := response.json().get("data", {}).get("url")):
            return URL(search_url)
