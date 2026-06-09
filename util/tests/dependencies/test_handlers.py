import json
import logging
from datetime import datetime
from unittest.mock import MagicMock, mock_open, patch

import pytest
import requests
from dateutil.parser import parse as datetime_parser

from pyfiles.dependencies.handlers import Handlers


def test_handlers_init():
    obj = Handlers()
    assert isinstance(obj, Handlers)

@pytest.fixture
def config():
    return {
        "azure.fhir": {
            "client_id": "abc",
            "client_secret": "secret123",
            "scope": "https://example/.default",
            "grant_type": "client_credentials",
            "token_url": "https://login.microsoftonline.com/token",
            "timeout_seconds": "60"
        }
    }

@pytest.fixture
def silver_layer_config():
    return {
        "silver_layer": {
            "username": "user1",
            "password": "pass123",
            "query_server": "server.example.com",
            "catalog": "default_catalog",
            "core_database": "core_db",
            "audit_database": "audit_db"
        }
    }

@pytest.fixture
def audit_db_connection():
    """
    Returns a mock object that simulates a database connection
    with a .connect() method that can be used as a context manager.
    """
    mock_connection_context = MagicMock()
    mock_connection_context.__enter__.return_value = MagicMock()  # This will act as the 'con'

    mock_audit_db_connection = MagicMock()
    mock_audit_db_connection.connect.return_value = mock_connection_context

    return mock_audit_db_connection

def test_get_azure_fhir_token_success(config):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "TOKEN123"}

    with patch("requests.post", return_value=mock_response) as mock_post:
        token = Handlers.get_azure_fhir_token(config)

        assert token == "TOKEN123"

        mock_post.assert_called_once_with(
            "https://login.microsoftonline.com/token",
            data={
                "client_id": "abc",
                "client_secret": "secret123",
                "scope": "https://example/.default",
                "grant_type": "client_credentials",
            },
            headers={"Accept": "*/*", "Connection": "keep-alive"},
            timeout=60
        )

def test_get_azure_fhir_token_non_200(config, caplog):
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"

    with patch("requests.post", return_value=mock_response):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(Exception) as exc:
                Handlers.get_azure_fhir_token(config)

            assert "Failed to get token" in str(exc.value)
            assert "status code: 400" in caplog.text

def test_get_azure_fhir_token_request_exception(config, caplog):
    with patch("requests.post", side_effect=Exception("Network failure")):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(Exception) as exc:
                Handlers.get_azure_fhir_token(config)

            assert "Network failure" in str(exc.value)
            assert "Error getting FHIR token" in caplog.text

def test_get_azure_fhir_token_missing_access_token(config):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}

    with patch("requests.post", return_value=mock_response):
        token = Handlers.get_azure_fhir_token(config)

        assert token is None

def test_azure_fhir_header_success(config):
    with patch.object(Handlers, "get_azure_fhir_token", return_value="TOKEN123") as mock_token:

        header = Handlers.azure_fhir_header(config)

        assert header == {
            "Accept": "application/fhir+json",
            "Prefer": "respond-async",
            "Authorization": "Bearer TOKEN123",
        }

        mock_token.assert_called_once_with(config)

def test_azure_fhir_header_empty_token(config):
    with patch.object(Handlers, "get_azure_fhir_token", return_value=""):

        header = Handlers.azure_fhir_header(config)

        assert header["Authorization"] == "Bearer "

def test_get_silver_layer_core_connection_parameters(silver_layer_config):
    expected = "user1:pass123@server.example.com/default_catalog.core_db"
    result = Handlers.get_silver_layer_core_connection_parameters(silver_layer_config)
    assert result == expected

def test_get_silver_layer_audit_connection_parameters(silver_layer_config):
    expected = "user1:pass123@server.example.com/default_catalog.audit_db"
    result = Handlers.get_silver_layer_audit_connection_parameters(silver_layer_config)
    assert result == expected

def test_get_database_connection_parameters_with_db(silver_layer_config):
    db_name = "custom_db"
    expected = "user1:pass123@server.example.com/default_catalog.custom_db"
    result = Handlers.get_database_connection_parameters(silver_layer_config, db_name)
    assert result == expected

def test_get_database_connection_parameters_no_db(silver_layer_config):
    expected = "user1:pass123@server.example.com"
    result = Handlers.get_database_connection_parameters(silver_layer_config, None)
    assert result == expected

def test_get_database_connection_parameters_empty_db(silver_layer_config):
    expected = "user1:pass123@server.example.com"
    result = Handlers.get_database_connection_parameters(silver_layer_config, "")
    assert result == expected

