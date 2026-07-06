from __future__ import annotations

from types import TracebackType
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin
from wiki.repository import WikiRepository


class FakeSyncTransaction:
    def __init__(self, origin: SessionTransactionOrigin) -> None:
        self.origin = origin


class FakeAsyncTransaction:
    def __init__(self, origin: SessionTransactionOrigin) -> None:
        self.sync_transaction = FakeSyncTransaction(origin)


class FakeBeginContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.begin_enters += 1

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.session.begin_exits += 1
        return None


class FakeSession:
    def __init__(self, origin: SessionTransactionOrigin | None = None) -> None:
        self._transaction = FakeAsyncTransaction(origin) if origin is not None else None
        self.begin_calls = 0
        self.begin_enters = 0
        self.begin_exits = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def get_transaction(self) -> FakeAsyncTransaction | None:
        return self._transaction

    def begin(self) -> FakeBeginContext:
        self.begin_calls += 1
        return FakeBeginContext(self)

    async def commit(self) -> None:
        self.commit_calls += 1
        self._transaction = None

    async def rollback(self) -> None:
        self.rollback_calls += 1
        self._transaction = None


@pytest.mark.asyncio
async def test_transaction_commits_autobegun_transaction() -> None:
    session = FakeSession(SessionTransactionOrigin.AUTOBEGIN)
    repository = WikiRepository(cast(AsyncSession, session))

    async with repository.transaction(), repository.transaction():
        pass

    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    assert session.begin_calls == 0


@pytest.mark.asyncio
async def test_transaction_rolls_back_autobegun_transaction_on_error() -> None:
    session = FakeSession(SessionTransactionOrigin.AUTOBEGIN)
    repository = WikiRepository(cast(AsyncSession, session))

    with pytest.raises(RuntimeError, match="compile failed"):
        async with repository.transaction():
            raise RuntimeError("compile failed")

    assert session.commit_calls == 0
    assert session.rollback_calls == 1
    assert session.begin_calls == 0


@pytest.mark.asyncio
async def test_transaction_does_not_commit_explicit_external_transaction() -> None:
    session = FakeSession(SessionTransactionOrigin.BEGIN)
    repository = WikiRepository(cast(AsyncSession, session))

    async with repository.transaction():
        pass

    assert session.commit_calls == 0
    assert session.rollback_calls == 0
    assert session.begin_calls == 0


@pytest.mark.asyncio
async def test_transaction_starts_context_when_session_has_no_transaction() -> None:
    session = FakeSession()
    repository = WikiRepository(cast(AsyncSession, session))

    async with repository.transaction():
        pass

    assert session.begin_calls == 1
    assert session.begin_enters == 1
    assert session.begin_exits == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0
