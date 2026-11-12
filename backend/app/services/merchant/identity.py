"""Individual workspace identities; existing merchant keys remain administrator credentials."""

from app.core.security import (
    password_hash as password_hash,
    password_matches as password_matches,
)

from app.schemas.identity import (
    AcceptInvite as AcceptInvite,
    AccountInput as AccountInput,
    Input as Input,
    Invite as Invite,
    OwnerAccount as OwnerAccount,
    Signup as Signup,
    StaffUpdate as StaffUpdate,
)


from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import secrets
from uuid import uuid4


from app.core.exceptions import StoreError


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def digest(value):
    return sha256(value.encode()).hexdigest()


def audit(db, merchant, actor, action, resource=None, **data):
    db.execute(
        "INSERT INTO platform_audit VALUES (?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(merchant),
            actor,
            action,
            str(resource) if resource else None,
            now(),
            json.dumps(data, separators=(",", ":")),
        ),
    )


class Identities:
    def __init__(self, store):
        self.store = store

    def throttle(self, purpose, identity, limit):
        # A separate committed transaction means failed authentication consumes a slot.
        key = digest(purpose + ":" + identity.lower())
        with self.store.transaction(write=True) as db:
            stamp = now()
            row = db.execute(
                "SELECT * FROM platform_auth_limits WHERE id=?", (key,)
            ).fetchone()
            count = row["attempts"] if row and row["expires_at"] > stamp else 0
            if count >= limit:
                raise StoreError(429, "Too many attempts; try again in fifteen minutes")
            expiry = (
                row["expires_at"]
                if count
                else (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            )
            db.execute(
                "INSERT INTO platform_auth_limits VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET attempts=excluded.attempts,expires_at=excluded.expires_at",
                (key, count + 1, expiry),
            )

    @staticmethod
    def _staff_view(row):
        return {
            k: row[k]
            for k in (
                "id",
                "merchant_id",
                "email",
                "name",
                "role",
                "active",
                "created_at",
            )
        }

    @staticmethod
    def _session(db, staff):
        token = "rweb_" + secrets.token_urlsafe(32)
        expiry = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
        db.execute(
            "INSERT INTO platform_sessions VALUES (?,?,?,?)",
            (digest(token), staff["id"], now(), expiry),
        )
        merchant = db.execute(
            "SELECT * FROM merchants WHERE id=?", (staff["merchant_id"],)
        ).fetchone()
        return {
            "token": token,
            "merchant": dict(merchant),
            "method": "password",
            "expires_at": expiry,
            "paypal_linked": False,
            "staff": Identities._staff_view(staff),
        }

    def signup(self, payload, peer):
        self.throttle("signup", peer, 5)
        encoded = password_hash(payload.password.get_secret_value())
        with self.store.transaction(write=True) as db:
            if db.execute(
                "SELECT 1 FROM platform_staff WHERE email=?", (payload.email.lower(),)
            ).fetchone():
                raise StoreError(409, "This account already exists; sign in instead")
            merchant, staff, stamp = str(uuid4()), str(uuid4()), now()
            db.execute(
                "INSERT INTO merchants VALUES (?,?,?)",
                (merchant, payload.workspace, stamp),
            )
            db.execute(
                "INSERT INTO platform_staff VALUES (?,?,?,?,?,?,1,?)",
                (
                    staff,
                    merchant,
                    payload.email.lower(),
                    payload.name,
                    encoded,
                    "owner",
                    stamp,
                ),
            )
            audit(db, merchant, staff, "workspace_created", merchant)
            return self._session(
                db,
                db.execute(
                    "SELECT * FROM platform_staff WHERE id=?", (staff,)
                ).fetchone(),
            )

    def claim(self, merchant, actor, payload):
        encoded = password_hash(payload.password.get_secret_value())
        with self.store.transaction(write=True) as db:
            if db.execute(
                "SELECT 1 FROM platform_staff WHERE merchant_id=? AND role='owner' AND active=1",
                (str(merchant),),
            ).fetchone():
                raise StoreError(409, "This workspace already has an owner account")
            if db.execute(
                "SELECT 1 FROM platform_staff WHERE email=?", (payload.email.lower(),)
            ).fetchone():
                raise StoreError(409, "This email already has an account")
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO platform_staff VALUES (?,?,?,?,?,'owner',1,?)",
                (
                    identifier,
                    str(merchant),
                    payload.email.lower(),
                    payload.name,
                    encoded,
                    now(),
                ),
            )
            audit(db, merchant, actor, "owner_account_created", identifier)
            return self._session(
                db,
                db.execute(
                    "SELECT * FROM platform_staff WHERE id=?", (identifier,)
                ).fetchone(),
            )

    def login(self, payload, peer):
        self.throttle("login-email", payload.email, 10)
        self.throttle("login-peer", peer, 50)
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM platform_staff WHERE email=? AND active=1",
                (payload.email.lower(),),
            ).fetchone()
        # Spend comparable password work even when the email does not exist.
        encoded = row["password_hash"] if row else "00" * 16 + ":" + "00" * 32
        if (
            not password_matches(payload.password.get_secret_value(), encoded)
            or not row
        ):
            raise StoreError(401, "Invalid account credentials")
        with self.store.transaction(write=True) as db:
            current = db.execute(
                "SELECT * FROM platform_staff WHERE id=? AND active=1", (row["id"],)
            ).fetchone()
            if not current or current["password_hash"] != encoded:
                raise StoreError(401, "Invalid account credentials")
            audit(db, current["merchant_id"], current["id"], "staff_signed_in")
            return self._session(db, current)

    def session(self, token):
        with self.store.transaction() as db:
            return self.session_in(db, token)

    def session_in(self, db, token):
        row = db.execute(
            "SELECT u.*,s.expires_at,m.name AS merchant_name,m.created_at AS merchant_created_at FROM platform_sessions s JOIN platform_staff u ON u.id=s.staff_id JOIN merchants m ON m.id=u.merchant_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
            (digest(token), now()),
        ).fetchone()
        if not row:
            return None
        return {
            "merchant": {
                "id": row["merchant_id"],
                "name": row["merchant_name"],
                "created_at": row["merchant_created_at"],
            },
            "method": "password",
            "expires_at": row["expires_at"],
            "paypal_linked": False,
            "staff": self._staff_view(row),
        }

    def invite(self, merchant, actor, payload):
        token, identifier = "rinv_" + secrets.token_urlsafe(32), str(uuid4())
        with self.store.transaction(write=True) as db:
            if db.execute(
                "SELECT 1 FROM platform_staff WHERE email=?", (payload.email.lower(),)
            ).fetchone():
                raise StoreError(409, "That email already has an account")
            db.execute(
                "UPDATE platform_invites SET used_at=? WHERE merchant_id=? AND email=? AND used_at IS NULL",
                (now(), str(merchant), payload.email.lower()),
            )
            expiry = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
            db.execute(
                "INSERT INTO platform_invites VALUES (?,?,?,?,?,?,NULL,?)",
                (
                    identifier,
                    str(merchant),
                    payload.email.lower(),
                    payload.role,
                    digest(token),
                    expiry,
                    now(),
                ),
            )
            audit(db, merchant, actor, "staff_invited", identifier, role=payload.role)
        return {"id": identifier, "token": token, "expires_at": expiry}

    def accept(self, payload, peer):
        self.throttle("invite", peer, 20)
        encoded = password_hash(payload.password.get_secret_value())
        with self.store.transaction(write=True) as db:
            row = db.execute(
                "SELECT * FROM platform_invites WHERE token_hash=? AND used_at IS NULL AND expires_at>? AND email=?",
                (
                    digest(payload.token.get_secret_value()),
                    now(),
                    payload.email.lower(),
                ),
            ).fetchone()
            if not row:
                raise StoreError(404, "Invitation is invalid, expired or already used")
            if db.execute(
                "SELECT 1 FROM platform_staff WHERE email=?", (row["email"],)
            ).fetchone():
                raise StoreError(409, "This account already exists")
            identifier = str(uuid4())
            db.execute(
                "INSERT INTO platform_staff VALUES (?,?,?,?,?,?,1,?)",
                (
                    identifier,
                    row["merchant_id"],
                    row["email"],
                    payload.name,
                    encoded,
                    row["role"],
                    now(),
                ),
            )
            db.execute(
                "UPDATE platform_invites SET used_at=? WHERE id=?", (now(), row["id"])
            )
            audit(db, row["merchant_id"], identifier, "staff_joined", identifier)
            return self._session(
                db,
                db.execute(
                    "SELECT * FROM platform_staff WHERE id=?", (identifier,)
                ).fetchone(),
            )

    def team(self, merchant):
        with self.store.transaction() as db:
            return {
                "items": [
                    self._staff_view(r)
                    for r in db.execute(
                        "SELECT * FROM platform_staff WHERE merchant_id=? ORDER BY created_at,id",
                        (str(merchant),),
                    )
                ]
            }

    def update(self, merchant, actor, identifier, payload):
        with self.store.transaction(write=True) as db:
            row = db.execute(
                "SELECT * FROM platform_staff WHERE id=? AND merchant_id=?",
                (str(identifier), str(merchant)),
            ).fetchone()
            if not row:
                raise StoreError(404, "Staff account not found")
            if (
                row["role"] == "owner"
                and row["active"]
                and (not payload.active or payload.role != "owner")
            ):
                owners = db.execute(
                    "SELECT count(*) FROM platform_staff WHERE merchant_id=? AND role='owner' AND active=1",
                    (str(merchant),),
                ).fetchone()[0]
                if owners <= 1:
                    raise StoreError(409, "Keep at least one active owner")
            db.execute(
                "UPDATE platform_staff SET role=?,active=? WHERE id=?",
                (payload.role, int(payload.active), row["id"]),
            )
            db.execute("DELETE FROM platform_sessions WHERE staff_id=?", (row["id"],))
            audit(
                db,
                merchant,
                actor,
                "staff_access_changed",
                row["id"],
                role=payload.role,
                active=payload.active,
            )
        return self.team(merchant)


