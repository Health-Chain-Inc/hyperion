from unittest.mock import MagicMock, patch

import pytest

from pyfiles.db_handler.fhir_server_handler import FhirServerHandler
from pyfiles.dependencies.utilityexception import UtilityException


@pytest.fixture
def azure_config():
    return {
        "initialization": {"deployment_type": "azure", "fhir_service": "azure"},
        "azure.fhir": {
            "server_url": "https://azure-fhir",
            "timeout_seconds": "30"
        },
    }


@pytest.fixture
def local_config():
    return {
        "initialization": {"deployment_type": "local"},
        "local.fhir": {
            "server_url": "http://localhost:8080/fhir",
            "timeout_seconds": "5"
        }
    }


def test_init_sets_azure_fhir_url(azure_config):
    handler = FhirServerHandler(azure_config)
    assert handler.fhir_url == "https://azure-fhir"


def test_init_sets_local_fhir_url(local_config):
    handler = FhirServerHandler(local_config)
    assert handler.fhir_url == "http://localhost:8080/fhir"


def test_init_unsupported_fhir_service_raises():
    config = {
        "initialization": {"deployment_type": "azure", "fhir_service": "aws"},
    }
    with pytest.raises(UtilityException):
        FhirServerHandler(config)


@patch("pyfiles.db_handler.fhir_server_handler.requests.get")
@patch("pyfiles.db_handler.fhir_server_handler.Handlers.azure_fhir_header")
def test_get_meta_data_azure_success(mock_header, mock_get, azure_config):
    mock_header.return_value = {"Authorization": "token"}
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"meta": "data"}
    mock_get.return_value = mock_response

    handler = FhirServerHandler(azure_config)
    result = handler.get_meta_data()

    assert result == {"meta": "data"}


@patch("pyfiles.db_handler.fhir_server_handler.requests.get")
def test_get_meta_data_local_success(mock_get, local_config):
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"resourceType": "CapabilityStatement"}
    mock_get.return_value = mock_response

    handler = FhirServerHandler(local_config)
    result = handler.get_meta_data()

    assert result == {"resourceType": "CapabilityStatement"}
    mock_get.assert_called_once_with(
        "http://localhost:8080/fhir/metadata",
        headers={"Accept": "application/fhir+json"},
        timeout=5
    )

def test_get_resource_list_with_resources(azure_config):
    handler = FhirServerHandler(azure_config)
    handler.get_meta_data = MagicMock(return_value={
        "rest": [{
            "resource": [
                {"type": "Patient"},
                {"type": "Observation"}
            ]
        }]
    })

    result = handler.get_resource_list()
    assert result == ["Patient", "Observation"]


def test_get_resource_list_empty_metadata(azure_config):
    handler = FhirServerHandler(azure_config)
    handler.get_meta_data = MagicMock(return_value={})

    result = handler.get_resource_list()
    assert result == []

@patch("pyfiles.db_handler.fhir_server_handler.requests.get")
@patch("pyfiles.db_handler.fhir_server_handler.Handlers.azure_fhir_header")
def test_dollar_exporter_azure_accepted(mock_header, mock_get, azure_config):
    mock_header.return_value = {}
    mock_response = MagicMock(status_code=202, headers={"Content-Location": "status_url"})
    mock_get.return_value = mock_response

    handler = FhirServerHandler(azure_config)
    location, status = handler.dollar_exporter({"_type": "Patient"})

    assert location == "status_url"
    assert status == "in-progress"

@patch("pyfiles.db_handler.fhir_server_handler.requests.get")
@patch("pyfiles.db_handler.fhir_server_handler.Handlers.azure_fhir_header")
def test_dollar_exporter_azure_failure(mock_header, mock_get, azure_config):
    mock_header.return_value = {}
    mock_response = MagicMock(status_code=200, headers={"Content-Location": "status_url"})
    mock_get.return_value = mock_response

    handler = FhirServerHandler(azure_config)
    location, status = handler.dollar_exporter({"_type": "Patient"})

    assert status == "error"
    assert location == "Dollar export invocation failed."

@patch("pyfiles.db_handler.fhir_server_handler.requests.get", side_effect=Exception("boom"))
def test_dollar_exporter_exception(mock_get, azure_config):
    handler = FhirServerHandler(azure_config)
    with pytest.raises(UtilityException):
        handler.dollar_exporter({"_type": "Patient"})

@patch("pyfiles.db_handler.fhir_server_handler.execute_sql_statement")
@patch("pyfiles.db_handler.fhir_server_handler.insert_dollar_export_logger")
@patch.object(FhirServerHandler, "dollar_exporter")
def test_dollar_export_invoker_success(
    mock_exporter,
    mock_insert_logger,
    mock_execute_sql,
    azure_config
):
    mock_exporter.return_value = ("status_url", "in-progress")
    mock_insert_logger.return_value = ("QUERY", {"param": 1})

    handler = FhirServerHandler(azure_config)

    handler.dollar_export_invoker(
        audit_db_connection="db",
        dollar_export_resources=["Patient"],
        start_date="2024-01-01 00:00:00",
        end_date="2024-01-05 00:00:00",
        interval=2
    )

    assert mock_exporter.called
    assert mock_execute_sql.called


@patch.object(FhirServerHandler, "dollar_exporter", side_effect=Exception("fail"))
def test_dollar_export_invoker_exception(mock_exporter, azure_config):
    handler = FhirServerHandler(azure_config)

    with pytest.raises(UtilityException):
        handler.dollar_export_invoker(
            audit_db_connection="db",
            dollar_export_resources=["Patient"],
            start_date="2024-01-01 00:00:00",
            end_date="2024-01-05 00:00:00",
            interval=2
        )

@patch("pyfiles.db_handler.fhir_server_handler.requests.get")
@patch("pyfiles.db_handler.fhir_server_handler.Handlers.azure_fhir_header")
def test_dollar_exporter_status_in_progress(mock_header, mock_get, azure_config):
    mock_header.return_value = {}
    mock_get.return_value = MagicMock(status_code=202)

    handler = FhirServerHandler(azure_config)
    result = handler.dollar_exporter_status("status_url")

    assert result == "in-progress"


@patch("pyfiles.db_handler.fhir_server_handler.requests.get")
@patch("pyfiles.db_handler.fhir_server_handler.Handlers.azure_fhir_header")
def test_dollar_exporter_status_complete(mock_header, mock_get, azure_config):
    mock_header.return_value = {}
    mock_get.return_value = MagicMock(status_code=200)

    handler = FhirServerHandler(azure_config)
    result = handler.dollar_exporter_status("status_url")

    assert result == "complete"


@patch("pyfiles.db_handler.fhir_server_handler.requests.get", side_effect=Exception("boom"))
def test_dollar_exporter_status_exception(mock_get, azure_config):
    handler = FhirServerHandler(azure_config)
    with pytest.raises(UtilityException):
        handler.dollar_exporter_status("status_url")
