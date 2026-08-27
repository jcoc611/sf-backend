"""Behaviour of the one-to-many contact addresses relationship."""

from sqlalchemy import inspect

from app.database import engine

BASE = "/api/v1/contacts"

HOME = {"type": "home", "city": "San Francisco", "state": "CA", "country": "USA"}
WORK = {
    "type": "work",
    "street": "1 Market St, Suite 400",
    "city": "San Francisco",
    "state": "CA",
    "postal_code": "94105",
    "country": "USA",
}


def _create(client, payload, **overrides):
    response = client.post(BASE, json={**payload, **overrides})
    assert response.status_code == 201
    return response.json()


def test_create_with_multiple_addresses(client, payload):
    body = _create(client, payload, addresses=[HOME, WORK])
    assert [a["type"] for a in body["addresses"]] == ["home", "work"]
    assert all(a["id"] > 0 for a in body["addresses"])
    assert body["addresses"][1]["street"] == WORK["street"]


def test_create_without_addresses_defaults_to_empty(client, payload):
    body = _create(client, payload, addresses=[])
    assert body["addresses"] == []


def test_create_rejects_unknown_address_type(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [{**HOME, "type": "vacation"}]})
    assert response.status_code == 422


def test_create_rejects_blank_address(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [{"type": "home"}]})
    assert response.status_code == 422


def test_create_rejects_too_many_addresses(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [HOME] * 11})
    assert response.status_code == 422


def test_get_returns_addresses_in_creation_order(client, payload):
    contact_id = _create(client, payload, addresses=[WORK, HOME])["id"]
    body = client.get(f"{BASE}/{contact_id}").json()
    assert [a["type"] for a in body["addresses"]] == ["work", "home"]


def test_list_embeds_addresses(client, payload):
    _create(client, payload, addresses=[HOME, WORK])
    body = client.get(BASE).json()
    assert len(body["items"][0]["addresses"]) == 2


def test_put_replaces_the_whole_address_set(client, payload):
    contact_id = _create(client, payload, addresses=[HOME, WORK])["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={**payload, "addresses": [{"type": "other", "city": "Portland"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["addresses"]) == 1
    assert body["addresses"][0]["type"] == "other"
    assert body["addresses"][0]["city"] == "Portland"


def test_patch_without_addresses_keeps_them(client, payload):
    contact_id = _create(client, payload, addresses=[HOME, WORK])["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    assert [a["type"] for a in response.json()["addresses"]] == ["home", "work"]


def test_patch_with_empty_addresses_clears_them(client, payload):
    contact_id = _create(client, payload, addresses=[HOME])["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"addresses": []})
    assert response.status_code == 200
    assert response.json()["addresses"] == []


def test_delete_contact_cascades_to_addresses(client, payload):
    contact_id = _create(client, payload, addresses=[HOME, WORK])["id"]
    address_ids = {a["id"] for a in client.get(f"{BASE}/{contact_id}").json()["addresses"]}

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204

    from app.database import SessionLocal
    from app.models import Address

    with SessionLocal() as db:
        remaining = {row.id for row in db.query(Address).all()}
    assert address_ids.isdisjoint(remaining)


def test_contacts_table_has_no_legacy_address_columns(client, payload):
    _create(client, payload)
    columns = {c["name"] for c in inspect(engine).get_columns("contacts")}
    assert columns.isdisjoint({"address", "city", "state", "postal_code", "country"})
