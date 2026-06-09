"""Unit tests for HapiFhirClient (local-mode FHIR adapter)."""
import pytest


def make_config(server_url="http://hapi-fhir:8080/fhir", ndjson_size="1000"):
    return {
        "local.fhir": {"server_url": server_url},
        "FHIR": {"ndjson_file_size": ndjson_size},
    }


class TestHapiFhirClientUrlBuilding:
    def test_get_fhir_batch_export_url_includes_resource_and_dates(self):
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        client = HapiFhirClient(make_config())
        url = client.get_fhir_batch_export_url(
            "Patient", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"
        )
        assert "/Patient" in url
        assert "_lastUpdated=ge2026-01-01T00:00:00Z" in url
        assert "_lastUpdated=le2026-02-01T00:00:00Z" in url
        assert "_count=1000" in url

    def test_get_fhir_batch_export_url_uses_local_fhir_server_url(self):
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        client = HapiFhirClient(make_config(server_url="http://example.com/fhir"))
        url = client.get_fhir_batch_export_url("Observation", "2026-01-01", "2026-01-02")
        assert url.startswith("http://example.com/fhir/Observation?")


class TestHapiFhirConnectivityCheck:
    def test_returns_true_on_200(self, monkeypatch):
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        client = HapiFhirClient(make_config())

        class FakeResp:
            status_code = 200
            def json(self):
                return {"resourceType": "CapabilityStatement"}

        def fake_get(url, headers=None, timeout=None):
            assert url.endswith("/metadata")
            return FakeResp()

        monkeypatch.setattr(client.session, "get", fake_get)
        assert client.fhir_connectivity_check() is True

    def test_raises_prerequisite_error_on_non_200(self, monkeypatch):
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        from pyfiles.dependencies.data_processing_error import PrerequisiteError
        client = HapiFhirClient(make_config())

        class FakeResp:
            status_code = 503
            def json(self):
                return {"error": "down"}

        monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResp())
        with pytest.raises(PrerequisiteError):
            client.fhir_connectivity_check()


class TestHapiFhirIterResources:
    def test_unwraps_entries_and_follows_pagination(self, monkeypatch):
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        client = HapiFhirClient(make_config())

        page1 = {
            "resourceType": "Bundle",
            "entry": [
                {"resource": {"resourceType": "Patient", "id": "1"}},
                {"resource": {"resourceType": "Patient", "id": "2"}},
            ],
            "link": [{"relation": "next", "url": "http://hapi-fhir:8080/fhir/Patient?page=2"}],
        }
        page2 = {
            "resourceType": "Bundle",
            "entry": [{"resource": {"resourceType": "Patient", "id": "3"}}],
            "link": [{"relation": "self", "url": "http://hapi-fhir:8080/fhir/Patient?page=2"}],
        }

        pages = iter([page1, page2])

        class FakeResp:
            def __init__(self, body):
                self.body = body
                self.status_code = 200
            def raise_for_status(self):
                return None
            def json(self):
                return self.body

        def fake_get(url, headers=None, timeout=None):
            return FakeResp(next(pages))

        monkeypatch.setattr(client.session, "get", fake_get)
        resources = list(client.iter_resources("Patient", "2026-01-01", "2026-02-01"))
        assert [r["id"] for r in resources] == ["1", "2", "3"]
        assert all(r["resourceType"] == "Patient" for r in resources)

    def test_handles_missing_entry_field(self, monkeypatch):
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        client = HapiFhirClient(make_config())

        class FakeResp:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self):
                return {"resourceType": "Bundle"}  # no entry, no link

        monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResp())
        assert list(client.iter_resources("Patient", "2026-01-01", "2026-02-01")) == []

    def test_propagates_http_errors(self, monkeypatch):
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        import requests as _requests
        client = HapiFhirClient(make_config())

        class FakeResp:
            status_code = 500
            def raise_for_status(self):
                raise _requests.HTTPError("500 Server Error")
            def json(self):
                return {}

        monkeypatch.setattr(client.session, "get", lambda *a, **k: FakeResp())
        with pytest.raises(_requests.HTTPError):
            list(client.iter_resources("Patient", "2026-01-01", "2026-02-01"))
