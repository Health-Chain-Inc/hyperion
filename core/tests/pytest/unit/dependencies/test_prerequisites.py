"""Unit tests for Prerequisites class."""
import configparser
import pytest
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.enum import ApplicationEnums, HyperionDBConnectionEnums
from pyfiles.dependencies.prerequisites import Prerequisites


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(app_name, fhir_service="azure", cloud_storage="azure", servicebus="azure"):
    """Build a mock configparser.ConfigParser-like object."""
    cfg = configparser.ConfigParser()
    cfg["application"] = {"name": app_name}
    cfg["initialization"] = {
        "cloud_storage": cloud_storage,
        "fhir_service": fhir_service,
        "servicebus": servicebus,
    }
    cfg["pools"] = {"database": "5"}
    cfg["schema"] = {"fhir_file_name": "fhir.schema.json"}
    return cfg


# ---------------------------------------------------------------------------
# Tests for substitute_env_variables
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSubstituteEnvVariables:
    """Test Prerequisites.substitute_env_variables static method."""

    def test_replaces_dollar_brace_syntax_with_env_value(self):
        """${VAR} placeholders are replaced with the env variable value."""
        section_data = {"key": "${MY_TEST_VAR}"}

        with patch("pyfiles.dependencies.prerequisites.configparser.ConfigParser") as mock_cp_class, \
             patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="hello") as mock_getenv:

            mock_cp = MagicMock()
            mock_cp.sections.return_value = ["section"]
            mock_cp.__getitem__.return_value = section_data
            mock_cp_class.return_value = mock_cp

            Prerequisites.substitute_env_variables()

            # getenv should have been called with the variable name and "" default
            # (was None; changed because configparser rejects None values on Python 3.13+)
            mock_getenv.assert_called_with("MY_TEST_VAR", "")
            # The value should have been replaced in-place
            assert section_data["key"] == "hello"

    def test_leaves_literal_values_unchanged(self):
        """Values that are not ${…} are passed through untouched."""
        fake_config = configparser.ConfigParser()
        fake_config["section"] = {"key": "literal_value"}

        with patch("pyfiles.dependencies.prerequisites.configparser.ConfigParser") as mock_cp_class, \
             patch("pyfiles.dependencies.prerequisites.os.getenv") as mock_getenv:

            mock_cp = MagicMock()
            mock_cp.sections.return_value = ["section"]
            # Value does not start with "${" — getenv should NOT be called
            mock_cp.__getitem__.return_value = {"key": "literal_value"}
            mock_cp_class.return_value = mock_cp

            Prerequisites.substitute_env_variables()

            mock_getenv.assert_not_called()

    def test_uses_empty_string_for_missing_env_variable(self):
        """When the env variable is absent, getenv returns "" (default).

        Default changed from None -> "" because configparser on Python 3.13+
        rejects None values with TypeError("option values must be strings").
        """
        with patch("pyfiles.dependencies.prerequisites.configparser.ConfigParser") as mock_cp_class, \
             patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="") as mock_getenv:

            mock_cp = MagicMock()
            mock_cp.sections.return_value = ["section"]
            mock_cp.__getitem__.return_value = {"key": "${MISSING_VAR}"}
            mock_cp_class.return_value = mock_cp

            Prerequisites.substitute_env_variables()

            mock_getenv.assert_called_with("MISSING_VAR", "")


# ---------------------------------------------------------------------------
# Tests for configurations
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConfigurations:
    """Test Prerequisites.configurations static method."""

    def test_configurations_delegates_to_substitute_env_variables(self):
        """configurations() is a thin wrapper around substitute_env_variables()."""
        mock_config = MagicMock()
        with patch.object(Prerequisites, "substitute_env_variables", return_value=mock_config) as mock_sub:
            result = Prerequisites.configurations()
            mock_sub.assert_called_once()
            assert result is mock_config


# ---------------------------------------------------------------------------
# Tests for prerequisite_check
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPrerequisiteCheckEarlyExit:
    """Test early-exit paths in prerequisite_check."""

    @patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration")
    @patch("pyfiles.dependencies.prerequisites.os.getenv")
    def test_early_exit_for_admin_grant_manager(self, mock_getenv, mock_log):
        """APPLICATION_NAME == admin-grant-manager returns 6-tuple of None."""
        mock_getenv.side_effect = lambda key, *args: (
            ApplicationEnums.ADMIN_GRANT_MANAGER.value if key == "APPLICATION_NAME" else None
        )

        result = Prerequisites.prerequisite_check()

        assert result == (None, None, None, None, None, None)

    @patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration")
    @patch("pyfiles.dependencies.prerequisites.os.getenv")
    def test_early_exit_for_root_password_manager(self, mock_getenv, mock_log):
        """APPLICATION_NAME == root-password-manager returns 6-tuple of None."""
        mock_getenv.side_effect = lambda key, *args: (
            ApplicationEnums.ROOT_PASSWORD_MANAGER.value if key == "APPLICATION_NAME" else None
        )

        result = Prerequisites.prerequisite_check()

        assert result == (None, None, None, None, None, None)


