from pathlib import Path

import pytest
from litestar import Litestar, Response, get, websocket_listener
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.response import Template
from litestar.template import TemplateConfig
from litestar.testing import AsyncTestClient

from litestar_hotreload.plugin import HotReloadPlugin


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("ws_reload_path", ["/__litestar__", "/custom_reload_path"])
async def test_plugin(tmp_path: Path, ws_reload_path: str) -> None:
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    index_jinja = templates_dir / "index.html"
    index_jinja.write_text("<body>{{ page_content }}</body>")

    template_config = TemplateConfig(
        engine=JinjaTemplateEngine, directory=templates_dir
    )

    @get("/")
    async def render_page() -> Response:
        page_content = "omg this is a html page"
        return Template("index.html", context={"page_content": page_content})

    hotreload_plugin = HotReloadPlugin(
        template_config=template_config,
        watch_paths=[templates_dir],
        reconnect_interval=0.5,
        ws_reload_path=ws_reload_path,
    )
    app = Litestar(
        route_handlers=[
            render_page,
        ],
        debug=True,
        template_config=template_config,
        plugins=[hotreload_plugin],
    )

    async with AsyncTestClient(app) as client:
        response = await client.get("/")
        assert "window.location.reload()" in response.text

        with await client.websocket_connect(ws_reload_path) as ws:
            index_jinja.write_text("modified")

            assert ws.receive_text() == "reload"
        response = await client.get("/")
        assert "modified" in response.text


@pytest.mark.anyio
async def test_ws_endpoint_with_plugin(tmp_path: Path) -> None:
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    index_jinja = templates_dir / "index.html"
    index_jinja.write_text("<body>{{ page_content }}</body>")

    template_config = TemplateConfig(
        engine=JinjaTemplateEngine, directory=templates_dir
    )

    @websocket_listener("/ws")
    async def ws(data: str) -> str:
        return data[::-1]

    hotreload_plugin = HotReloadPlugin(
        template_config=template_config,
        watch_paths=[templates_dir],
        reconnect_interval=0.5,
    )
    app = Litestar(
        route_handlers=[ws],
        debug=True,
        template_config=template_config,
        plugins=[hotreload_plugin],
    )

    async with AsyncTestClient(app) as client:
        with await client.websocket_connect("/ws") as ws:
            ws.send("1234")
            assert ws.receive_text() == "4321"
