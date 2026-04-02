"""Tracker web app for actioning Trusted Publishing issues."""

import webbrowser
from pathlib import Path


def main(
    target: str = "./data",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    import uvicorn

    from .server import create_app

    app = create_app(Path(target))
    webbrowser.open(f"http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")