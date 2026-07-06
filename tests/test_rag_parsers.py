from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.rag_parsers import TextFirstParser, install_text_first_parser


class FakeFallbackParser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def check_installation(self) -> bool:
        return False

    def parse_document(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("parse_document", kwargs))
        return [{"type": "text", "text": "delegated"}]

    def parse_pdf(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("parse_pdf", kwargs))
        return [{"type": "text", "text": "pdf"}]

    def parse_image(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("parse_image", kwargs))
        return [{"type": "text", "text": "image"}]

    def parse_office_doc(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("parse_office_doc", kwargs))
        return [{"type": "text", "text": "office"}]


def test_text_first_parser_handles_markdown_without_fallback_install(tmp_path: Path) -> None:
    source = tmp_path / "Deities & Mythology.md"
    output_dir = tmp_path / "output"
    source.write_text("# Pantheon\n\nAstra keeps the sky map.", encoding="utf-8")
    fallback = FakeFallbackParser()
    parser = TextFirstParser(fallback, parser_name="mineru")

    assert parser.check_installation() is True

    content_list = parser.parse_document(source, output_dir=output_dir)

    assert content_list == [
        {
            "type": "text",
            "text": "# Pantheon\n\nAstra keeps the sky map.",
            "page_idx": 0,
            "source_file": "Deities & Mythology.md",
        }
    ]
    assert fallback.calls == []
    assert (output_dir / "Deities & Mythology_content_list.json").is_file()
    assert (output_dir / "Deities & Mythology.md").read_text(encoding="utf-8") == (
        "# Pantheon\n\nAstra keeps the sky map."
    )


def test_text_first_parser_delegates_non_text_documents(tmp_path: Path) -> None:
    source = tmp_path / "manual.pdf"
    source.write_bytes(b"%PDF-1.7")
    fallback = FakeFallbackParser()
    parser = TextFirstParser(fallback, parser_name="mineru")

    content_list = parser.parse_document(source, method="ocr", output_dir=tmp_path / "out")

    assert content_list == [{"type": "text", "text": "delegated"}]
    assert fallback.calls == [
        (
            "parse_document",
            {
                "file_path": source,
                "method": "ocr",
                "output_dir": tmp_path / "out",
                "lang": None,
            },
        )
    ]


def test_install_text_first_parser_is_idempotent() -> None:
    class FakeRAGAnything:
        def __init__(self) -> None:
            self.doc_parser = FakeFallbackParser()

    rag_anything = FakeRAGAnything()

    install_text_first_parser(rag_anything, parser_name="mineru")
    first_parser = rag_anything.doc_parser
    install_text_first_parser(rag_anything, parser_name="mineru")

    assert isinstance(first_parser, TextFirstParser)
    assert rag_anything.doc_parser is first_parser


def test_text_first_parser_rejects_missing_text_file(tmp_path: Path) -> None:
    parser = TextFirstParser(FakeFallbackParser(), parser_name="mineru")

    with pytest.raises(FileNotFoundError):
        parser.parse_text_file(tmp_path / "missing.md")
