"""Authenticated Zendesk reads, source-preserving imports and durable webhook jobs."""

from app.schemas.platform_imports import (
    ImportMatch as ImportMatch,
    TicketImport as TicketImport,
)


import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import re
from urllib.parse import urlsplit
from uuid import UUID, uuid4


from app.schemas.extraction import ChatMessage
from app.core.extraction_config import ExtractionSettings
from app.services.ai.extraction import current_data_policy, extract_promises
from app.services.ai.usage import ExtractionUsage
from app.services.commerce.orders import CommerceWorkspace
from app.core.exceptions import StoreError
from app.services.merchant.connections import Connections, provider_json
from app.services.merchant.identity import audit, now
from app.services.resolution.workspace import ResolutionWorkspace

USAGE = ExtractionUsage()


def imported_transcript(store, case_id, merchant):
    with store.transaction() as db:
        rows = db.execute(
            "SELECT m.* FROM platform_ticket_messages m JOIN platform_imports i ON i.id=m.import_id WHERE i.case_id=? AND i.merchant_id=? ORDER BY m.sent_at DESC,m.id DESC LIMIT 200",
            (str(case_id), str(merchant)),
        ).fetchall()
    return [
        ChatMessage(
            id="zd:" + r["source_id"],
            sender=r["sender"],
            text=r["body"],
            sent_at=r["sent_at"],
        )
        for r in reversed(rows)
    ]


