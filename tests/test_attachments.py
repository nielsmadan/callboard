import hashlib
import io
import os
import sqlite3
import stat
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from callboard.attachments import TEMP_PREFIX, media_type, store_blob
from callboard.errors import CallboardError
from callboard.paths import attachments_dir, config_path, store_path
from helpers import CLOCK, Callboard, FakeBellhop, rows, seed

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489")
BINARY = bytes(range(256)) * 9


@pytest.fixture(autouse=True)
def people() -> None:
    seed(("enki", "enki"), ("nanna", "sess-nanna"), ("niels", None))


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    made = {
        "notes.txt": "line one\nline two ünïcode\n".encode(),
        "pixel.png": PNG,
        "blob.bin": BINARY,
    }
    directory = tmp_path / "src"
    directory.mkdir()
    for name, content in made.items():
        (directory / name).write_bytes(content)
    return {name: directory / name for name in made}


def _blobs() -> list[str]:
    directory = attachments_dir(os.environ)
    return sorted(entry.name for entry in directory.iterdir()) if directory.exists() else []


def _limit(limit: object) -> None:
    path = config_path(os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"max_attachment_bytes = {limit}\n")


def test_files_round_trip_byte_identical(
    cb: Callboard, files: dict[str, Path], tmp_path: Path
) -> None:
    attach = [arg for path in files.values() for arg in ("--attach", str(path))]
    assert cb("--as", "enki", "dm", "nanna", "three files", *attach).code == 0
    listed = cb("--as", "nanna", "read", "@enki", "--json").json()["messages"][0]["attachments"]
    assert [(item["filename"], item["media_type"], item["size"]) for item in listed] == [
        ("notes.txt", "text/plain", files["notes.txt"].stat().st_size),
        ("pixel.png", "image/png", len(PNG)),
        ("blob.bin", "application/octet-stream", len(BINARY)),
    ]
    for item in listed:
        original = files[item["filename"]].read_bytes()
        stored = Path(item["path"])
        assert stored.read_bytes() == original
        assert stored.name == hashlib.sha256(original).hexdigest()
        assert stat.S_IMODE(stored.stat().st_mode) == 0o600
        assert cb("--as", "nanna", "attachment", "get", item["id"]).out == f"{stored}\n"
        out = tmp_path / f"copy-{item['filename']}"
        assert cb("--as", "nanna", "attachment", "get", item["id"], "--out", str(out)).code == 0
        assert out.read_bytes() == original


def test_the_same_file_twice_is_stored_once(cb: Callboard, files: dict[str, Path]) -> None:
    png = str(files["pixel.png"])
    assert cb("--as", "enki", "dm", "nanna", "a", "--attach", png, "--attach", png).code == 0
    assert cb("--as", "enki", "group", "create", "ops", "--members", "nanna").code == 0
    assert cb("--as", "enki", "group", "send", "ops", "b", "--attach", png).code == 0
    assert _blobs() == [hashlib.sha256(PNG).hexdigest()]
    assert rows("SELECT count(*), count(DISTINCT id) FROM attachments") == [(3, 3)]


def test_every_send_command_takes_attachments(cb: Callboard, files: dict[str, Path]) -> None:
    txt = str(files["notes.txt"])
    assert (
        cb("--as", "enki", "mail", "send", "--to", "nanna", "--subject", "s", "--attach", txt).code
        == 0
    )
    assert cb("--as", "nanna", "mail", "reply", "cb_000000000001", "--attach", txt).code == 0
    assert cb("--as", "enki", "group", "create", "ops", "--members", "nanna").code == 0
    assert cb("--as", "enki", "group", "send", "ops", "--attach", txt).code == 0
    assert cb("--as", "enki", "dm", "nanna", "--attach", txt).code == 0
    assert (
        rows(
            "SELECT m.body, count(a.id) FROM messages m JOIN attachments a ON a.message_id = m.id GROUP BY m.seq"
        )
        == [("", 1)] * 4
    )


def test_a_missing_path_is_refused_before_anything_is_stored(
    cb: Callboard, files: dict[str, Path], tmp_path: Path
) -> None:
    missing = tmp_path / "nope.txt"
    result = cb(
        "--as",
        "enki",
        "dm",
        "nanna",
        "hi",
        "--attach",
        str(files["blob.bin"]),
        "--attach",
        str(missing),
    )
    assert result == (
        2,
        "",
        f"callboard: --attach: cannot read {missing}: No such file or directory\n",
    )
    assert rows("SELECT count(*) FROM messages") == [(0,)]
    assert _blobs() == []


