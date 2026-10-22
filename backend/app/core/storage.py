import hashlib
import os
from pathlib import Path
from uuid import uuid4
from app.core.errors import AppError


def uid():
    return str(uuid4())


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(root: Path, relative: str):
    candidate = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise AppError("UNSAFE_PATH", "Đường dẫn không hợp lệ.", 400)
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise AppError("UNSAFE_PATH", "Không cho phép symbolic link.", 400)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise AppError("UNSAFE_PATH", "Đường dẫn ngoài vùng dữ liệu.", 400)
    return candidate


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    partial = path.with_name(path.name + "." + uid() + ".partial")
    try:
        with partial.open("xb") as stream:
            os.chmod(partial, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
