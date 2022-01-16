def tag(tagname: str, content: str, attrs: dict = {}) -> str:
    attrs_str = " ".join(map(lambda i: f'{i[0]}="{i[1]}"', attrs.items()))
    return f"<{tagname} {attrs_str}>{content}</{tagname}>"


b = lambda text: tag("b", text)
i = lambda text: tag("i", text)
pre = lambda text: tag("pre", text)
code = lambda text: tag("code", text)
a = lambda text, href: tag("a", text, {"href": href})
img = lambda text, src: tag("img", text, {"src": src})
title = lambda text: b(text + ":") + " "