def test_get_last_export_time_existing(audit_db_connection):
    expected_db_time = datetime(2025, 1, 1, 12, 30)

    # Mock the result of SQL execution
    mock_result = MagicMock()
    mock_result.fetchone.return_value = [expected_db_time]

    # con.execute(...) should return the mock result
    con_mock = audit_db_connection.connect().__enter__.return_value
    con_mock.execute.return_value = mock_result

    result = Handlers.get_last_export_time(audit_db_connection, "2025-01-01T00:00:00", "Patient")
    assert result == expected_db_time

    args, _ = con_mock.execute.call_args
    executed_sql = "SELECT MAX(till_date_time) FROM dollar_export_logger where resource_type = 'Patient'"
    assert args[0].text == executed_sql

def test_get_last_export_time_first_run(audit_db_connection, caplog):
    start_date_str = "2025-01-01T00:00:00"
    expected_date = datetime_parser(start_date_str)

    mock_result = MagicMock()
    mock_result.fetchone.return_value = [None]

    con_mock = audit_db_connection.connect().__enter__.return_value
    con_mock.execute.return_value = mock_result

    with caplog.at_level(logging.INFO):
        result = Handlers.get_last_export_time(audit_db_connection, start_date_str, "Observation")
        assert result == expected_date
        assert "SYNC PROCESS INVOKED FOR THE FIRST TIME" in caplog.text

    args, _ = con_mock.execute.call_args
    executed_sql = "SELECT MAX(till_date_time) FROM dollar_export_logger where resource_type = 'Observation'"
    assert args[0].text == executed_sql


def test_get_last_export_time_invalid_start_date(audit_db_connection):
    invalid_start_date = "invalid-date"

    mock_result = MagicMock()
    mock_result.fetchone.return_value = [None]

    con_mock = audit_db_connection.connect().__enter__.return_value
    con_mock.execute.return_value = mock_result

    with pytest.raises(Exception):
        Handlers.get_last_export_time(audit_db_connection, invalid_start_date, "Patient")

def test_json_reader_success():
    fake_json_content = '{"resourceType": "Patient", "id": "123"}'
    file_name = "fake_schema.json"

    m = mock_open(read_data=fake_json_content)

    with patch("builtins.open", m):
        result = Handlers.json_reader(file_name)

    expected = {"resourceType": "Patient", "id": "123"}
    assert result == expected

def test_json_reader_file_not_found(caplog):
    file_name = "non_existent_file.json"

    with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
        with caplog.at_level(logging.ERROR):
            result = Handlers.json_reader(file_name)
            assert result is None
            # Check that error was logged
            assert "Failed to read json file" in caplog.text
            assert "File not found" in caplog.text

def test_json_reader_invalid_json(caplog):
    invalid_json_content = "{invalid_json: true}"
    file_name = "invalid_schema.json"

    m = mock_open(read_data=invalid_json_content)

    with patch("builtins.open", m):
        with caplog.at_level(logging.ERROR):
            result = Handlers.json_reader(file_name)
            assert result is None
            assert "Failed to read json file" in caplog.text
            assert "Expecting property name enclosed in double quotes" in caplog.text


def test_get_database_parameters_success():
    configurations = {
        "silver_layer": {
            "database": "test_db",
            "username": "user1",
            "password": "pass123",
            "query_server": "localhost",
            "port": 9030
        }
    }

    result = Handlers.get_database_parameters(configurations)

    assert result == {
        "database": "test_db",
        "user": "user1",
        "password": "pass123",
        "host": "localhost",
        "port": 9030,
    }


def test_get_database_parameters_missing_key():
    configurations = {
        "silver_layer": {
            "username": "user1",
            "password": "pass123",
            "query_server": "localhost",
            "port": 9030
        }
    }

    with pytest.raises(KeyError):
        Handlers.get_database_parameters(configurations)

def test_get_resource_fhir_url_success():
    fhir_event = {"subject": "example.fhir.server.com"}

    result = Handlers.get_resource_fhir_url(fhir_event)
    assert result == "https://example.fhir.server.com"

def test_get_configuration_file_success():
    fake_json = {"name": "Patient", "type": "resource"}

    m = mock_open(read_data=json.dumps(fake_json))

    with patch("builtins.open", m):
        result = Handlers.get_configuration_file("Patient")

    assert result == fake_json


def test_get_configuration_file_not_found():
    with patch("builtins.open", side_effect=FileNotFoundError):
        with pytest.raises(FileNotFoundError):
            Handlers.get_configuration_file("MissingResource")


def test_get_configuration_file_invalid_json():
    m = mock_open(read_data="{ invalid json }")

    with patch("builtins.open", m):
        with pytest.raises(json.JSONDecodeError):
            Handlers.get_configuration_file("BrokenFile")


