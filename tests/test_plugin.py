import warnings
from pathlib import Path

import pytest
from _pytest.recwarn import WarningsRecorder
from jinja2 import Environment, FileSystemLoader
from litestar import Litestar, Response, get, websocket_listener
from litestar.config.compression import CompressionConfig
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.handlers import HTTPRouteHandler, WebsocketListenerRouteHandler
from litestar.response import Template
from litestar.template import TemplateConfig
from litestar.testing import AsyncTestClient, create_async_test_client

from litestar_hotreload.plugin import HotReloadPlugin


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


LitestarHotReloadTestFactory = tuple[
    Path,
    Path,
    Path,
    Path,
    HTTPRouteHandler,
    HTTPRouteHandler,
    WebsocketListenerRouteHandler,
]


@pytest.fixture
def _setup(
    tmp_path: Path,
) -> LitestarHotReloadTestFactory:
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    index_jinja = templates_dir / "index.html"
    index_jinja.write_text("<body>{{ page_content }}</body>")
    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    index_md = markdown_dir / "index.md"
    index_md.write_text("## Hello, world!")

    @get("/")
    async def render_page(i: int = 1) -> Response:
        page_content = "omg this is a html page" * i
        return Template("index.html", context={"page_content": page_content})

    @get("/markdown", sync_to_thread=False)
    def render_markdown() -> Response:
        with Path(index_md).open("r") as f:
            markdown_content = f.read()
        return Response(markdown_content, media_type="text/markdown")

    @websocket_listener("/reversed_echo")
    async def reversed_echo(data: str) -> str:
        return data[::-1]

    return (
        index_jinja,
        templates_dir,
        index_md,
        markdown_dir,
        render_markdown,
        render_page,
        reversed_echo,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("ws_reload_path", ["/__litestar__", "/custom_reload_path"])
async def test_plugin_default_engine(
    _setup: LitestarHotReloadTestFactory, ws_reload_path: str
) -> None:
    (
        index_jinja,
        templates_dir,
        index_md,
        markdown_dir,
        render_markdown,
        render_page,
        reversed_echo,
    ) = _setup

    template_config = TemplateConfig(
        engine=JinjaTemplateEngine, directory=templates_dir
    )

    hotreload_plugin = HotReloadPlugin(
        template_config=template_config,
        watch_paths=[templates_dir, markdown_dir],
        reconnect_interval=0.5,
        ws_reload_path=ws_reload_path,
    )

    async with create_async_test_client(
        route_handlers=[render_page, render_markdown],
        debug=True,
        template_config=template_config,
        plugins=[hotreload_plugin],
    ) as client:
        response = await client.get("/")
        assert "window.location.reload()" in response.text

        with await client.websocket_connect(ws_reload_path) as ws:
            index_jinja.write_text("modified")

            assert ws.receive_text() == "reload"
        response = await client.get("/")
        assert "modified" in response.text

        with await client.websocket_connect(ws_reload_path) as ws:
            index_md.write_text("__modified__")

            assert ws.receive_text() == "reload"
        response = await client.get("/markdown")
        assert "__modified__" in response.text


@pytest.mark.anyio
@pytest.mark.parametrize("ws_reload_path", ["/__litestar__", "/custom_reload_path"])
async def test_plugin_non_default_engine(
    _setup: LitestarHotReloadTestFactory, ws_reload_path: str
) -> None:
    (
        index_jinja,
        templates_dir,
        index_md,
        markdown_dir,
        render_markdown,
        render_page,
        reversed_echo,
    ) = _setup

    environment = Environment(loader=FileSystemLoader(templates_dir), autoescape=True)
    template_config = TemplateConfig(
        instance=JinjaTemplateEngine.from_environment(environment),
    )

    hotreload_plugin = HotReloadPlugin(
        template_config=template_config,
        watch_paths=[templates_dir],
        reconnect_interval=0.5,
        ws_reload_path=ws_reload_path,
    )

    async with create_async_test_client(
        route_handlers=[render_page, render_markdown],
        debug=True,
        template_config=template_config,
        plugins=[hotreload_plugin],
    ) as client:
        response = await client.get("/")
        assert "window.location.reload()" in response.text

        with await client.websocket_connect(ws_reload_path) as ws:
            index_jinja.write_text("modified")

            assert ws.receive_text() == "reload"
        response = await client.get("/")
        assert "modified" in response.text


@pytest.mark.anyio
async def test_ws_endpoint_with_plugin(
    _setup: LitestarHotReloadTestFactory,
) -> None:
    (
        index_jinja,
        templates_dir,
        index_md,
        markdown_dir,
        render_markdown,
        render_page,
        reversed_echo,
    ) = _setup

    template_config = TemplateConfig(
        engine=JinjaTemplateEngine, directory=templates_dir
    )

    hotreload_plugin = HotReloadPlugin(
        template_config=template_config,
        watch_paths=[templates_dir],
        reconnect_interval=0.5,
    )
    app = Litestar(
        route_handlers=[reversed_echo],
        debug=True,
        template_config=template_config,
        plugins=[hotreload_plugin],
    )

    async with AsyncTestClient(app) as client:
        with await client.websocket_connect("/reversed_echo") as ws:
            ws.send("1234")
            assert ws.receive_text() == "4321"


@pytest.mark.anyio
async def test_plugin_with_compression_warning(
    _setup: LitestarHotReloadTestFactory, recwarn: WarningsRecorder
) -> None:
    (
        index_jinja,
        templates_dir,
        index_md,
        markdown_dir,
        render_markdown,
        render_page,
        reversed_echo,
    ) = _setup
    template_config = TemplateConfig(
        engine=JinjaTemplateEngine, directory=templates_dir
    )

    compression_config = CompressionConfig("gzip")

    hotreload_plugin = HotReloadPlugin(
        template_config=template_config,
        watch_paths=[templates_dir],
    )
    app = Litestar(
        route_handlers=[
            render_page,
        ],
        debug=True,
        template_config=template_config,
        plugins=[hotreload_plugin],
        compression_config=compression_config,
    )

    async with AsyncTestClient(app) as client:
        with warnings.catch_warnings():
            response = await client.get("/?i=1000")
            assert "window.location.reload()" not in response.text
            assert len(recwarn) == 1
            w = recwarn.pop(UserWarning)
            assert issubclass(w.category, UserWarning)
            assert (
                str(w.message)
                == "Cannot inject reload script into response encoded as b'gzip'."
            )
