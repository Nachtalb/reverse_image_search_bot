from yarl import URL

from reverse_image_search_bot.utils import get_file_from_url

from .generic import PreWorkEngine


class ShutterStockEngine(PreWorkEngine):
    name = "ShutterStock"
    description = (
        "Shutterstock is a global provider of stock photography, stock footage and stock music, headquartered in New"
        " York."
    )
    provider_url = URL("https://www.shutterstock.com/")
    types = ["Stock"]
    recommendation = ["Stock Photography"]

    url = "https://www.shutterstock.com/search/ris/{query}"
    pre_url = "https://www.shutterstock.com/studioapi/images/reverse-image-search"
    has_session = True

    def get_search_link_by_url(self, url: URL) -> str | None:
        file = get_file_from_url(url)
        if not file.is_file():
            return

        with file.open("rb") as open_file:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                    " Chrome/97.0.4692.71 Safari/537.36"
                )
            }
            response = self.session.post(self.pre_url, headers=headers, files={"image": (file.name, open_file)})
        if response.status_code != 200:
            return
        ids = map(lambda item: item["id"], response.json())
        return self.url.format(query=":".join(ids))
