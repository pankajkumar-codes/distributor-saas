"""InFlightLimit (#491): one server process works on at most MAX_IN_FLIGHT API requests at once; /health never waits.

Without it, 100 requests at once locked a local server: requests holding a database connection waited for a thread
while every thread waited for a connection, until the pool's 30 second timeout failed them all."""

import asyncio

from app.api import MAX_IN_FLIGHT, InFlightLimit, asgi


async def _run(limit: int, paths: list[str]) -> tuple[int, int]:
    """Sends every path at once through the limit; returns (most at once inside, most /health at once inside)."""
    now = {"api": 0, "health": 0}
    peak = {"api": 0, "health": 0}
    gate = asyncio.Event()

    async def inner(scope, receive, send):
        kind = "health" if scope["path"].endswith("/health") else "api"
        now[kind] += 1
        peak[kind] = max(peak[kind], now[kind])
        if kind == "health":
            await gate.wait()  # health requests stay inside until all of them are in, so they must not queue
        else:
            await asyncio.sleep(0.01)
        now[kind] -= 1

    mw = InFlightLimit(inner, limit=limit)

    async def call(path):
        await mw({"type": "http", "path": path}, None, None)

    tasks = [asyncio.create_task(call(p)) for p in paths]
    health = sum(p.endswith("/health") for p in paths)
    for _ in range(200):
        await asyncio.sleep(0)
        if now["health"] == health:
            break
    gate.set()
    await asyncio.gather(*tasks)
    return peak["api"], peak["health"]


def test_no_more_than_the_limit_at_once_and_health_never_waits():
    paths = ["/api/v1/b/x/documents"] * 40 + ["/api/v1/health"] * 5
    api_peak, health_peak = asyncio.run(_run(3, paths))
    assert api_peak == 3
    assert health_peak == 5


def test_every_request_is_answered_and_a_new_event_loop_works():
    # Lambda (Mangum) and the tests may run on more than one event loop; the semaphore follows the loop.
    for _ in range(2):
        api_peak, _ = asyncio.run(_run(2, ["/api/v1/me"] * 10))
        assert api_peak == 2


def test_the_app_is_wrapped_and_the_limit_fits_the_local_pool():
    assert isinstance(asgi.inner, InFlightLimit)
    assert MAX_IN_FLIGHT <= 15  # SQLAlchemy's default pool: 5 connections + 10 overflow (platform_common.db)