@pytest.mark.unit
class TestPrerequisiteCheckDBPools:
    """Test DB pool creation logic in prerequisite_check."""

    def _run_with_app(self, app_name, fhir_service="azure"):
        """Helper: run prerequisite_check patching all side-effecting deps."""
        cfg = _make_config(app_name, fhir_service=fhir_service)

        with patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration"), \
             patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO"), \
             patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations", return_value=cfg), \
             patch("pyfiles.dependencies.prerequisites.DBConnectionPool") as mock_pool_cls, \
             patch("pyfiles.dependencies.prerequisites.AzureFHIRClient") as mock_azure_fhir:

            mock_azure_fhir.return_value.fhir_connectivity_check.return_value = None
            mock_pool_cls.return_value = MagicMock()

            result = Prerequisites.prerequisite_check()
            return result, mock_pool_cls

    def test_creates_core_db_pool_for_core_data_ingester(self):
        """CORE_DATA_INGESTER triggers DBConnectionPool with CORE_DB_CONNECTION."""
        result, mock_pool_cls = self._run_with_app(ApplicationEnums.CORE_DATA_INGESTER.value)

        mock_pool_cls.assert_called_once()
        args = mock_pool_cls.call_args[0]
        assert args[1] == HyperionDBConnectionEnums.CORE_DB_CONNECTION.value

    def test_creates_audit_db_pool_for_scheduler(self):
        """SCHEDULER triggers DBConnectionPool with AUDIT_DB_CONNECTION."""
        result, mock_pool_cls = self._run_with_app(ApplicationEnums.SCHEDULER.value)

        mock_pool_cls.assert_called_once()
        args = mock_pool_cls.call_args[0]
        assert args[1] == HyperionDBConnectionEnums.AUDIT_DB_CONNECTION.value


    def test_no_db_pool_for_event_load_exporter(self):
        """EVENT_LOAD_EXPORTER does not create any DBConnectionPool."""
        result, mock_pool_cls = self._run_with_app(ApplicationEnums.EVENT_LOAD_EXPORTER.value)

        mock_pool_cls.assert_not_called()


@pytest.mark.unit
class TestPrerequisiteCheckFHIRConnectivity:
    """Test FHIR connectivity check in prerequisite_check."""

    def _run_for_fhir(self, fhir_service):
        cfg = _make_config(ApplicationEnums.BATCH_LOAD_EXPORTER.value, fhir_service=fhir_service)

        with patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration"), \
             patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO"), \
             patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations", return_value=cfg), \
             patch("pyfiles.dependencies.prerequisites.DBConnectionPool"), \
             patch("pyfiles.dependencies.prerequisites.AzureFHIRClient") as mock_azure:

            mock_azure.return_value.fhir_connectivity_check.return_value = None

            Prerequisites.prerequisite_check()
            return mock_azure

    def test_azure_fhir_client_created_and_checked_for_azure(self):
        """When fhir_service == 'azure', AzureFHIRClient is instantiated and checked."""
        mock_azure = self._run_for_fhir("azure")

        mock_azure.assert_called_once()
        mock_azure.return_value.fhir_connectivity_check.assert_called_once()


@pytest.mark.unit
class TestPrerequisiteCheckReturnValue:
    """Test the 6-tuple returned by a successful prerequisite_check."""

    def test_returns_6_tuple_on_success(self):
        """prerequisite_check() returns a tuple of exactly 6 elements."""
        cfg = _make_config(ApplicationEnums.BATCH_LOAD_EXPORTER.value, fhir_service="azure")

        with patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration"), \
             patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO"), \
             patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations", return_value=cfg), \
             patch("pyfiles.dependencies.prerequisites.DBConnectionPool"), \
             patch("pyfiles.dependencies.prerequisites.AzureFHIRClient") as mock_fhir:

            mock_fhir.return_value.fhir_connectivity_check.return_value = None

            result = Prerequisites.prerequisite_check()

        assert isinstance(result, tuple)
        assert len(result) == 6


@pytest.mark.unit
class TestPrerequisiteCheckExceptionHandling:
    """Test that exceptions in prerequisite_check are wrapped as PrerequisiteError."""

    @patch("pyfiles.dependencies.prerequisites.Handlers.logging_configuration")
    @patch("pyfiles.dependencies.prerequisites.os.getenv", return_value="INFO")
    @patch("pyfiles.dependencies.prerequisites.Prerequisites.configurations",
           side_effect=Exception("config read error"))
    def test_raises_prerequisite_error_on_exception(self, mock_config, mock_getenv, mock_log):
        """Any unexpected exception is wrapped as PrerequisiteError and propagated."""
        from pyfiles.dependencies.data_processing_error import PrerequisiteError

        with pytest.raises(PrerequisiteError):
            Prerequisites.prerequisite_check()
