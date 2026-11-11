from uuid import uuid4


def test_sql_injection_text_is_data_and_cannot_change_other_records(client):
    text = "'; DROP TABLE cases; -- <script>alert('x')</script>"
    created = client.post("/resolution-cases", json={"title": text, "order_reference": "SECURITY-" + uuid4().hex})
    assert created.status_code == 201
    case_id = created.json()["id"]
    assert client.get("/resolution-cases/" + case_id).json()["title"] == text
    again = client.post("/resolution-cases", json={"title": "Table remains intact"})
    assert again.status_code == 201
    assert client.get("/resolution-cases").status_code == 200


def test_validation_does_not_reflect_password_or_connection_secret(client):
    password = "PRIVATE-NEGATIVE-INPUT-DO-NOT-REFLECT"
    response = client.post("/platform/account/login", json={"email": "not-an-email", "password": password})
    assert response.status_code == 422
    assert password not in response.text
    response = client.put("/platform/connections/not-a-provider", json={"credentials": {"api_key": password}, "expected_revision": -1})
    assert response.status_code in {404, 422}
    assert password not in response.text
