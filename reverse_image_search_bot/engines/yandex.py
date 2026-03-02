from yarl import URL

from .pic_image_search import PicImageSearchEngine

__all__ = ["YandexEngine"]


class YandexEngine(PicImageSearchEngine):
    name = "Yandex"
    description = "Yandex reverse image search — finds sites containing the image and visually similar images."
    provider_url = URL("https://yandex.com/")
    types = ["General"]
    recommendation = ["Anything SFW and NSFW", "Image to Text (OCR)", "Anything Russian"]
    url = "https://yandex.com/images/search?url={query_url}&rpt=imageview"

    def __init__(self, *args, **kwargs):
        from PicImageSearch import Yandex

        self.pic_engine_class = Yandex
        super().__init__(*args, **kwargs)