class Imports:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.connections = Connections(store, settings)

    def _configuration(self, merchant):
        row = self.connections.get(merchant, "zendesk")
        if not row or not row["enabled"]:
            raise StoreError(
                503, "Connect and enable this workspace's Zendesk account first"
            )
        return row, json.loads(row["config_json"]), self.connections.decrypt(row)

    def fetch(self, merchant, actor, ticket_id, http):
        connection, cfg, secret = self._configuration(merchant)
        origin = "https://" + cfg["subdomain"] + ".zendesk.com"
        headers = {
            "Authorization": "Bearer " + secret["oauth_token"],
            "Accept": "application/json",
        }
        ticket = provider_json(
            http, origin + f"/api/v2/tickets/{ticket_id}.json", headers=headers
        ).get("ticket")
        if (
            not isinstance(ticket, dict)
            or type(ticket.get("id")) is not int
            or ticket.get("id") != ticket_id
        ):
            raise StoreError(502, "Zendesk returned a different ticket")
        comments, next_url, seen = (
            [],
            origin + f"/api/v2/tickets/{ticket_id}/comments.json?page[size]=100",
            set(),
        )
        for _ in range(10):
            if not next_url:
                break
            parsed = urlsplit(next_url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != urlsplit(origin).netloc
                or parsed.path != f"/api/v2/tickets/{ticket_id}/comments.json"
                or parsed.username
                or parsed.password
            ):
                raise StoreError(
                    502, "Zendesk pagination left the approved ticket endpoint"
                )
            if next_url in seen:
                raise StoreError(502, "Zendesk returned a repeated pagination cursor")
            seen.add(next_url)
            page = provider_json(http, next_url, headers=headers)
            if not isinstance(page.get("comments"), list):
                raise StoreError(502, "Zendesk comments are invalid")
            comments.extend(page["comments"])
            next_url = (
                (page.get("links") or {}).get("next")
                if page.get("meta", {}).get("has_more")
                else page.get("next_page")
            )
            if page.get("meta", {}).get("has_more") and not next_url:
                raise StoreError(502, "Zendesk omitted the next comments cursor")
        if next_url or len(comments) > 1000:
            raise StoreError(
                422, "Ticket exceeds the bounded import; review it manually"
            )
        if any(not isinstance(c, dict) for c in comments):
            raise StoreError(502, "Zendesk returned malformed comments")
        authors = sorted(
            {c.get("author_id") for c in comments if type(c.get("author_id")) is int}
        )
        roles = {}
        for offset in range(0, len(authors), 100):
            page = provider_json(
                http,
                origin + "/api/v2/users/show_many.json",
                headers=headers,
                params={"ids": ",".join(map(str, authors[offset : offset + 100]))},
            )
            if not isinstance(page.get("users"), list) or any(
                not isinstance(u, dict) for u in page["users"]
            ):
                raise StoreError(502, "Zendesk returned malformed author records")
            for user in page.get("users", []):
                roles[user.get("id")] = user.get("role")
        messages = []
        for comment in comments:
            role = roles.get(comment.get("author_id"))
            if (
                role not in ("agent", "admin", "end-user")
                or type(comment.get("id")) is not int
                or type(comment.get("public")) is not bool
            ):
                raise StoreError(
                    502, "A comment's author or visibility could not be verified"
                )
            body = comment.get("plain_body") or comment.get("body")
            if not isinstance(body, str) or not 1 <= len(body) <= 4000:
                raise StoreError(
                    422,
                    "A comment requires manual review because of its length or format",
                )
            try:
                stamp = datetime.fromisoformat(
                    comment["created_at"].replace("Z", "+00:00")
                )
                if stamp.tzinfo is None:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise StoreError(502, "A comment has no verifiable timestamp") from None
            messages.append(
                (
                    str(comment["id"]),
                    "merchant" if role in ("agent", "admin") else "buyer",
                    body,
                    int(comment["public"]),
                    stamp.astimezone(timezone.utc).isoformat(),
                )
            )
        reference = ticket.get("external_id")
        reference = (
            reference.strip()
            if isinstance(reference, str) and 0 < len(reference.strip()) <= 160
            else None
        )
        with self.store.transaction(write=True) as db:
            current = db.execute(
                "SELECT revision FROM platform_connections WHERE merchant_id=? AND provider='zendesk'",
                (str(merchant),),
            ).fetchone()
            if not current or current["revision"] != connection["revision"]:
                raise StoreError(409, "Zendesk connection changed during import")
            row = db.execute(
                "SELECT * FROM platform_imports WHERE merchant_id=? AND provider='zendesk' AND ticket_id=?",
                (str(merchant), str(ticket_id)),
            ).fetchone()
            if row and row["case_id"] and row["order_reference"] != reference:
                raise StoreError(
                    409,
                    "This ticket's order reference changed; review the existing case match manually",
                )
            identifier = row["id"] if row else str(uuid4())
            case_id = row["case_id"] if row else None
            candidates = (
                db.execute(
                    "SELECT id FROM resolution_cases WHERE merchant_id=? AND order_reference=?",
                    (str(merchant), reference),
                ).fetchall()
                if reference
                else []
            )
            # Never use fuzzy text, an email address, or another merchant's order.
            if not case_id and len(candidates) == 1:
                case_id = candidates[0]["id"]
            elif not case_id and not candidates and reference:
                orders = db.execute(
                    "SELECT * FROM commerce_orders WHERE merchant_id=? AND order_reference=?",
                    (str(merchant), reference),
                ).fetchall()
                if len(orders) == 1:
                    from app.schemas.commerce import CommerceSnapshot

                    commerce = CommerceWorkspace(self.store)
                    snapshot = CommerceSnapshot.model_validate_json(
                        orders[0]["snapshot_json"]
                    )
                    matched = commerce._case_for_order(
                        db, merchant, snapshot, orders[0], None
                    )
                    commerce._record_evidence(db, matched, snapshot)
                    case_id = matched["id"]
                    db.execute(
                        "UPDATE commerce_orders SET resolution_id=? WHERE id=? AND merchant_id=?",
                        (case_id, orders[0]["id"], str(merchant)),
                    )
            state = "matched" if case_id else "needs_match"
            title = str(ticket.get("subject") or "Zendesk ticket")[:160]
            db.execute(
                "INSERT INTO platform_imports VALUES (?,?,'zendesk',?,?,?,?,?,NULL,?,?) ON CONFLICT(merchant_id,provider,ticket_id) DO UPDATE SET title=excluded.title,order_reference=excluded.order_reference,state=excluded.state,updated_at=excluded.updated_at",
                (
                    identifier,
                    str(merchant),
                    str(ticket_id),
                    case_id,
                    reference,
                    title,
                    state,
                    now(),
                    now(),
                ),
            )
            for source, sender, body, public, sent in messages:
                prior = db.execute(
                    "SELECT * FROM platform_ticket_messages WHERE import_id=? AND source_id=?",
                    (identifier, source),
                ).fetchone()
                if prior and (
                    prior["body"],
                    prior["sender"],
                    prior["public"],
                    prior["sent_at"],
                ) != (body, sender, public, sent):
                    raise StoreError(
                        409,
                        "A previously imported source comment changed; review manually",
                    )
                db.execute(
                    "INSERT INTO platform_ticket_messages VALUES (?,?,?,?,?,?,?) ON CONFLICT(import_id,source_id) DO NOTHING",
                    (str(uuid4()), identifier, source, sender, body, public, sent),
                )
            audit(
                db,
                merchant,
                actor,
                "ticket_imported",
                identifier,
                ticket_id=str(ticket_id),
                comment_count=len(messages),
                state=state,
            )
        if case_id:
            self.propose(merchant, identifier)
        return self.get(merchant, identifier)

    def propose(self, merchant, identifier):
        import groq

        item = self.get(merchant, identifier)
        if not item["case_id"]:
            return
        cfg = ExtractionSettings()
        client = (
            groq.Groq(
                api_key=cfg.groq_key.get_secret_value(),
                timeout=cfg.timeout_seconds,
                max_retries=1,
            )
            if cfg.enabled
            and cfg.groq_key
            and current_data_policy() == "minimized_standard_retention"
            else None
        )
        try:
            result = extract_promises(
                UUID(item["case_id"]),
                imported_transcript(self.store, item["case_id"], merchant),
                client,
                cfg,
                "case_conversation",
                data_policy=current_data_policy(),
                usage=USAGE,
                merchant_id=merchant,
            )
        finally:
            if client:
                client.close()
        with self.store.transaction(write=True) as db:
            db.execute(
                "UPDATE platform_imports SET suggestions_json=? WHERE id=? AND merchant_id=? AND case_id=?",
                (
                    result.model_dump_json(),
                    str(identifier),
                    str(merchant),
                    item["case_id"],
                ),
            )

    def list(self, merchant):
        with self.store.transaction() as db:
            return {
                "items": [
                    self._view(r)
                    for r in db.execute(
                        "SELECT * FROM platform_imports WHERE merchant_id=? ORDER BY updated_at DESC LIMIT 200",
                        (str(merchant),),
                    )
                ]
            }

    @staticmethod
    def _view(row):
        value = dict(row)
        raw = value.pop("suggestions_json")
        value["suggestions"] = json.loads(raw) if raw else None
        return value

    def get(self, merchant, identifier):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM platform_imports WHERE id=? AND merchant_id=?",
                (str(identifier), str(merchant)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Ticket import not found")
            return {
                **self._view(row),
                "messages": [
                    dict(m)
                    for m in db.execute(
                        "SELECT source_id,sender,body,public,sent_at FROM platform_ticket_messages WHERE import_id=? ORDER BY sent_at,source_id",
                        (row["id"],),
                    )
                ],
            }

    def match(self, merchant, actor, identifier, case_id):
        with self.store.transaction(write=True) as db:
            case = ResolutionWorkspace._case(db, case_id, merchant)
            row = db.execute(
                "SELECT * FROM platform_imports WHERE id=? AND merchant_id=?",
                (str(identifier), str(merchant)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Ticket import not found")
            if row["case_id"] and row["case_id"] != case["id"]:
                raise StoreError(409, "This ticket already belongs to another case")
            db.execute(
                "UPDATE platform_imports SET case_id=?,state='matched',updated_at=? WHERE id=?",
                (case["id"], now(), row["id"]),
            )
            ResolutionWorkspace._event(
                db,
                case,
                "merchant_evidence",
                "merchant_recorded",
                {
                    "evidence_type": "support_ticket",
                    "import_id": row["id"],
                    "ticket_id": row["ticket_id"],
                },
            )
            audit(
                db,
                merchant,
                actor,
                "ticket_match_confirmed",
                identifier,
                case_id=case["id"],
            )
        self.propose(merchant, identifier)
        return self.get(merchant, identifier)

    def webhook(self, merchant, body, headers):
        _, _, secret = self._configuration(merchant)
        signature, timestamp = (
            headers.get("x-zendesk-webhook-signature", ""),
            headers.get("x-zendesk-webhook-signature-timestamp", ""),
        )
        key = secret.get("webhook_secret")
        try:
            sent = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if (
                not key
                or sent.tzinfo is None
                or abs((datetime.now(timezone.utc) - sent).total_seconds()) > 300
            ):
                raise ValueError()
            expected = base64.b64encode(
                hmac.new(key.encode(), timestamp.encode() + body, sha256).digest()
            ).decode()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
        except (ValueError, TypeError):
            raise StoreError(401, "Webhook signature or timestamp is invalid") from None
        try:
            data = json.loads(body)
            ticket = str(data["ticket_id"])
            event = headers.get("x-zendesk-webhook-invocation-id") or data["event_id"]
            if (
                not re.fullmatch(r"[0-9]{1,16}", ticket)
                or not isinstance(event, str)
                or not re.fullmatch(r"[\x20-\x7e]{1,160}", event)
            ):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise StoreError(
                422,
                "Configure a ticket_id and stable event_id in the Zendesk trigger payload",
            ) from None
        fingerprint = sha256(body).hexdigest()
        with self.store.transaction(write=True) as db:
            prior = db.execute(
                "SELECT * FROM platform_webhook_jobs WHERE merchant_id=? AND provider='zendesk' AND event_id=?",
                (str(merchant), event),
            ).fetchone()
            if prior:
                if prior["body_hash"] != fingerprint:
                    raise StoreError(409, "Webhook event ID has conflicting content")
                return {"accepted": True, "duplicate": True}
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO platform_webhook_jobs VALUES (?,?,'zendesk',?,?,?,'queued',0,?,NULL,NULL,?)",
                (identifier, str(merchant), event, fingerprint, ticket, now(), now()),
            )
            return {"accepted": True, "duplicate": False}


def process_jobs(store, settings, http, limit=20):
    importer, processed = Imports(store, settings), 0
    for _ in range(limit):
        lease = str(uuid4())
        with store.transaction(write=True) as db:
            db.execute(
                "UPDATE platform_webhook_jobs SET state='failed',error='Import retry budget exhausted' WHERE state='processing' AND attempts>=5 AND next_attempt_at<=?",
                (now(),),
            )
            row = db.execute(
                "SELECT * FROM platform_webhook_jobs WHERE state IN ('queued','retry','processing') AND next_attempt_at<=? AND attempts<5 ORDER BY created_at,id LIMIT 1",
                (now(),),
            ).fetchone()
            if not row:
                break
            db.execute(
                "UPDATE platform_webhook_jobs SET state='processing',attempts=attempts+1,lease_id=?,next_attempt_at=? WHERE id=?",
                (
                    lease,
                    (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    row["id"],
                ),
            )
        try:
            importer.fetch(
                row["merchant_id"], "zendesk-worker", int(row["ticket_id"]), http
            )
            state, error = "completed", None
        except StoreError as exc:
            state, error = (
                ("failed" if row["attempts"] >= 4 else "retry"),
                str(exc.detail),
            )
        except Exception:
            state, error = (
                ("failed" if row["attempts"] >= 4 else "retry"),
                "Import needs manual review; provider details omitted",
            )
        with store.transaction(write=True) as db:
            db.execute(
                "UPDATE platform_webhook_jobs SET state=?,error=?,next_attempt_at=? WHERE id=? AND lease_id=?",
                (
                    state,
                    error,
                    (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=min(3600, 30 * 2 ** row["attempts"]))
                    ).isoformat(),
                    row["id"],
                    lease,
                ),
            )
        processed += 1
    return {"processed": processed}
