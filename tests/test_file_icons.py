"""Tests for attachment file-type icons and image thumbnails."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice, QSize
from PySide6.QtGui import QImage

from todo_snake.ui import file_icons


def _png_bytes(width: int = 120, height: int = 60, color: int = 0xFF3366) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(color)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_extension_and_is_image():
    assert file_icons.extension("Report.PDF") == "pdf"
    assert file_icons.extension("no-extension") == ""
    assert file_icons.is_image("photo.JPG")
    assert file_icons.is_image("blob", "image/png")
    assert not file_icons.is_image("notes.txt")


def test_type_icon_maps_known_extensions(qapp):
    assert file_icons.icon_name("a.pdf") == "file-pdf"
    assert file_icons.icon_name("a.xlsx") == "file-spreadsheet"
    assert file_icons.icon_name("a.mp3") == "file-audio"
    assert file_icons.icon_name("a.mp4") == "file-video"
    assert file_icons.icon_name("a.zip") == "file-archive"
    assert file_icons.icon_name("a.md") == "file-text"
    assert file_icons.icon_name("a.png") == "file-image"


def test_type_icon_falls_back_by_mime_then_unknown(qapp):
    assert file_icons.icon_name("blob", "image/webp") == "file-image"
    assert file_icons.icon_name("video", "video/mp4") == "file-video"
    unknown = file_icons.type_icon("mystery.xyz")
    assert file_icons.icon_name("mystery.xyz") == "file"
    assert not unknown.isNull()


def test_image_thumbnail_is_a_square_preview(qapp):
    icon = file_icons.image_thumbnail(_png_bytes())
    assert icon is not None
    pixmap = icon.pixmap(QSize(48, 48))
    assert (pixmap.width(), pixmap.height()) == (48, 48)


def test_image_thumbnail_rejects_garbage(qapp):
    assert file_icons.image_thumbnail(b"this is not an image") is None
    assert file_icons.image_thumbnail(b"") is None
    assert file_icons.image_thumbnail(None) is None


def test_attachment_icon_prefers_thumbnail_then_type_icon(qapp):
    thumbnail = file_icons.attachment_icon("photo.png", "image/png", _png_bytes())
    assert thumbnail.cacheKey() != file_icons.type_icon("photo.png", "image/png").cacheKey()

    # No local bytes (or a broken image): fall back to the type icon.
    assert (
        file_icons.attachment_icon("photo.png", "image/png").cacheKey()
        == file_icons.type_icon("photo.png", "image/png").cacheKey()
    )
    assert (
        file_icons.attachment_icon("photo.png", "image/png", b"broken").cacheKey()
        == file_icons.type_icon("photo.png", "image/png").cacheKey()
    )
