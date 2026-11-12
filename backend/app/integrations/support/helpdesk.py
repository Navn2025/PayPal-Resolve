"""Read and attach a Zendesk ticket owned by the configured helpdesk."""

from app.schemas.helpdesk import (
    HelpdeskState as HelpdeskState,
    LinkedTicket as LinkedTicket,
    TicketInput as TicketInput,
)


from datetime import datetime, timezone
import re

import httpx

from app.services.customer.notifications import stamp
from app.core.exceptions import StoreError
from app.services.resolution.workspace import ResolutionWorkspace

ZENDESK_STATES = {"new", "open", "pending", "hold", "solved", "closed"}


class Helpdesk:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings

    def _configuration(self, merchant):
        slug = self.settings.zendesk_subdomain or ""
        token = self.settings.zendesk_oauth_token
        if (
            self.settings.helpdesk_merchant_id != merchant
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug)
            or not token
        ):
            return None
        return slug + ".zendesk.com", token.get_secret_value()

    @staticmethod
    def _ticket(row):
        return LinkedTicket(
            ticket_id=row["ticket_id"],
            status=row["status"],
            checked_at=row["checked_at"],
            url=f"https://{row['host']}/agent/tickets/{row['ticket_id']}",
        )

    def state(self, case_id, merchant):
        config = self._configuration(merchant)
        with self.store.transaction() as db:
            case = ResolutionWorkspace._case(db, case_id, merchant)
            row = db.execute(
                "SELECT * FROM resolution_helpdesk WHERE resolution_id=? AND merchant_id=?",
                (case["id"], case["merchant_id"]),
            ).fetchone()
        return HelpdeskState(
            configured=bool(config),
            ticket=self._ticket(row)
            if row and config and row["host"] == config[0]
            else None,
        )

    def link(self, case_id, merchant, ticket_id, client: httpx.Client):
        prior = self.state(case_id, merchant)
        config = self._configuration(merchant)
        if config is None:
            raise StoreError(503, "Zendesk is not configured for this merchant")
        host, token = config
        try:
            response = client.get(
                f"https://{host}/api/v2/tickets/{ticket_id}",
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
            )
            if response.status_code == 404:
                raise StoreError(404, "Zendesk ticket not found")
            if response.status_code == 429:
                raise StoreError(
                    503, "Zendesk is rate limiting ticket reads; try again later"
                )
            response.raise_for_status()
            data = response.json()
            ticket = data.get("ticket") if isinstance(data, dict) else None
            if (
                not isinstance(ticket, dict)
                or type(ticket.get("id")) is not int
                or ticket["id"] != ticket_id
                or ticket.get("status") not in ZENDESK_STATES
            ):
                raise ValueError("Invalid ticket")
        except (httpx.HTTPError, ValueError, TypeError):
            raise StoreError(502, "Zendesk could not verify this ticket") from None
        now = stamp(datetime.now(timezone.utc))
        with self.store.transaction(write=True) as db:
            case = ResolutionWorkspace._case(db, case_id, merchant)
            current = db.execute(
                "SELECT * FROM resolution_helpdesk WHERE resolution_id=?", (case["id"],)
            ).fetchone()
            current_ticket = (
                self._ticket(current) if current and current["host"] == host else None
            )
            if current_ticket != prior.ticket:
                raise StoreError(409, "The linked ticket changed; reload and try again")
            db.execute(
                """INSERT INTO resolution_helpdesk VALUES (?,?,?,?,?,?)
                   ON CONFLICT(resolution_id) DO UPDATE SET host=excluded.host,ticket_id=excluded.ticket_id,
                   status=excluded.status,checked_at=excluded.checked_at""",
                (
                    case["id"],
                    case["merchant_id"],
                    host,
                    ticket_id,
                    ticket["status"],
                    now,
                ),
            )
            if not prior.ticket or prior.ticket.ticket_id != ticket_id:
                ResolutionWorkspace._event(
                    db,
                    case,
                    "merchant_evidence",
                    "merchant_recorded",
                    {"note": "A Zendesk ticket was linked.", "ticket_id": ticket_id},
                )
        return self.state(case_id, merchant)
