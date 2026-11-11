"""Bound query growth without caching authorization or reconciliation state."""
from contextlib import contextmanager

from app.case_operations import CaseOperations, OperationsUpdate, derive
from app.resolution_models import ResolutionCreate
from app.resolution_workspace import ResolutionWorkspace


def test_inbox_batches_triage_and_preserves_filter_pagination(client):
    store = client.app.state.store
    merchant = client.get("/auth/me").json()["id"]
    workspace = ResolutionWorkspace(store)
    cases = [workspace.create(merchant, ResolutionCreate(title=f"Scale case {index}", order_reference=f"SCALE-{index}")) for index in range(105)]
    operations = CaseOperations(store)
    operations.update(cases[0].id, merchant, OperationsUpdate(expected_revision=0, assignee="Warehouse team", waiting_on_customer=True))
    original = store.transaction
    calls = []

    class Counted:
        def __init__(self, connection): self.connection = connection
        def execute(self, statement, parameters=None):
            calls.append(1)
            return self.connection.execute(statement, parameters) if parameters is not None else self.connection.execute(statement)
        def __getattr__(self, name): return getattr(self.connection, name)

    @contextmanager
    def measured(*, write=False):
        with original(write=write) as connection:
            yield Counted(connection)

    store.transaction = measured
    try:
        # More than 100 cases crosses the bounded batch boundary. Search still
        # counts matches after a full page instead of returning a partial total.
        page = operations.inbox(merchant, "all", "scale case", 10, 100)
        assert page.total == 105 and len(page.items) == 5
        assert len(calls) <= 120, "Triage must not issue three extra queries per case"
        calls.clear()
        filtered = operations.inbox(merchant, "waiting_on_customer", "warehouse", 10, 0)
        assert filtered.total == 1 and filtered.items[0].id == cases[0].id
        assert filtered.items[0].operations.assignee == "Warehouse team"
        # Batching is only a read strategy: compare its result with the ordinary
        # single-case projection in a fresh transaction.
        with original() as db:
            row = workspace._case(db, cases[0].id, merchant)
            expected = derive(db, store, row, workspace._view(db, row))
        assert filtered.items[0].operations == expected
    finally:
        store.transaction = original
