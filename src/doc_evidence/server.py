"""Production-like local server composition and authenticated browser launch."""

from __future__ import annotations

import secrets
import socket
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import uvicorn

from doc_evidence.adapters.local_workspace import LocalWorkspace
from doc_evidence.api.app import create_app
from doc_evidence.application.library import LibraryApplication
from doc_evidence.config import AppConfig
from doc_evidence.errors import RequestError


def default_frontend_dir() -> Path:
    repository_build = Path(__file__).parents[2] / "web" / "dist"
    if repository_build.is_dir():
        return repository_build
    packaged_build = Path(__file__).parent / "web_dist"
    return packaged_build


def serve_local(
    config: AppConfig,
    *,
    frontend_dir: Path | None = None,
    open_browser: bool = True,
) -> int:
    static_dir = (frontend_dir or default_frontend_dir()).expanduser().resolve()
    if not (static_dir / "index.html").is_file():
        raise RequestError(
            f"frontend build is missing at {static_dir}; run npm install --prefix web "
            "and npm run build --prefix web"
        )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2048)
    port = int(listener.getsockname()[1])
    base_url = f"http://127.0.0.1:{port}"
    token = secrets.token_urlsafe(32)
    launch_url = base_url + "/#token=" + urllib.parse.quote(token, safe="")
    application = LibraryApplication(LocalWorkspace(config))

    def started() -> None:
        if open_browser:
            threading.Thread(
                target=webbrowser.open,
                args=(launch_url,),
                daemon=True,
            ).start()

    app = create_app(
        application,
        launch_token=token,
        allowed_origins={base_url},
        static_dir=static_dir,
        on_started=started,
    )
    print(f"doc-evidence is serving an authenticated workspace at {base_url}")
    if not open_browser:
        print(
            "Browser launch disabled; this process intentionally does not print its token."
        )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="warning",
        )
    )
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
    return 0
