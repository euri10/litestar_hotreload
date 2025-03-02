from pathlib import Path

from litestar import Litestar, Response, get
from litestar.config.compression import CompressionConfig
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.response import Template
from litestar.template import TemplateConfig

from litestar_hotreload.plugin import HotReloadPlugin


@get("/")
async def render_page(trigger_compression: bool = False) -> Response:
    if trigger_compression:
        return Template(
            "index.html",
            context={
                "page_content": "my page content",
                "large_content_to_trigger_compression": "a\n" * 100000,
            },
        )
    return Template("index.html", context={"page_content": "my page content"})


@get("/json")
async def json_page() -> dict[str, str]:
    return {"not hot reload": "on json responses"}


template_config = TemplateConfig(
    engine=JinjaTemplateEngine, directory=Path(__file__).parent / "templates"
)
hotreload_plugin = HotReloadPlugin(
    template_config=template_config,
    watch_paths=[Path(__file__).parent / "templates"],
    ws_reload_path="/reload_custom",
    reconnect_interval=2.0,
)
compression_config = CompressionConfig(backend="gzip", gzip_compress_level=9)

app = Litestar(
    route_handlers=[
        render_page,
        json_page,
    ],
    debug=True,
    template_config=template_config,
    plugins=[hotreload_plugin],
    compression_config=compression_config,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "simple:app",
        reload=True,
    )
    # import granian
    # Granian(
    #     "simple:app", interface=Interfaces.ASGI, port=5000, reload=True
    # ).serve()
