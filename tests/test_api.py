from tests.conftest import enquiry


def test_full_flow_over_http(client):
    created = client.post("/leads", json=enquiry()).json()
    assert created["status"] == "pending_approval"
    assert created["qualification"] == "hot"
    assert "#lead " in created["approval_message"]

    # the email node must not be able to run before a person decides
    assert client.post(f"/leads/{created['id']}/sent").status_code == 409

    decision = client.post(
        f"/leads/{created['id']}/decision", json={"action": "approve", "by": "owner"}
    ).json()
    assert decision["send"] is True
    assert decision["reply_to"] == "tom.hughes@example.com"
    assert decision["reply_text"] == created["draft_text"]

    sent = client.post(f"/leads/{created['id']}/sent").json()
    assert sent["status"] == "sent"
    assert (
        client.post(f"/leads/{created['id']}/decision", json={"action": "reject"}).status_code
        == 409
    )


def test_webhook_envelope_is_unwrapped(client):
    envelope = {"headers": {"host": "x"}, "params": {}, "query": {}, "body": enquiry()}
    created = client.post("/leads", json=envelope).json()
    assert created["email"] == "tom.hughes@example.com"


def test_reject_does_not_send(client):
    created = client.post("/leads", json=enquiry()).json()
    decision = client.post(f"/leads/{created['id']}/decision", json={"action": "reject"}).json()
    assert decision["send"] is False and decision["reply_text"] == ""
    assert client.post(f"/leads/{created['id']}/sent").status_code == 409


def test_failed_and_incidents_and_report(client):
    created = client.post("/leads", json=enquiry()).json()
    assert (
        client.post(f"/leads/{created['id']}/failed", json={"error": "SMTP down"}).json()["status"]
        == "failed"
    )
    inc = client.post(
        "/incidents",
        json={
            "workflow": "lead-intake",
            "node": "Send reply",
            "message": "SMTP down",
            "lead_id": created["id"],
        },
    )
    assert inc.status_code == 201
    report = client.get("/report").json()
    assert (
        report["leads"] == 1 and report["incidents"] == 1 and report["by_status"] == {"failed": 1}
    )


def test_bearer_token_when_configured(client, monkeypatch):
    from leadintake.config import get_settings

    monkeypatch.setenv("API_TOKEN", "s3cret-token-value")
    get_settings.cache_clear()
    assert client.post("/leads", json=enquiry()).status_code == 401
    assert (
        client.post(
            "/leads", json=enquiry(), headers={"Authorization": "Bearer s3cret-token-value"}
        ).status_code
        == 201
    )
    assert client.get("/healthz").status_code == 200


def test_unknown_lead_is_404(client):
    assert client.get("/leads/lead_nope").status_code == 404
    assert client.post("/leads/lead_nope/decision", json={"action": "approve"}).status_code == 404