def test_a_directory_is_refused(cb: Callboard, tmp_path: Path) -> None:
    result = cb("--as", "enki", "dm", "nanna", "hi", "--attach", str(tmp_path))
    assert result == (2, "", f"callboard: --attach: {tmp_path} is not a regular file\n")


def test_a_file_over_the_limit_is_refused(cb: Callboard, files: dict[str, Path]) -> None:
    _limit(100)
    result = cb("--as", "enki", "dm", "nanna", "hi", "--attach", str(files["blob.bin"]))
    assert result == (
        2,
        "",
        f"callboard: --attach: {files['blob.bin']} is larger than 100 bytes\n",
    )
    assert rows("SELECT count(*) FROM messages") == [(0,)]
    assert _blobs() == []
    assert cb("--as", "enki", "dm", "nanna", "hi", "--attach", str(files["pixel.png"])).code == 0


@pytest.mark.parametrize("limit", ["0", '"big"', "true"])
def test_an_invalid_limit_is_a_config_error(
    cb: Callboard, files: dict[str, Path], limit: str
) -> None:
    _limit(limit)
    result = cb("--as", "enki", "dm", "nanna", "hi", "--attach", str(files["pixel.png"]))
    assert result.code == 2
    assert result.err.startswith(f"callboard: {config_path(os.environ)}: max_attachment_bytes must")


def test_an_unreadable_source_leaves_no_message_and_no_temp_file(
    cb: Callboard, files: dict[str, Path]
) -> None:
    files["blob.bin"].chmod(0o000)
    try:
        result = cb("--as", "enki", "dm", "nanna", "hi", "--attach", str(files["blob.bin"]))
    finally:
        files["blob.bin"].chmod(0o600)
    assert result == (
        2,
        "",
        f"callboard: --attach: cannot copy {files['blob.bin']}: Permission denied\n",
    )
    assert rows("SELECT count(*) FROM messages") == [(0,)]
    assert [name for name in _blobs() if name.startswith(TEMP_PREFIX)] == []


