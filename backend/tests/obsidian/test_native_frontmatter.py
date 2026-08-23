"""Native Markdown/frontmatter adapter contracts."""

from __future__ import annotations

import json

import pytest
from app.obsidian.infrastructure.markdown.native_frontmatter import (
    NativeMarkdownDocumentParser,
)


class _FakeNativeDocumentModule:
    def compute_contract_version(self) -> int:
        return 1

    def analyze_document_batch_json(self, payload: bytes) -> bytes:
        request = json.loads(payload)
        assert request["documents"][0]["text"].startswith("---")
        return json.dumps(
            {
                "contract_version": 1,
                "analysis_version": 1,
                "results": [
                    {
                        "status": "success",
                        "document_id": "obsidian-markdown-document",
                        "relative_path": "Obsidian/Document.md",
                        "analysis": {
                            "analysis_version": 1,
                            "has_frontmatter": True,
                            "frontmatter": [
                                {
                                    "key": "title",
                                    "value": {"kind": "string", "value": "Case"},
                                },
                                {
                                    "key": "count",
                                    "value": {"kind": "integer", "value": "3"},
                                },
                                {
                                    "key": "ratio",
                                    "value": {"kind": "float", "value": "1.5"},
                                },
                                {
                                    "key": "enabled",
                                    "value": {"kind": "boolean", "value": True},
                                },
                                {"key": "nothing", "value": {"kind": "null"}},
                                {
                                    "key": "tags",
                                    "value": {
                                        "kind": "sequence",
                                        "value": [
                                            {"kind": "string", "value": "one"},
                                            {"kind": "integer", "value": "2"},
                                        ],
                                    },
                                },
                            ],
                            "body": "# Body\n",
                            "frontmatter_source_range": {"start": 0, "end": 1},
                            "frontmatter_content_range": {"start": 0, "end": 1},
                            "body_source_range": {"start": 0, "end": 1},
                            "headings": [],
                        },
                    }
                ],
            }
        ).encode()


def test_native_parser_maps_typed_frontmatter_to_existing_document() -> None:
    document = NativeMarkdownDocumentParser(_FakeNativeDocumentModule()).parse(
        "---\ntitle: Case\n---\n# Body\n"
    )

    assert document.body == "# Body\n"
    assert document.frontmatter["title"] == "Case"
    assert document.frontmatter["count"] == 3
    assert document.frontmatter["ratio"] == 1.5
    assert document.frontmatter["enabled"] is True
    assert document.frontmatter["nothing"] is None
    assert document.frontmatter["tags"] == ("one", 2)


def test_native_parser_preserves_frontmatter_parse_error_message() -> None:
    class _ErrorModule(_FakeNativeDocumentModule):
        def analyze_document_batch_json(self, payload: bytes) -> bytes:
            del payload
            return b'{"contract_version":1,"analysis_version":1,"results":[{"status":"error","document_id":"obsidian-markdown-document","relative_path":"Obsidian/Document.md","error":{"code":"FRONTMATTER_PARSE_ERROR","message":"FRONTMATTER_PARSE_ERROR: unterminated frontmatter","recoverable":true}}]}'

    with pytest.raises(
        ValueError, match="FRONTMATTER_PARSE_ERROR: unterminated frontmatter"
    ):
        NativeMarkdownDocumentParser(_ErrorModule()).parse("---\ntitle: Case\n")
