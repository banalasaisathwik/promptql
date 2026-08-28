from collections.abc import AsyncIterator, Callable

import httpx


async def request_scoped_http_client(
    client_factory: Callable[[], httpx.AsyncClient],
) -> AsyncIterator[httpx.AsyncClient]:
    client = client_factory()
    try:
        yield client
    finally:
        await client.aclose()
