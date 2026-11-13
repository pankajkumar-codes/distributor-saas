"""Opens an uploaded zip safely (LLD-7 §3 step 3, AC7-13).

A zip is a container for the platform's own report files (Meesho's holds a sales and a
returns workbook). The caller says which entry names a reader of the section accepts;
anything else rejects the whole file, so a stray file can never be read by accident.
Nothing is written to disk: entries are inflated into memory with a hard cap, counted as
they are read, so a small archive that expands enormously is stopped part-way.
"""

import io
import zipfile
import zlib
from collections.abc import Callable

from .files import FileRejected


def open_zip(content: bytes, *, accepts: Callable[[str], bool], max_entries: int,
             max_inflate_bytes: int) -> list[tuple[str, bytes]]:
    """The (name, bytes) of each file in the zip, in archive order. Raises FileRejected
    with a plain reason for a bad archive, a path in a name, too many entries, too much
    inflated data or a file no reader expects."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise FileRejected("this isn't a readable zip file") from exc
    infos = archive.infolist()
    if len(infos) == 0:
        raise FileRejected("the zip is empty")
    if len(infos) > max_entries:
        raise FileRejected(f"the zip holds more than {max_entries} files")
    out: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        if info.is_dir() or "/" in name or "\\" in name or name.startswith(".") or ".." in name or not name.isprintable():
            raise FileRejected("the zip has a folder or an odd file name in it")
        if info.flag_bits & 0x1:
            raise FileRejected("the zip is password protected")
        if name.lower() in seen:
            raise FileRejected("the zip has two files with the same name")
        seen.add(name.lower())
        if not accepts(name):
            raise FileRejected("the zip has a file we don't expect in it")
        if info.file_size > max_inflate_bytes - total:
            raise FileRejected("the zip expands to more than we can read")
        try:
            with archive.open(info) as handle:
                data = handle.read(max_inflate_bytes - total + 1)  # one over the limit proves it is too big
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
            # A damaged entry, or a compression method we don't read, is a bad file, not a job error.
            raise FileRejected("the zip has a damaged or unsupported file in it") from exc
        total += len(data)
        if total > max_inflate_bytes:
            raise FileRejected("the zip expands to more than we can read")
        out.append((name, data))
    return out