def enforce_role(request, merchant, token):
    from app.services.merchant.auth import MerchantAuth

    info = getattr(request.state, "merchant_session", None)
    # Re-check writes at the authorization gate; reuse only this request's read identity.
    if token.startswith("rweb_") and (
        info is None or request.method not in ("GET", "HEAD", "OPTIONS")
    ):
        info = MerchantAuth(
            request.app.state.store, request.app.state.settings
        ).session(token)
    if token.startswith("rweb_") and info is None:
        raise StoreError(401, "Sign in to your merchant workspace")
    staff = info.staff if info and info.staff else None
    role = staff["role"] if staff else "owner"
    actor = staff["id"] if staff else "credential:" + digest(token)[:20]
    request.state.actor_id, request.state.staff_role = actor, role
    request.state.audit_merchant = merchant.id
    path = request.url.path
    write = (
        request.method not in ("GET", "HEAD", "OPTIONS") and path != "/aftercare/status"
    )
    restricted = (
        (write and role == "viewer")
        or (
            "/refund-approvals" in path
            and write
            and role not in ("owner", "manager", "finance")
        )
        or ("/refund-executions" in path and write and role not in ("owner", "finance"))
        or (
            write
            and any(
                p in path
                for p in (
                    "/team",
                    "/connections",
                    "/commerce-keys",
                    "/sdk-keys",
                    "/support-keys",
                )
            )
            and role != "owner"
        )
        or (
            write
            and "/dispute-packages" in path
            and path.endswith("/review")
            and role not in ("owner", "manager")
        )
    )
    restricted = (
        restricted
        or (write and "/return-policy" in path and role != "owner")
        or (
            write
            and path.endswith("/disputes")
            and role not in ("owner", "manager", "finance")
        )
        or (
            write
            and path.endswith("/refund-traces")
            and role not in ("owner", "finance")
        )
    )
    if restricted:
        raise StoreError(403, "Your workspace role does not permit this action")
    if write and not getattr(request.state, "audit_intent", None):
        identifier = str(uuid4())
        with request.app.state.store.transaction(write=True) as db:
            audit(
                db,
                merchant.id,
                actor,
                "request_started",
                identifier,
                method=request.method,
                path=path,
            )
        request.state.audit_intent = identifier
