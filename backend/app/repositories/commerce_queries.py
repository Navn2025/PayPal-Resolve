"""Order association lookup; authorization stays inside the service transaction."""


def order_for_resolution(connection, merchant_id, resolution_id):
    return connection.execute(
        "SELECT source,order_reference FROM commerce_orders WHERE merchant_id=? AND resolution_id=?",
        (merchant_id, resolution_id),
    ).fetchone()
