import os

from react_agent.eval.connectors import (
    ConnectorConfig,
    GitLabAdapter,
    JiraAdapter,
    ServiceNowAdapter,
    TraceAdapter,
    ZendeskAdapter,
    ReadOnlyHttpClient,
    load_env_file,
)


def _client(payload, headers=None):
    def transport(url, request_headers):
        assert "Authorization" not in request_headers
        return payload, headers or {}

    return ReadOnlyHttpClient(ConnectorConfig("https://example.test", "secret"), transport)


def test_jira_normalizes_issue_and_preserves_unresolved_boundary():
    client = _client({"issues": [{"key": "OPS-1", "fields": {"summary": "401", "status": {"statusCategory": {"key": "indeterminate"}}}}], "total": 1})
    task = JiraAdapter(client).fetch()[0]
    assert task["task_id"] == "OPS-1"
    assert task["domain"] == "software_delivery"
    assert task["final_status"] == "needs_review"
    assert client.audit[0]["method"] == "GET"
    assert "secret" not in client.audit[0]["url"]


def test_gitlab_uses_next_page_header():
    calls = []

    def transport(url, headers):
        calls.append(url)
        if "page=1" in url:
            return [{"iid": 1, "title": "one", "state": "opened", "web_url": "u1"}], {"X-Next-Page": "2"}
        return [{"iid": 2, "title": "two", "state": "closed", "web_url": "u2"}], {}

    adapter = GitLabAdapter(ReadOnlyHttpClient(ConnectorConfig("https://gitlab.test", "x"), transport), "42")
    tasks = adapter.fetch()
    assert len(tasks) == 2
    assert tasks[1]["final_status"] == "resolved"
    assert len(calls) == 2


def test_zendesk_and_servicenow_map_closed_states():
    zendesk = ZendeskAdapter(_client({"tickets": [{"id": 7, "subject": "outage", "status": "solved"}]})).fetch()[0]
    servicenow = ServiceNowAdapter(_client({"result": [{"number": "INC7", "short_description": "outage", "state": "6"}]})).fetch()[0]
    assert zendesk["final_status"] == "resolved"
    assert servicenow["final_status"] == "resolved"


def test_trace_adapter_keeps_trace_as_source_reference():
    adapter = TraceAdapter(_client({"trace_id": "abc", "error": "timeout"}), "/traces", trace_ids=["abc"])
    task = adapter.fetch()[0]
    assert task["task_id"] == "abc"
    assert task["evidence"]["source_ref"] == "trace://abc"


def test_connector_config_reads_only_prefixed_environment(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.test/")
    monkeypatch.setenv("JIRA_READONLY_TOKEN", "token")
    config = ConnectorConfig.from_env("JIRA")
    assert config.base_url == "https://jira.test"
    assert config.token == "token"


def test_load_env_file_does_not_override_process_secret(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CONNECTOR_URL=https://file.test\nCONNECTOR_TOKEN=from-file\n", encoding="utf-8")
    monkeypatch.setenv("CONNECTOR_TOKEN", "from-process")
    assert load_env_file(env_file) == 1
    assert os.environ["CONNECTOR_URL"] == "https://file.test"
    assert os.environ["CONNECTOR_TOKEN"] == "from-process"
