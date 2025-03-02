"""Hot reload plugin for Litestar."""

import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader
from litestar import Litestar, Router, websocket_stream
from litestar.config.app import AppConfig
from litestar.plugins import InitPlugin
from litestar.template import TemplateConfig

from litestar_hotreload._notify import Notify
from litestar_hotreload._watch import ChangeSet, FileWatcher
from litestar_hotreload.middleware import HotReloadMiddleware

logger = logging.getLogger(__name__)


def _make_base_router(
    reload_path: str,
) -> tuple[Router, Notify]:
    # @websocket(path=reload_path)
    # async def _reload_handler(socket: WebSocket) -> None:
    #     await socket.accept()
    #     tasks = [
    #         asyncio.create_task(_watch_reloads(socket)),
    #         asyncio.create_task(_wait_client_disconnect(socket)),
    #     ]
    #     (done, pending) = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)  # noqa: E501
    #     logger.info(f"Done: {done}")
    #     logger.info(f"Pending: {pending}")
    #     logger.info("Cancelling pending tasks")
    #     [task.cancel() for task in pending]
    #     [task.result() for task in done]

    # async def _watch_reloads(socket: WebSocket) -> None:
    #     logger.info("Watching for reloads")
    #     async for _ in _notify.watch():
    #         logger.info("sending reload to ws")
    #         await socket.send_text("reload")
    #
    # async def _wait_client_disconnect(socket: WebSocket) -> None:
    #     logger.info("Waiting for client disconnect")
    #     async for _ in socket.iter_data("text"):
    #         logger.info(_)
    #         pass
    _notify = Notify()

    @websocket_stream(reload_path)
    async def _reload_handler() -> AsyncGenerator[str, None]:
        async for _ in _notify.watch():
            logger.info("sending reload to ws")
            yield "reload"

    return Router("/", route_handlers=[_reload_handler]), _notify


async def _on_changes(
    changeset: ChangeSet,
    *,
    _notify: Notify,
    # on_reload
) -> None:
    description = ", ".join(
        f"file {event} at {', '.join(f'{event!r}' for event in changeset[event])}"
        for event in changeset
    )
    logger.warning("Detected %s. Triggering reload...", description)

    # Run server-side hooks first.
    # for callback in on_reload:
    #     await callback()

    await _notify.notify()


@asynccontextmanager
async def hotreload_lifespan(
    _app: Litestar, watch_paths: Sequence[Path], notify: Notify
) -> AsyncGenerator[None, None]:
    """Lifespan asynccontextmanager for hot reload."""
    logger.info("Starting hot reload lifespan")
    _watchers = [
        FileWatcher(
            path,
            on_change=partial(
                _on_changes,
                _notify=notify,
                # on_reload=on_reload
            ),
        )
        for path in watch_paths
    ]
    try:
        for watcher in _watchers:
            await watcher.startup()
    except Exception:
        logger.exception("Error while starting hot reload")
        raise
    yield
    try:
        for watcher in _watchers:
            await watcher.shutdown()
    except Exception:
        logger.exception(
            "Error while stopping hot reload",
        )
        raise
    logger.info("Stopping hot reload lifespan")


class HotReloadPlugin(InitPlugin):
    """A plugin for hot reloading templates and static files."""

    def __init__(
        self,
        template_config: TemplateConfig,
        watch_paths: Sequence[Path],
        ws_reload_path: str = "/__litestar__",
        reconnect_interval: float = 1.0,
    ):
        """Initialize the HotReloadPlugin.

        Parameters
        ----------
        template_config : TemplateConfig
            The configuration for the template engine.
        watch_paths : Sequence[Path]
            A sequence of paths to watch for changes.
        ws_reload_path : str
            The WebSocket path for reload notifications. Defaults to "/__litestar__".
        reconnect_interval : float
            The interval in seconds to attempt reconnection. Defaults to 1.0.
        """
        self.template_config = template_config
        self.watch_paths = watch_paths
        self.ws_reload_path = ws_reload_path
        self.reconnect_interval = reconnect_interval

    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        """Configure the app with the hot reload plugin."""
        # TODO: could switch on engine, we suppose here it's jinja
        environment = self.template_config.engine_instance.engine
        with (Path(__file__).parent / "templates" / "hotreload.js").open(
            "r"
        ) as template_path:
            hotreload_template = template_path.read()
        new_env = environment.overlay(
            loader=ChoiceLoader(
                [DictLoader({"hotreload.js": hotreload_template}), environment.loader]
            )
        )
        _router, notify = _make_base_router(self.ws_reload_path)
        app_config.route_handlers.append(_router)

        app_config.middleware.append(
            HotReloadMiddleware(
                reconnect_interval=self.reconnect_interval,
                ws_path=self.ws_reload_path,
                environment=new_env,
            )
        )
        app_config.lifespan.append(
            partial(hotreload_lifespan, watch_paths=self.watch_paths, notify=notify)
        )
        return app_config
