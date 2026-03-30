from __future__ import annotations

import pytest

from devpipe.parser_legacy import OutputParser, OutputParseError


def test_parser_extracts_json_from_fenced_block() -> None:
    parser = OutputParser(
        {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        }
    )

    payload = parser.parse('Result:\n```json\n{"summary":"ok"}\n```')

    assert payload["summary"] == "ok"


def test_parser_rejects_invalid_output() -> None:
    parser = OutputParser(
        {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        }
    )

    with pytest.raises(OutputParseError):
        parser.parse('{"wrong":"shape"}')
