import configparser
from unittest.mock import patch

import pytest

from pyfiles.dependencies.prerequisites import Prerequisites
from pyfiles.dependencies.utilityexception import UtilityException


def test_configurations_calls_substitute_env_variables():
    with patch.object(Prerequisites, 'substitute_env_variables') as mock_substitute:
        mock_substitute.return_value = "config"

        result = Prerequisites.configurations()

        mock_substitute.assert_called_once()
        assert result == "config"


@patch("configparser.ConfigParser.read")
@patch("os.getenv")
def test_substitute_env_variables_replaces_env_vars(mock_getenv, mock_read):
    mock_getenv.return_value = "resolved_value"

    config = configparser.ConfigParser()
    config.read_dict({
        "initialization": {
            "fhir_service": "${FHIR_SERVICE}"
        }
    })

    with patch("configparser.ConfigParser", return_value=config):
        result = Prerequisites.substitute_env_variables()

    assert result["initialization"]["fhir_service"] == "resolved_value"

def test_substitute_env_variables_keeps_plain_values():
    config = configparser.ConfigParser()
    config.read_dict({
        "section1": {
            "key1": "plain_value"
        }
    })

    with patch("configparser.ConfigParser", return_value=config):
        result = Prerequisites.substitute_env_variables()

    assert result["section1"]["key1"] == "plain_value"


def test_substitute_env_variables_multiple_sections():

    config = configparser.ConfigParser()
    config.read_dict({
        "section1": {"key1": "value1"},
        "section2": {"key2": "value2"}
    })

    with patch("configparser.ConfigParser", return_value=config):
        result = Prerequisites.substitute_env_variables()

    assert result["section1"]["key1"] == "value1"
    assert result["section2"]["key2"] == "value2"

import configparser
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.prerequisites import Prerequisites


@patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO")
@patch("pyfiles.dependencies.prerequisites.DBConnectionPool")
@patch("pyfiles.dependencies.prerequisites.Handlers.fhir_connectivity_check")
@patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration")
@patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations")
def test_prerequisite_check_success(
    mock_configurations,
    mock_logging_config,
    mock_fhir_check,
    mock_db_pool,
    mock_getenv,
):
    # Arrange
    fake_config = configparser.ConfigParser()
    mock_configurations.return_value = fake_config

    core_db = MagicMock()
    audit_db = MagicMock()

    mock_db_instance = MagicMock()
    mock_db_instance.initialize.side_effect = [core_db, audit_db]
    mock_db_pool.return_value = mock_db_instance

    # Act
    result_config, core_conn, audit_conn = Prerequisites.prerequisite_check(
        core_connections=True
    )

    # Assert
    assert result_config == fake_config
    assert core_conn == core_db
    assert audit_conn == audit_db

    mock_logging_config.assert_called_once()
    mock_fhir_check.assert_called_once_with(fake_config)
    assert mock_db_instance.initialize.call_count == 2

@patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO")
@patch("pyfiles.dependencies.prerequisites.Handlers.fhir_connectivity_check")
@patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration")
@patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations")
def test_prerequisite_check_no_core_connections(
    mock_configurations,
    mock_logging_config,
    mock_fhir_check,
    mock_getenv,
):
    fake_config = configparser.ConfigParser()
    mock_configurations.return_value = fake_config

    result_config, core_conn, audit_conn = Prerequisites.prerequisite_check(
        core_connections=False
    )

    assert result_config == fake_config
    assert core_conn is None
    assert audit_conn is None

@patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO")
@patch("pyfiles.dependencies.prerequisites.DBConnectionPool")
@patch("pyfiles.dependencies.prerequisites.Handlers.fhir_connectivity_check")
@patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration")
@patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations")
def test_prerequisite_check_db_failure(
    mock_configurations,
    mock_logging_config,
    mock_fhir_check,
    mock_db_pool,
    mock_getenv,
):
    mock_configurations.return_value = configparser.ConfigParser()

    mock_db_instance = MagicMock()
    mock_db_instance.initialize.side_effect = Exception("db error")
    mock_db_pool.return_value = mock_db_instance

    with pytest.raises(UtilityException) as exc:
        Prerequisites.prerequisite_check(core_connections=True)

    assert "Database connectivity check failed" in str(exc.value)

@patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO")
@patch("pyfiles.dependencies.prerequisites.Handlers.fhir_connectivity_check", side_effect=Exception)
@patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration")
@patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations")
def test_prerequisite_check_fhir_failure(
    mock_configurations,
    mock_logging_config,
    mock_fhir_check,
    mock_getenv,
):
    mock_configurations.return_value = configparser.ConfigParser()

    with pytest.raises(UtilityException) as exc:
        Prerequisites.prerequisite_check(core_connections=True)

    assert "FHIR Server connectivity check failed" in str(exc.value)

@patch(
    "pyfiles.dependencies.prerequisites.Prerequisites.configurations",
    side_effect=Exception("config error"),
)
def test_prerequisite_check_config_failure(mock_config):
    with pytest.raises(UtilityException) as exc:
        Prerequisites.prerequisite_check(core_connections=True)

    assert "Environment Variables Initialization Failed" in str(exc.value)
