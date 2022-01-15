from .baidu import BaiduEngine
from .generic import GenericRISEngine
from .iqdb import IQDBEngine
from .saucenao import SauceNaoEngine
from .shutterstock import ShutterStockEngine
from .trace import TraceEngine


__all__ = ["engines"]

engines: list[GenericRISEngine] = [
    SauceNaoEngine(),
    GenericRISEngine(
        "Google",
        "https://www.google.com/searchbyimage?safe=off&image_url={query_url}",
        "Google LLC is an American multinational technology company that specializes in Internet-related services and"
        " products.",
        "https://google.com/",
        ["All-in-one"],
        ["Anything SFW", "People and Characters"],
    ),
    TraceEngine(),
    IQDBEngine(),
    GenericRISEngine(
        "Yandex",
        "https://yandex.com/images/search?url={query_url}&rpt=imageview",
        "Yandex N.V. is a multinational corporation primarily for Russian and Russian-language users, providing 70"
        " Internet-related products and services",
        "https://yandex.ru/",
        ["All-in-one"],
        ["Anything SFW and NSFW", "Image to Text (ORC)", "Anything Russian"],
    ),
    BaiduEngine(),
    ShutterStockEngine(),
    GenericRISEngine(
        "Bing",
        "https://www.bing.com/images/search?q=imgurl:{query_url}&view=detailv2&iss=sbi",
        "Microsoft Bing is a web search engine owned and operated by Microsoft.",
        "https://bing.com/",
        ["All-in-one"],
    ),
    GenericRISEngine(
        "TinEye",
        "https://tineye.com/search?url={query_url}",
        "TinEye is a reverse image search engine developed and offered by Idée, Inc.. It is the first image search"
        " engine on the web to use image identification technology rather than keywords, metadata or watermarks.",
        "https://tineye.com/",
        ["All-in-one"],
    ),
]
