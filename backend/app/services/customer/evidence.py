"""Bounded, downloadable case files submitted by the customer."""

from app.schemas.customer_evidence import (
    CustomerEvidence as CustomerEvidence,
)


from hashlib import sha256
import re
from uuid import uuid4


from app.services.payments.cases import ATTACHMENT_TYPES, MAX_ATTACHMENT, now_text
from app.core.exceptions import StoreError


MAX_CUSTOMER_FILES = 10


def evidence_list(db, case):
    rows = db.execute(
        """SELECT id,filename,content_type,size_bytes,created_at FROM customer_evidence
                         WHERE resolution_id=? AND merchant_id=? ORDER BY created_at,id""",
        (case["id"], case["merchant_id"]),
    )
    return [CustomerEvidence.model_validate(dict(row)) for row in rows]


def _validated_file(filename, content_type, content):
    kind = ATTACHMENT_TYPES.get(content_type)
    if not kind:
        raise StoreError(415, "Use a PDF, PNG or JPEG evidence file.")
    if len(content) > MAX_ATTACHMENT:
        raise StoreError(413, "Evidence file exceeds 2 MiB.")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,119}", filename or "")
        or not filename.lower().endswith(kind[0])
        or not content.startswith(kind[1])
    ):
        raise StoreError(
            422, "The filename or file content does not match the supported file type."
        )


class EvidenceFiles:
    def __init__(self, store):
        from app.services.customer.portal import CustomerPortal

        self.portal = CustomerPortal(store)
        self.store = store

    def _buyer_case(self, db, secret):
        link = self.portal._authorized_link(db, secret)
        return self.portal.workspace._case(
            db, link["resolution_id"], link["merchant_id"]
        )

    def upload(self, secret, filename, content_type, content):
        with self.store.transaction(write=True) as db:
            case = self._buyer_case(db, secret)
            _validated_file(filename, content_type, content)
            digest = sha256(content).hexdigest()
            previous = db.execute(
                """SELECT id,filename,content_type,size_bytes,created_at FROM customer_evidence
                WHERE resolution_id=? AND merchant_id=? AND filename=? AND sha256=?""",
                (case["id"], case["merchant_id"], filename, digest),
            ).fetchone()
            if previous:
                return CustomerEvidence.model_validate(dict(previous))
            if (
                db.execute(
                    "SELECT count(*) FROM customer_evidence WHERE resolution_id=?",
                    (case["id"],),
                ).fetchone()[0]
                >= MAX_CUSTOMER_FILES
            ):
                raise StoreError(409, "This case has reached its customer file limit.")
            file = CustomerEvidence(
                id=uuid4(),
                filename=filename,
                content_type=content_type,
                size_bytes=len(content),
                created_at=now_text(),
            )
            db.execute(
                """INSERT INTO customer_evidence
                (id,resolution_id,merchant_id,filename,content_type,content,size_bytes,sha256,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(file.id),
                    case["id"],
                    case["merchant_id"],
                    filename,
                    content_type,
                    content,
                    len(content),
                    digest,
                    file.created_at.isoformat(),
                ),
            )
            return file

    @staticmethod
    def _download(db, case, file_id):
        file = db.execute(
            """SELECT filename,content_type,content FROM customer_evidence
            WHERE id=? AND resolution_id=? AND merchant_id=?""",
            (str(file_id), case["id"], case["merchant_id"]),
        ).fetchone()
        if file is None:
            raise StoreError(404, "Customer evidence file not found.")
        return tuple(file)

    def buyer_download(self, secret, file_id):
        with self.store.transaction() as db:
            return self._download(db, self._buyer_case(db, secret), file_id)

    def merchant_list(self, case_id, merchant_id):
        with self.store.transaction() as db:
            return evidence_list(
                db, self.portal.workspace._case(db, case_id, merchant_id)
            )

    def merchant_download(self, case_id, merchant_id, file_id):
        with self.store.transaction() as db:
            return self._download(
                db, self.portal.workspace._case(db, case_id, merchant_id), file_id
            )
