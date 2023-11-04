from typing import Generator


def chunks[T](lst: list[T], n: int) -> Generator[list[T], None, None]:  # type: ignore[name-defined]  # Syntax not yet supported by mypy
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
