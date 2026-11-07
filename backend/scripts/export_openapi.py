"""Export the public contract without starting a server or initializing storage."""

import argparse
import json
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import create_app
from app.settings import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND_DIR.parent / "postman/contracts/resolve.openapi.json",
    )
    args = parser.parse_args()
    schema = create_app(settings=Settings(_env_file=None)).openapi()
    schema["servers"] = [
        {"url": "http://127.0.0.1:8000", "description": "Local development"}
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print("Exported Resolve OpenAPI contract")


if __name__ == "__main__":
    main()
