"""File-type icons and image thumbnails for attachments.

Images get a real preview (decoded from the local bytes); every other file is
represented by a small, flat SVG icon chosen from its extension/MIME type, with
a neutral page icon as the fallback for unknown types.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from todo_snake.ui.icons import load_icon

#: Extension -> bundled icon name.
_EXTENSION_ICONS: dict[str, str] = {
    "pdf": "file-pdf",
    # images
    **dict.fromkeys(
        ("png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "tif", "tiff", "ico", "heic", "avif"),
        "file-image",
    ),
    # text / documents / source
    **dict.fromkeys(
        (
            "txt",
            "md",
            "markdown",
            "log",
            "rtf",
            "doc",
            "docx",
            "odt",
            "tex",
            "json",
            "xml",
            "yml",
            "yaml",
            "toml",
            "ini",
            "cfg",
            "conf",
            "html",
            "htm",
            "css",
            "js",
            "ts",
            "py",
            "sh",
            "c",
            "cpp",
            "h",
            "java",
        ),
        "file-text",
    ),
    # spreadsheets
    **dict.fromkeys(("csv", "tsv", "xls", "xlsx", "ods", "numbers"), "file-spreadsheet"),
    # archives
    **dict.fromkeys(("zip", "gz", "tgz", "tar", "bz2", "xz", "7z", "rar", "zst"), "file-archive"),
    # audio
    **dict.fromkeys(
        ("mp3", "wav", "ogg", "oga", "flac", "m4a", "aac", "opus", "wma", "mid", "midi"),
        "file-audio",
    ),
    # video
    **dict.fromkeys(
        ("mp4", "m4v", "mkv", "mov", "avi", "webm", "wmv", "flv", "mpg", "mpeg"),
        "file-video",
    ),
}

#: MIME prefix -> icon name (checked when the extension is not decisive).
_MIME_PREFIX_ICONS: tuple[tuple[str, str], ...] = (
    ("image/", "file-image"),
    ("audio/", "file-audio"),
    ("video/", "file-video"),
    ("text/", "file-text"),
    ("font/", "file"),
)

_IMAGE_EXTENSIONS = frozenset(
    {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "tif", "tiff", "ico", "heic", "avif"}
)

_UNKNOWN_ICON = "file"
_icon_cache: dict[str, QIcon] = {}


def extension(filename: str) -> str:
    """Lower-case extension of ``filename`` without the dot ("" if none)."""
    return Path(filename).suffix.lstrip(".").lower()


def is_image(filename: str, mime: str = "") -> bool:
    return mime.startswith("image/") or extension(filename) in _IMAGE_EXTENSIONS


def icon_name(filename: str, mime: str = "") -> str:
    """Bundled icon *name* for a file's type (never empty)."""
    name = _EXTENSION_ICONS.get(extension(filename))
    if name is None:
        for prefix, candidate in _MIME_PREFIX_ICONS:
            if mime.startswith(prefix):
                return candidate
    return name or _UNKNOWN_ICON


def type_icon(filename: str, mime: str = "") -> QIcon:
    """The bundled icon for a file's type (never ``None``)."""
    return _cached_icon(icon_name(filename, mime))


def image_thumbnail(data: bytes | None, size: int = 48) -> QIcon | None:
    """A square, aspect-preserving preview of ``data``; ``None`` on failure."""
    if not data or QApplication.instance() is None:
        return None
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        return None
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    if not reader.canRead():
        return None
    # Downscale while decoding, so a huge photo never lands in memory in full.
    source = reader.size()
    if source.isValid() and (source.width() > size or source.height() > size):
        reader.setScaledSize(source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        return None
    scaled = QPixmap.fromImage(image).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return QIcon(canvas)


def attachment_icon(
    filename: str, mime: str = "", data: bytes | None = None, size: int = 48
) -> QIcon:
    """Preview for images, a type icon otherwise (always an icon)."""
    if data is not None and is_image(filename, mime):
        thumbnail = image_thumbnail(data, size)
        if thumbnail is not None:
            return thumbnail
    return type_icon(filename, mime)


def _cached_icon(name: str) -> QIcon:
    icon = _icon_cache.get(name)
    if icon is None:
        icon = load_icon(name)
        _icon_cache[name] = icon
    return icon