class _Breaking(io.BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        if self.tell():
            raise OSError("device went away")
        return super().read(size)


def test_a_failed_copy_removes_its_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("callboard.attachments.CHUNK_BYTES", 16)
    with pytest.raises(OSError, match="device went away"):
        store_blob(_Breaking(BINARY), tmp_path / "blobs", 10_000, "x")
    assert list((tmp_path / "blobs").iterdir()) == []


def test_a_stream_growing_past_the_limit_is_refused_and_cleaned_up(tmp_path: Path) -> None:
    with pytest.raises(CallboardError) as caught:
        store_blob(io.BytesIO(BINARY), tmp_path / "blobs", 100, "grown.bin")
    assert (caught.value.exit_code, str(caught.value)) == (
        2,
        "--attach: grown.bin is larger than 100 bytes",
    )
    assert list((tmp_path / "blobs").iterdir()) == []


class _Changing(io.BytesIO):
    def __init__(self, source: Path) -> None:
        super().__init__(source.read_bytes())
        self.source = source

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        with self.source.open("ab") as grow:
            grow.write(b"appended while copying")
        return chunk


def test_a_source_changing_during_the_copy_yields_a_blob_matching_its_hash(
    tmp_path: Path, files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("callboard.attachments.CHUNK_BYTES", 64)
    blob = store_blob(_Changing(files["blob.bin"]), tmp_path / "blobs", 10_000, "x")
    stored = (tmp_path / "blobs" / blob.sha256).read_bytes()
    assert hashlib.sha256(stored).hexdigest() == blob.sha256
    assert len(stored) == blob.size
    assert files["blob.bin"].read_bytes() != stored


def _age(seconds: int) -> None:
    then = datetime.fromisoformat(CLOCK).timestamp() - seconds
    for entry in attachments_dir(os.environ).iterdir():
        os.utime(entry, (then, then))


def test_a_failed_insert_leaves_a_blob_that_prune_removes(
    cb: Callboard, files: dict[str, Path], bellhop: FakeBellhop
) -> None:
    kept = cb("--as", "enki", "dm", "nanna", "kept", "--attach", str(files["pixel.png"]))
    assert kept.code == 0
    failed = cb("--as", "enki", "dm", "ghost", "lost", "--attach", str(files["blob.bin"]))
    assert failed == (3, "", "callboard: no participant 'ghost'\n")
    orphan = hashlib.sha256(BINARY).hexdigest()
    assert _blobs() == sorted([hashlib.sha256(PNG).hexdigest(), orphan])
    assert rows("SELECT count(*) FROM messages") == [(1,)]
    stale_temp = attachments_dir(os.environ) / f"{TEMP_PREFIX}crashed"
    stale_temp.write_bytes(b"half")
    _age(59 * 60)
    fresh = cb("doctor", "--prune", "--json").json()["pruned"]
    assert fresh == {"blobs": 0, "blob_bytes": 0, "temp_files": 0, "wal_truncated": True}
    _age(61 * 60)
    wal = Path(f"{store_path(os.environ)}-wal")
    with closing(sqlite3.connect(store_path(os.environ))) as holder:
        holder.execute(
            "INSERT INTO participants (handle, kind, created_at) VALUES ('anu', 'human', 't')"
        )
        holder.commit()
        assert wal.stat().st_size > 0
        result = cb("doctor", "--prune")
        assert wal.stat().st_size == 0
    assert result.code == 0
    assert result.out.splitlines()[-1] == (
        f"pruned 1 unreferenced attachment files ({len(BINARY)} bytes) and 1 temp files;"
        " truncated the WAL"
    )
    assert _blobs() == [hashlib.sha256(PNG).hexdigest()]


def test_prune_is_skipped_without_a_healthy_store(
    cb: Callboard, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "empty"))
    result = cb("doctor", "--prune", "--json")
    assert result.json()["pruned"] is None


def test_read_and_history_list_attachments_in_text(cb: Callboard, files: dict[str, Path]) -> None:
    assert (
        cb("--as", "enki", "dm", "nanna", "see file", "--attach", str(files["pixel.png"])).code == 0
    )
    stored = attachments_dir(os.environ) / hashlib.sha256(PNG).hexdigest()
    expected = (
        "cb_000000000001  2026-11-14T09:00:00Z  enki: see file\n"
        f"  attachment at_000000000002  pixel.png  image/png  {len(PNG)} bytes  {stored}\n"
    )
    assert cb("--as", "nanna", "history", "@enki").out == expected
    assert cb("--as", "nanna", "read", "@enki").out == expected


def test_attachment_get_refusals(cb: Callboard, files: dict[str, Path], tmp_path: Path) -> None:
    assert cb("--as", "enki", "dm", "nanna", "f", "--attach", str(files["pixel.png"])).code == 0
    assert cb("--as", "niels", "attachment", "get", "at_000000000002") == (
        3,
        "",
        "callboard: 'niels' is not a member of dm:enki:nanna\n",
    )
    assert cb("--as", "nanna", "attachment", "get", "at_0000000000ff") == (
        3,
        "",
        "callboard: no attachment at_0000000000ff\n",
    )
    existing = tmp_path / "exists.png"
    existing.write_bytes(b"keep")
    assert cb("--as", "nanna", "attachment", "get", "at_000000000002", "--out", str(existing)) == (
        2,
        "",
        f"callboard: --out: {existing} already exists\n",
    )
    assert existing.read_bytes() == b"keep"
    stored = attachments_dir(os.environ) / hashlib.sha256(PNG).hexdigest()
    stored.unlink()
    assert cb("--as", "nanna", "attachment", "get", "at_000000000002") == (
        1,
        "",
        f"callboard: attachment at_000000000002 is missing its file {stored}\n",
    )


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("a.txt", "text/plain"),
        ("a.PNG", "image/png"),
        ("a.json", "application/json"),
        ("noext", "application/octet-stream"),
        ("a.tar.gz", "application/gzip"),
        ("d.json.gz", "application/gzip"),
        ("a.tar.xz", "application/x-xz"),
        ("a.txt.bz2", "application/x-bzip2"),
    ],
)
def test_media_types(filename: str, expected: str) -> None:
    assert media_type(filename) == expected


def test_out_into_a_directory_is_refused_clearly(
    cb: Callboard, files: dict[str, Path], tmp_path: Path
) -> None:
    assert cb("--as", "enki", "dm", "nanna", "f", "--attach", str(files["pixel.png"])).code == 0
    assert cb("--as", "nanna", "attachment", "get", "at_000000000002", "--out", str(tmp_path)) == (
        2,
        "",
        f"callboard: --out: {tmp_path} is a directory; name a file\n",
    )


def test_reusing_a_blob_refreshes_it_so_prune_keeps_it(
    cb: Callboard, files: dict[str, Path]
) -> None:
    png = str(files["pixel.png"])
    assert cb("--as", "enki", "dm", "ghost", "lost", "--attach", png).code == 3
    stored = attachments_dir(os.environ) / hashlib.sha256(PNG).hexdigest()
    os.utime(stored, (1_000_000_000, 1_000_000_000))
    assert cb("--as", "enki", "dm", "nanna", "kept", "--attach", png).code == 0
    assert stored.stat().st_mtime > 1_000_000_000
