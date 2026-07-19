import json
import pytest


@pytest.mark.django_db
def test_register_creates_public_client(client):
    resp = client.post(
        "/oauth/register",
        data=json.dumps({"redirect_uris": ["http://localhost:9999/cb"], "client_name": "Cursor"}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["client_id"]
    assert data["redirect_uris"] == ["http://localhost:9999/cb"]
    assert data["token_endpoint_auth_method"] == "none"


@pytest.mark.django_db
def test_register_rejects_missing_redirect_uris(client):
    resp = client.post("/oauth/register", data=json.dumps({}), content_type="application/json")
    assert resp.status_code == 400