def test_fhir_connectivity_check_azure_success(caplog):
    config = {
        "initialization": {"deployment_type": "azure", "fhir_service": "azure"},
        "azure.fhir": {
            "server_url": "https://azure.fhir.com",
            "timeout_seconds": "10"
        }
    }

    mock_header = {"Authorization": "Bearer token123"}
    mock_response = MagicMock()
    mock_response.status_code = 200

    with (
        patch.object(Handlers, "azure_fhir_header", return_value=mock_header),
        patch("requests.get", return_value=mock_response),
        caplog.at_level(logging.INFO)
    ):
        result = Handlers.fhir_connectivity_check(config)

        assert result == "Success"
        assert "FHIR Server connection successful" in caplog.text

        # ensure correct request call
        requests.get.assert_called_once_with(
            "https://azure.fhir.com",
            headers=mock_header,
            timeout=10
        )


def test_fhir_connectivity_check_azure_failure(caplog):
    config = {
        "initialization": {"deployment_type": "azure", "fhir_service": "azure"},
        "azure.fhir": {
            "server_url": "https://azure.fhir.com",
            "timeout_seconds": "10"
        }
    }

    mock_header = {"Authorization": "Bearer token123"}
    mock_response = MagicMock()
    mock_response.status_code = 500

    with (
        patch.object(Handlers, "azure_fhir_header", return_value=mock_header),
        patch("requests.get", return_value=mock_response),
        caplog.at_level(logging.ERROR)
    ):
        with pytest.raises(SystemExit):
            Handlers.fhir_connectivity_check(config)

        assert "FHIR Server connection unsuccessful" in caplog.text
        assert "500" in caplog.text


def test_fhir_connectivity_check_azure_exception(caplog):
    config = {
        "initialization": {"deployment_type": "azure", "fhir_service": "azure"},
        "azure.fhir": {
            "server_url": "https://azure.fhir.com",
            "timeout_seconds": "10"
        }
    }

    with (
        patch.object(Handlers, "azure_fhir_header", side_effect=Exception("Header error")),
        caplog.at_level(logging.ERROR)
    ):
        with pytest.raises(SystemExit):
            Handlers.fhir_connectivity_check(config)

        assert "FHIR Server connection unsuccessful: Header error" in caplog.text

def test_fhir_connectivity_check_unsupported_exits(caplog):
    config = {
        "initialization": {"deployment_type": "something", "fhir_service": "aws"},
    }

    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit):
            Handlers.fhir_connectivity_check(config)

        assert "Unsupported fhir_service" in caplog.text


def test_local_fhir_connectivity_check_success(caplog):
    config = {
        "local.fhir": {
            "server_url": "http://localhost:8080/fhir",
            "timeout_seconds": "5"
        }
    }

    mock_response = MagicMock()
    mock_response.status_code = 200

    with (
        patch("requests.get", return_value=mock_response),
        caplog.at_level(logging.INFO)
    ):
        Handlers.local_fhir_connectivity_check(config)

        assert "HAPI FHIR Server connection successful" in caplog.text
        requests.get.assert_called_once_with(
            "http://localhost:8080/fhir/metadata",
            headers={"Accept": "application/fhir+json"},
            timeout=5
        )


def test_local_fhir_connectivity_check_non_200(caplog):
    config = {
        "local.fhir": {
            "server_url": "http://localhost:8080/fhir",
            "timeout_seconds": "5"
        }
    }

    mock_response = MagicMock()
    mock_response.status_code = 503

    with (
        patch("requests.get", return_value=mock_response),
        caplog.at_level(logging.ERROR)
    ):
        with pytest.raises(SystemExit):
            Handlers.local_fhir_connectivity_check(config)

        assert "HAPI FHIR Server connection failed with status: 503" in caplog.text


def test_local_fhir_connectivity_check_exception(caplog):
    config = {
        "local.fhir": {
            "server_url": "http://localhost:8080/fhir",
            "timeout_seconds": "5"
        }
    }

    with (
        patch("requests.get", side_effect=Exception("Connection refused")),
        caplog.at_level(logging.ERROR)
    ):
        with pytest.raises(SystemExit):
            Handlers.local_fhir_connectivity_check(config)

        assert "HAPI FHIR connectivity check failed" in caplog.text
        assert "Connection refused" in caplog.text


def test_fhir_connectivity_check_local_routes_to_hapi(caplog):
    config = {
        "initialization": {"deployment_type": "local"},
        "local.fhir": {
            "server_url": "http://localhost:8080/fhir",
            "timeout_seconds": "5"
        }
    }

    with patch.object(Handlers, "local_fhir_connectivity_check") as mock_local:
        Handlers.fhir_connectivity_check(config)
        mock_local.assert_called_once_with(config)
