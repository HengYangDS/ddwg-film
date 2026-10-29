"""Serve owned local review media with byte ranges for browser seeking."""

from __future__ import annotations

import argparse
import contextlib
import re
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import filmkit.repository as repository


class MediaHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        self.remaining = None
        path = Path(self.translate_path(self.path))
        requested = self.headers.get("Range")
        if not requested or not path.is_file():
            return super().send_head()

        size = path.stat().st_size
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
        if not match or not any(match.groups()) or not size:
            return self.unsatisfied(size)

        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            count = int(last)
            if not count:
                return self.unsatisfied(size)
            start, end = max(0, size - count), size - 1
        if start >= size or start > end:
            return self.unsatisfied(size)

        try:
            file = path.open("rb")
            file.seek(start)
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        self.remaining = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Length", str(self.remaining))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Last-Modified", self.date_time_string(path.stat().st_mtime))
        self.end_headers()
        return file

    def unsatisfied(self, size):
        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def copyfile(self, source, outputfile):
        try:
            if self.remaining is None:
                return super().copyfile(source, outputfile)
            left = self.remaining
            while left:
                block = source.read(min(64 * 1024, left))
                if not block:
                    break
                outputfile.write(block)
                left -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            # Seeking and edition changes legitimately cancel the old response.
            return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=repository.ROOT / "build/artifacts/film",
    )
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    directory = args.directory.resolve(strict=True)
    if not directory.is_dir():
        parser.error("The media directory must exist")
    handler = partial(MediaHandler, directory=str(directory))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Serving review media at http://127.0.0.1:{args.port}/", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    main()
