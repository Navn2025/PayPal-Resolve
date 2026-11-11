"""Keep the checked-in consumer contract synchronized across merges."""

import json
from pathlib import Path

from app.main import create_app
from app.settings import Settings


def test_exported_contract_matches_runtime_and_has_resolvable_schema_references():
    stored = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "postman/contracts/resolve.openapi.json"
        ).read_text(encoding="utf-8")
    )
    generated = create_app(settings=Settings(_env_file=None)).openapi()
    generated["servers"] = [
        {"url": "http://127.0.0.1:8000", "description": "Local development"}
    ]
    assert stored == generated, "Regenerate the contract with scripts/export_openapi.py"

    def verify(node):
        if isinstance(node, dict):
            reference = node.get("$ref", "")
            if reference.startswith("#/"):
                target = stored
                for key in reference[2:].split("/"):
                    target = target[key.replace("~1", "/").replace("~0", "~")]
            for value in node.values():
                verify(value)
        elif isinstance(node, list):
            for value in node:
                verify(value)

    verify(stored)
