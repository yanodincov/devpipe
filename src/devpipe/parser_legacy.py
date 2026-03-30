from __future__ import annotations

import json
import re

from jsonschema import ValidationError, validate


class OutputParseError(ValueError):
    pass


class OutputParser:
    def __init__(self, schema: dict[str, object]) -> None:
        self.schema = schema

    def parse(self, transcript: str) -> dict[str, object]:
        payload = self._extract_json(transcript)
        try:
            validate(payload, self.schema)
        except ValidationError as exc:
            raise OutputParseError(str(exc)) from exc
        return payload

    _ANSI_RE = re.compile(r"\x1b(?:\[[0-9;:?>=<!]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|.)")

    def _extract_json(self, transcript: str) -> dict[str, object]:
        with open("/tmp/devpipe_transcript.txt", "w", errors="replace") as _f:
            _f.write(transcript)
        clean = self._ANSI_RE.sub("", transcript)

        # 1. Fenced ```json block
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", clean, re.DOTALL)
        if fenced:
            raw = fenced.group(1)
            return self._parse_obj(raw)

        # 2. Last JSON object in the output (rightmost { ... })
        for m in reversed(list(re.finditer(r"\{", clean))):
            candidate = clean[m.start():]
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        raise OutputParseError("No JSON object found in runner output")

    def _parse_obj(self, raw: str) -> dict[str, object]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OutputParseError(str(exc)) from exc
        if not isinstance(data, dict):
            raise OutputParseError("Structured output must be a JSON object")
        return data

