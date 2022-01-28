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
        ["General"],
        ["Anything SFW", "People and Characters"],
    ),
    TraceEngine(),
    IQDBEngine(),
    IQDBEngine(
        "3D IQDB",
        "https://3d.iqdb.org/?url={query_url}",
        "3D IQDB is a reverse search engine that scrubs ImageBoards for cosplayer photos.",
        "https://3d.iqdb.org/",
        ["Cosplayers"],
        ["Cosplayers"],
    ),
    GenericRISEngine(
        "Yandex",
        "https://yandex.com/images/search?url={query_url}&rpt=imageview",
        "Yandex N.V. is a multinational corporation primarily for Russian and Russian-language users, providing 70"
        " Internet-related products and services",
        "https://yandex.ru/",
        ["General"],
        ["Anything SFW and NSFW", "Image to Text (ORC)", "Anything Russian"],
    ),
    BaiduEngine(),
    # ShutterStockEngine(),
    GenericRISEngine(
        "Bing",
        "https://www.bing.com/images/search?q=imgurl:{query_url}&view=detailv2&iss=sbi",
        "Microsoft Bing is a web search engine owned and operated by Microsoft.",
        "https://bing.com/",
        ["General"],
    ),
    GenericRISEngine(
        "TinEye",
        "https://tineye.com/search?url={query_url}",
        "TinEye is a reverse image search engine developed and offered by Idée, Inc.. It is the first image search"
        " engine on the web to use image identification technology rather than keywords, metadata or watermarks.",
        "https://tineye.com/",
        ["General"],
    ),
    GenericRISEngine(
        "Sogou",
        "https://pic.sogou.com/ris?flag=1&drag=0&query={query_url}",
        "Sogou, Inc. is a Chinese technology company that offers a search engine. It is a subsidiary of Tencent.",
        "https://www.sogou.com/",
        ["Asian people I guess"],
    ),
    GenericRISEngine(
        "ascii2d",
        "https://ascii2d.net/search/url/{query_url}",
        "ascii2d allows you to search for images by image and examine its details. You can search for images with"
        "matching partial features (mainly for cropped images if about 2/3 of the original image remains)",
        "https://ascii2d.net/",
        ["Anime/Manga related Artworks"],
    ),
]
