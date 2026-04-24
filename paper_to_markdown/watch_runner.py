"""Realtime runner-side PDF watcher.

This process belongs on the conversion machine.  It watches ``input_root`` for
PDF changes and delegates actual conversion to the existing Marker pipeline.
"""
from __future__ import annotations

import argparse
import queue
import time
from pathlib import Path
from typing import Callable

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ModuleNotFoundError:
    class FileSystemEventHandler:  # type: ignore[no-redef]
        pass

    Observer = None  # type: ignore[assignment]

try:
    from .common import find_all_pdfs, load_config, setup_logger
    from .pipeline import convert_one_pdf_with_retries
except ImportError:
    from common import find_all_pdfs, load_config, setup_logger
    from pipeline import convert_one_pdf_with_retries


def is_pdf_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def load_runner_config(config_path: str | None = None) -> dict:
    config = load_config(config_path)
    if config.get("run_mode") == "controller":
        raise SystemExit(1)
    return config


def wait_until_stable(path: Path, checks: int, interval_seconds: float) -> bool:
    if checks <= 0:
        return path.exists()

    previous: tuple[int, int] | None = None
    stable_count = 0
    while stable_count < checks:
        if not path.exists() or not path.is_file():
            return False
        stat = path.stat()
        current = (stat.st_size, stat.st_mtime_ns)
        if current == previous:
            stable_count += 1
        else:
            previous = current
            stable_count = 0
        if stable_count < checks and interval_seconds > 0:
            time.sleep(interval_seconds)
    return True


class PdfEventHandler(FileSystemEventHandler):
    def __init__(self, input_root: Path, enqueue: Callable[[Path], None]) -> None:
        self.input_root = input_root
        self.enqueue = enqueue

    def _queue_path(self, raw_path: str) -> None:
        path = Path(raw_path)
        if is_pdf_path(path):
            self.enqueue(path)

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._queue_path(event.src_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._queue_path(event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._queue_path(event.dest_path)


class PdfWatchRunner:
    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path
        self.config = load_runner_config(config_path)
        self.logger = setup_logger(self.config, logger_name="paper_to_markdown.watch_runner")
        self.input_root = Path(self.config["input_root"])
        self.pending: "queue.Queue[Path]" = queue.Queue()
        self.seen: set[Path] = set()

    def enqueue(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved in self.seen:
            return
        self.seen.add(resolved)
        self.pending.put(resolved)
        self.logger.info("Queued PDF for conversion: %s", resolved)

    def run_initial_scan(self) -> None:
        if not bool(self.config.get("watch_initial_scan", False)):
            return
        for pdf_path in find_all_pdfs(self.input_root):
            self.enqueue(pdf_path)
        self.process_pending_once()

    def process_pending_once(self) -> None:
        stable_checks = int(self.config.get("watch_stable_checks", 3))
        stable_interval = float(self.config.get("watch_stable_interval_seconds", 2))
        while True:
            try:
                pdf_path = self.pending.get_nowait()
            except queue.Empty:
                return

            try:
                if not wait_until_stable(pdf_path, stable_checks, stable_interval):
                    self.logger.info("Skipped unstable or missing PDF: %s", pdf_path)
                    continue
                convert_one_pdf_with_retries(pdf_path, config_path=self.config_path)
            except Exception:
                self.logger.exception("Watcher conversion failed after all retries: %s", pdf_path)
            finally:
                self.seen.discard(pdf_path)

    def watch_forever(self) -> None:
        if Observer is None:
            raise RuntimeError(
                "watchdog is required for realtime watching. Install project dependencies with "
                "`pip install -r requirements.txt`."
            )

        self.input_root.mkdir(parents=True, exist_ok=True)
        self.run_initial_scan()

        event_handler = PdfEventHandler(self.input_root, self.enqueue)
        observer = Observer()
        observer.schedule(event_handler, str(self.input_root), recursive=True)
        observer.start()
        self.logger.info("Runner PDF watcher started: %s", self.input_root)

        poll_interval = float(self.config.get("watch_poll_interval_seconds", 1))
        try:
            while True:
                self.process_pending_once()
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.logger.info("Runner PDF watcher stopping")
        finally:
            observer.stop()
            observer.join()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Realtime runner-side PDF watcher.")
    parser.add_argument("--config", default=None, help="Path to settings.json.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    PdfWatchRunner(config_path=args.config).watch_forever()


if __name__ == "__main__":
    main()
