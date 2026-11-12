"""Version-bound buyer decisions, guided returns, portfolio alerts and evidence packages."""

from app.schemas.platform_operations import (
    BuyerReturn as BuyerReturn,
    OfferChoice as OfferChoice,
    OfferCreate as OfferCreate,
    OfferDecision as OfferDecision,
    PackageCreate as PackageCreate,
    ReturnCreate as ReturnCreate,
    ReturnItem as ReturnItem,
    ReturnUpdate as ReturnUpdate,
    Shipment as Shipment,
)


from app.services.resolution.workspace import ResolutionWorkspace


from app.services.merchant.operation_values import _json as _json, _money as _money
from app.services.merchant.offers import MerchantOffers
from app.services.merchant.returns import MerchantReturns
from app.services.merchant.monitoring import MerchantMonitoring
from app.services.merchant.disputes import DisputePackages


class Operations:
    """Stable facade over focused merchant workflow services."""

    def __init__(self, store):
        self.store = store
        self.workspace = ResolutionWorkspace(store)
        self._offers = MerchantOffers(store, self.workspace)
        self._returns = MerchantReturns(store, self.workspace)
        self._monitoring = MerchantMonitoring(store, self.workspace)
        self._disputes = DisputePackages(store, self.workspace)

    def _invalidate(self, db, case, reason):
        return self._offers._invalidate(db, case, reason)

    _offer = staticmethod(MerchantOffers._offer)

    def offers(self, merchant, case_id):
        return self._offers.offers(merchant, case_id)

    def publish(self, merchant, actor, case_id, payload):
        return self._offers.publish(merchant, actor, case_id, payload)

    def _check_refund_balance(self, db, merchant, case, choices):
        return self._offers._check_refund_balance(db, merchant, case, choices)

    _safe_choice = staticmethod(MerchantOffers._safe_choice)

    def buyer_offers(self, token):
        return self._offers.buyer_offers(token)

    def decide(self, payload):
        return self._offers.decide(payload)

    _return = staticmethod(MerchantReturns._return)

    def return_catalog(self, merchant, case_id):
        return self._returns.return_catalog(merchant, case_id)

    def request_return(self, merchant, actor, case_id, payload):
        return self._returns.request_return(merchant, actor, case_id, payload)

    def update_return(self, merchant, actor, case_id, identifier, payload):
        return self._returns.update_return(
            merchant, actor, case_id, identifier, payload
        )

    def scan(self, merchant, actor="worker", *, moment=None):
        return self._monitoring.scan(merchant, actor, moment=moment)

    def alerts(self, merchant):
        return self._monitoring.alerts(merchant)

    def dashboard(self, merchant):
        return self._monitoring.dashboard(merchant)

    def packages(self, merchant, case_id):
        return self._disputes.packages(merchant, case_id)

    _assurance_sources = staticmethod(DisputePackages._assurance_sources)

    _source_revision = staticmethod(DisputePackages._source_revision)

    def build_package(self, merchant, actor, case_id, payload):
        return self._disputes.build_package(merchant, actor, case_id, payload)

    def package(self, merchant, case_id, identifier, *, review=False, actor=None):
        return self._disputes.package(
            merchant, case_id, identifier, review=review, actor=actor
        )
