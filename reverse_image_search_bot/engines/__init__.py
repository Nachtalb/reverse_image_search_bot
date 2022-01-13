from .generic import GenericRISEngine
from .saucenao import SauceNaoEngine
from .iqdb import IQDBEngine
from .trace import TraceEngine


__all__ = ['engines']

engines: list[GenericRISEngine]= [
    SauceNaoEngine(),
    GenericRISEngine('Google', 'https://www.google.com/searchbyimage?safe=off&image_url={query_url}'),
    IQDBEngine(),
    GenericRISEngine('Yandex', 'https://yandex.com/images/search?url={query_url}&rpt=imageview'),
    GenericRISEngine('Bing', 'https://www.bing.com/images/search?q=imgurl:{query_url}&view=detailv2&iss=sbi'),
    GenericRISEngine('TinEye', 'https://tineye.com/search?url={query_url}'),
    TraceEngine(),
]
