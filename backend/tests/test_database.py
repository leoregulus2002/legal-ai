import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.database import get_session


@pytest.mark.parametrize("failure", [False, True])
def test_session_transaction_boundary(failure: bool) -> None:
    committed = AsyncMock()
    rolled_back = AsyncMock()

    @asynccontextmanager
    async def transaction():
        try:
            yield
        except BaseException:
            await rolled_back()
            raise
        else:
            await committed()

    session = SimpleNamespace(begin=transaction)

    @asynccontextmanager
    async def sessions():
        yield session

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(sessions=sessions)))
    )

    async def exercise() -> None:
        dependency = get_session(request)
        assert await anext(dependency) is session
        if failure:
            with pytest.raises(RuntimeError):
                await dependency.athrow(RuntimeError("rollback"))
        else:
            with pytest.raises(StopAsyncIteration):
                await anext(dependency)

    asyncio.run(exercise())
    if failure:
        rolled_back.assert_awaited_once()
        committed.assert_not_awaited()
    else:
        committed.assert_awaited_once()
        rolled_back.assert_not_awaited()
