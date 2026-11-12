"""Compatibility and dependency boundaries introduced by the module migration."""

import ast
from importlib import import_module
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("settings", "core.config"),
        ("models", "schemas.payments"),
        ("storage", "repositories.sqlite"),
        ("postgres", "repositories.postgres"),
        ("paypal", "integrations.paypal.client"),
        ("inference", "integrations.llm.providers"),
        ("ai_extraction", "services.ai.extraction"),
        ("investigations", "services.ai.investigations"),
        ("platform_operations", "services.merchant.operations"),
        ("worker", "workers.refunds"),
    ],
)
def test_legacy_imports_share_the_canonical_module_and_patch_namespace(
    legacy, canonical
):
    # A reexported copy of a module would silently disconnect monkeypatches and DI.
    assert import_module("app." + legacy) is import_module("app." + canonical)


def test_relocation_keeps_backend_relative_runtime_assets():
    from app.core.config import BACKEND_DIR, Settings
    from app.integrations.email.smtp import MAILER
    from app.repositories.postgres import MIGRATIONS
    from app.testing.investigations import LABELS

    backend = Path(__file__).resolve().parents[1]
    assert BACKEND_DIR == backend
    assert (
        Settings(_env_file=None, database_path="data/probe.sqlite3").database_path
        == backend / "data/probe.sqlite3"
    )
    assert MAILER == backend / "mailer"
    assert MIGRATIONS == backend / "migrations/postgres"
    assert LABELS == backend / "evaluation/investigations.json"


def test_contracts_are_independent_of_workflow_and_storage_modules():
    app = Path(__file__).resolve().parents[1] / "app"
    for path in (app / "schemas").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("app.services", "app.repositories", "app.api")
                ), path


def test_http_endpoints_do_not_execute_sql():
    app = Path(__file__).resolve().parents[1] / "app"
    for path in (app / "api/endpoints").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in ("execute", "executemany"), path
