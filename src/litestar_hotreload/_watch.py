import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import watchfiles

logger = logging.getLogger(__name__)

ChangeSet = dict[str, list[str]]

CHANGE_EVENT_LABELS = {
    watchfiles.Change.added: "added",
    watchfiles.Change.modified: "modified",
    watchfiles.Change.deleted: "deleted",
}


class TaskError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class FileWatcher:
    def __init__(
        self, path: Path, on_change: Callable[[ChangeSet], Awaitable[None]]
    ) -> None:
        self._path = path
        self._on_change = on_change
        self._task: asyncio.Task | None = None

    @property
    def _should_exit(self) -> asyncio.Event:
        # Create lazily as hot reload may not run in the same thread as the one this
        # object was created in.
        if not hasattr(self, "_should_exit_obj"):
            self._should_exit_obj = asyncio.Event()
        return self._should_exit_obj

    async def _watch(self) -> None:
        async for changes in watchfiles.awatch(
            self._path, stop_event=self._should_exit
        ):
            changeset: ChangeSet = {}
            for event, group in itertools.groupby(changes, key=lambda item: item[0]):
                label = CHANGE_EVENT_LABELS[event]
                changeset[label] = [path for _, path in group]
            await self._on_change(changeset)

    async def _main(self) -> None:
        tasks = [
            asyncio.create_task(self._watch()),
        ]
        (done, pending) = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        [task.cancel() for task in pending]
        [task.result() for task in done]

    async def startup(self) -> None:
        if self._task is not None:
            raise RuntimeError("Task already started.")  # noqa: TRY003
        self._task = asyncio.create_task(self._main())
        logger.info(f"Started watching file changes at {self._path!r}")

    async def shutdown(self) -> None:
        if self._task is None:
            raise RuntimeError("Task was not started.")  # noqa: TRY003

        logger.info("Stopping file watching...")
        self._should_exit.set()
        await self._task
        self._task = None
