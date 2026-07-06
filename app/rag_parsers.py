from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TextFirstParser:
    """RAG-Anything parser adapter with direct text/Markdown support.

    RAG-Anything checks the selected parser installation while initializing the
    runtime, before it knows the input file extension. That makes plain text and
    Markdown ingestion fail when the configured parser's CLI is unavailable,
    even though those formats do not need OCR or document conversion.
    """

    TEXT_FORMATS = {".md", ".txt"}

    def __init__(self, fallback_parser: Any, *, parser_name: str) -> None:
        self.fallback_parser = fallback_parser
        self.parser_name = parser_name

    def check_installation(self) -> bool:
        return True

    def parse_document(
        self,
        file_path: str | Path,
        method: str = "auto",
        output_dir: str | Path | None = None,
        lang: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        path = Path(file_path)
        if path.suffix.lower() in self.TEXT_FORMATS:
            return self.parse_text_file(path, output_dir=output_dir)

        return self.fallback_parser.parse_document(
            file_path=path,
            method=method,
            output_dir=output_dir,
            lang=lang,
            **kwargs,
        )

    def parse_text_file(
        self,
        text_path: str | Path,
        output_dir: str | Path | None = None,
        lang: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del lang, kwargs

        path = Path(text_path)
        if path.suffix.lower() not in self.TEXT_FORMATS:
            raise ValueError(f"Unsupported text format: {path.suffix}")
        if not path.is_file():
            raise FileNotFoundError(f"Text file does not exist: {path}")

        text = _read_text(path)
        content_list = [
            {
                "type": "text",
                "text": text,
                "page_idx": 0,
                "source_file": path.name,
            }
        ]
        _write_parser_artifacts(path, output_dir, content_list)
        logger.info("Parsed text document directly: %s", path)
        return content_list

    def parse_pdf(
        self,
        pdf_path: str | Path,
        output_dir: str | Path | None = None,
        method: str = "auto",
        lang: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return self.fallback_parser.parse_pdf(
            pdf_path=pdf_path,
            output_dir=output_dir,
            method=method,
            lang=lang,
            **kwargs,
        )

    def parse_image(
        self,
        image_path: str | Path,
        output_dir: str | Path | None = None,
        lang: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return self.fallback_parser.parse_image(
            image_path=image_path,
            output_dir=output_dir,
            lang=lang,
            **kwargs,
        )

    def parse_office_doc(
        self,
        doc_path: str | Path,
        output_dir: str | Path | None = None,
        lang: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return self.fallback_parser.parse_office_doc(
            doc_path=doc_path,
            output_dir=output_dir,
            lang=lang,
            **kwargs,
        )


def install_text_first_parser(rag_anything: Any, *, parser_name: str) -> None:
    fallback_parser = getattr(rag_anything, "doc_parser", None)
    if fallback_parser is None or isinstance(fallback_parser, TextFirstParser):
        return

    rag_anything.doc_parser = TextFirstParser(
        fallback_parser=fallback_parser,
        parser_name=parser_name,
    )


def _read_text(path: Path) -> str:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")

    details = "; ".join(errors)
    raise UnicodeDecodeError("text", b"", 0, 1, f"could not decode {path}: {details}")


def _write_parser_artifacts(
    source_path: Path,
    output_dir: str | Path | None,
    content_list: list[dict[str, Any]],
) -> None:
    if output_dir is None:
        return

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stem = source_path.stem
    (output_path / f"{stem}_content_list.json").write_text(
        json.dumps(content_list, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / f"{stem}.md").write_text(content_list[0]["text"], encoding="utf-8")
