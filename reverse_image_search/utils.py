from typing import Generator, Sequence, TypeVar


T = TypeVar("T")


def chunks(value: Sequence[T], size: int) -> Generator[Sequence[T], None, None]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(value), size):
        yield value[i : i + size]
