import json
from pathlib import Path

import pytest

from paper_to_markdown import watch_runner


def write_settings(tmp_path: Path, payload: dict) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "settings.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def runner_config(tmp_path: Path, **overrides) -> dict:
    payload = {
        "run_mode": "runner",
        "input_root": str(tmp_path / "input"),
        "output_root": str(tmp_path / "output"),
        "hf_home": str(tmp_path / "hf"),
        "marker_cli": "marker_single",
        "watch_stable_checks": 1,
        "watch_stable_interval_seconds": 0,
    }
    payload.update(overrides)
    return payload


def test_controller_mode_rejects_runner_watch(tmp_path: Path):
    (tmp_path / "input").mkdir()
    config_path = write_settings(
        tmp_path,
        {
            "run_mode": "controller",
            "input_root": str(tmp_path / "input"),
            "output_root": str(tmp_path / "output"),
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        watch_runner.load_runner_config(str(config_path))

    assert excinfo.value.code == 1


def test_pdf_events_are_queued_and_non_pdfs_are_ignored(tmp_path: Path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    handler = watch_runner.PdfEventHandler(input_root, lambda path: queued.append(path))
    queued: list[Path] = []

    handler.on_created(type("Event", (), {"is_directory": False, "src_path": str(input_root / "paper.pdf")})())
    handler.on_modified(type("Event", (), {"is_directory": False, "src_path": str(input_root / "note.txt")})())

    assert queued == [input_root / "paper.pdf"]


def test_moved_pdf_queues_destination(tmp_path: Path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    queued: list[Path] = []
    handler = watch_runner.PdfEventHandler(input_root, queued.append)

    handler.on_moved(
        type(
            "Event",
            (),
            {
                "is_directory": False,
                "src_path": str(input_root / "old.tmp"),
                "dest_path": str(input_root / "paper.pdf"),
            },
        )()
    )

    assert queued == [input_root / "paper.pdf"]


def test_process_pending_converts_stable_pdf_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_root = tmp_path / "input"
    input_root.mkdir()
    pdf_path = input_root / "paper.pdf"
    pdf_path.write_bytes(b"pdf")
    config_path = write_settings(tmp_path, runner_config(tmp_path))
    converted: list[Path] = []

    monkeypatch.setattr(
        watch_runner,
        "convert_one_pdf_with_retries",
        lambda path, config_path=None, force_reconvert=False: converted.append(Path(path)),
    )

    watcher = watch_runner.PdfWatchRunner(str(config_path))
    watcher.enqueue(pdf_path)
    watcher.process_pending_once()
    watcher.process_pending_once()

    assert converted == [pdf_path]


def test_initial_scan_is_optional_and_converts_existing_pdfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    input_root = tmp_path / "input"
    input_root.mkdir()
    pdf_path = input_root / "paper.pdf"
    pdf_path.write_bytes(b"pdf")
    off_config = write_settings(tmp_path / "off", runner_config(tmp_path / "off", watch_initial_scan=False))
    on_config = write_settings(tmp_path / "on", runner_config(tmp_path / "on", input_root=str(input_root), watch_initial_scan=True))
    converted: list[Path] = []

    monkeypatch.setattr(
        watch_runner,
        "convert_one_pdf_with_retries",
        lambda path, config_path=None, force_reconvert=False: converted.append(Path(path)),
    )

    watch_runner.PdfWatchRunner(str(off_config)).run_initial_scan()
    watch_runner.PdfWatchRunner(str(on_config)).run_initial_scan()

    assert converted == [pdf_path]
