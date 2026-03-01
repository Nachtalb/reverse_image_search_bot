def tag(tagname: str, content: str, attrs: dict | None = None) -> str:
    attrs_str = " ".join(map(lambda i: f'{i[0]}="{i[1]}"', (attrs or {}).items()))
    return f"<{tagname} {attrs_str}>{content}</{tagname}>"


def b(text):
    return tag("b", text)


def i(text):
    return tag("i", text)


def pre(text):
    return tag("pre", text)


def code(text):
    return tag("code", text)


def a(text, href):
    return tag("a", text, {"href": href})


def hidden_a(src):
    return a("​", src)


def title(text):
    return b(text + ":") + " "
