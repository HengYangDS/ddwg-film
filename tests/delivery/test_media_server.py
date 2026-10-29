"""Ranged media serving."""

import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import filmkit.delivery.media_server as delivery_media_server


def test_media_ranges_support_seek_and_reject_unsatisfied_range(tmp_path):
    (tmp_path / "film.bin").write_bytes(b"0123456789abcdef")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(delivery_media_server.MediaHandler, directory=str(tmp_path))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/film.bin"
    try:
        with urlopen(Request(url, headers={"Range": "bytes=4-7"}), timeout=5) as response:
            assert response.status == 206
            assert response.read() == b"4567"
            assert response.headers["Content-Range"] == "bytes 4-7/16"
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url, headers={"Range": "bytes=50-"}), timeout=5)
        with error.value:
            assert error.value.code == 416
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
