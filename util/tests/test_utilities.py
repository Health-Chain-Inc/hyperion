"""Unit tests for utilities.py — Utilities class."""

from unittest.mock import MagicMock, patch

import pytest

from utilities import Utilities
from pyfiles.dependencies.utilityexception import UtilityException

# Module path prefix for patching
MOD = "utilities"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_config():
    return {
        "silver_layer": {
            "core_database": "core_db",
            "audit_database": "audit_db",
            "storage_volume": "test_volume",
            "catalog": "test_catalog",
            "replication_number": "1",
            "username": "root",
            "password": "pass",
        },
        "initialization": {
            "cloud_storage": "azure",
        },
        "azure.storage": {
            "version": "1",
            "locations": "wasbs://container@account.blob.core.windows.net/",
            "end_point": "https://account.blob.core.windows.net",
            "access_key": "key",
            "source_connection_string": "DefaultEndpointsProtocol=https;AccountName=test",
            "source_stage_container": "source-container",
        },
        "local.storage": {
            "locations": "s3://hyperion/",
            "endpoint": "http://minio:9000",
            "region": "us-east-1",
            "access_key_id": "minioadmin",
            "access_key_secret": "minioadmin123",
        },
        "schema": {
            "resource": "schema/fhir.schema.json",
            "destination": "schema/output/silver_layer_all.sql",
            "common_table_schema_path": "schema/common_tables.sql",
            "overwrite_schema": "true",
            "database_initialization_flag": "true",
        },
        "default_value": {
            "is_audit": "true",
            "is_lineage": "true",
        },
        "service_account": {
            "user_name": "svc_user",
            "password": "svc_pass",
        },
    }


@pytest.fixture
def initializer(base_config):
    with patch(f"{MOD}.Handlers"):
        obj = Utilities()
    obj.initialize = MagicMock(return_value=(base_config, None, None))
    return obj


@pytest.fixture
def mock_db_connection():
    conn = MagicMock()
    conn.connect.return_value.__enter__.return_value = conn
    return conn


# ===================================================================
# Existing tests — initialize_core_database / initialize_audit_database
# ===================================================================

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_core_database(mock_pool, mock_execute, initializer, base_config, mock_db_connection):
    mock_pool.return_value.initialize.return_value = mock_db_connection

    initializer.initialize_core_database()

    mock_execute.assert_called_once_with(
        mock_db_connection,
        "CREATE DATABASE core_db;"
    )

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_audit_database(mock_pool, mock_execute, initializer, base_config, mock_db_connection):
    mock_pool.return_value.initialize.return_value = mock_db_connection

    initializer.initialize_audit_database()

    mock_execute.assert_called_once_with(
        mock_db_connection,
        "CREATE DATABASE audit_db;"
    )


# ===================================================================
# Existing tests — initialize_storage_volume
# ===================================================================

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_already_exists(
    mock_pool, mock_execute, initializer, base_config, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection

    result_proxy = MagicMock()
    result_proxy.fetchall.return_value = [("test_volume",)]
    result_proxy.keys.return_value = ["Storage Volume"]

    mock_db_connection.execute.return_value = result_proxy

    initializer.initialize_storage_volume()

    mock_execute.assert_not_called()

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_azure_azblob(
    mock_pool, mock_execute, initializer, base_config, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.return_value.fetchall.return_value = []
    mock_db_connection.execute.return_value.keys.return_value = ["Storage Volume"]

    initializer.initialize_storage_volume()

    assert mock_execute.call_count == 3
    assert "CREATE STORAGE VOLUME test_volume" in mock_execute.call_args_list[0][0][1]
    assert "AZBLOB" in mock_execute.call_args_list[0][0][1]

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_azure_adls2(
    mock_pool, mock_execute, initializer, base_config, mock_db_connection
):
    base_config["azure.storage"]["version"] = "2"
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.return_value.fetchall.return_value = []
    mock_db_connection.execute.return_value.keys.return_value = ["Storage Volume"]

    initializer.initialize_storage_volume()

    assert "ADLS2" in mock_execute.call_args_list[0][0][1]

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_local_minio(
    mock_pool, mock_execute, initializer, base_config, mock_db_connection
):
    base_config["initialization"]["cloud_storage"] = "local"
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.return_value.fetchall.return_value = []
    mock_db_connection.execute.return_value.keys.return_value = ["Storage Volume"]

    initializer.initialize_storage_volume()

    assert "TYPE = S3" in mock_execute.call_args_list[0][0][1]
    assert mock_execute.call_count == 3


@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_unsupported_raises(
    mock_pool, mock_execute, initializer, base_config, mock_db_connection
):
    base_config["initialization"]["cloud_storage"] = "aws"
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.return_value.fetchall.return_value = []
    mock_db_connection.execute.return_value.keys.return_value = ["Storage Volume"]

    with pytest.raises(UtilityException):
        initializer.initialize_storage_volume()


@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_sets_defaults(
    mock_pool, mock_execute, initializer, base_config, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.return_value.fetchall.return_value = []
    mock_db_connection.execute.return_value.keys.return_value = ["Storage Volume"]

    initializer.initialize_storage_volume()

    calls = [c[0][1] for c in mock_execute.call_args_list]

    assert any("SET test_volume AS DEFAULT STORAGE VOLUME" in c for c in calls)
    assert any("activate_all_roles_on_login" in c for c in calls)


# ===================================================================
# Existing negative tests
# ===================================================================

def test_initialize_core_database_initialize_failure(initializer):
    initializer.initialize.side_effect = Exception("Init failed")

    with pytest.raises(Exception):
        initializer.initialize_core_database()


def test_initialize_audit_database_initialize_failure(initializer):
    initializer.initialize.side_effect = Exception("Init failed")

    with pytest.raises(Exception):
        initializer.initialize_audit_database()


def test_initialize_storage_volume_initialize_failure(initializer):
    initializer.initialize.side_effect = Exception("Init failed")

    with pytest.raises(Exception):
        initializer.initialize_storage_volume()

@patch(f"{MOD}.DBConnectionPool")
def test_initialize_core_database_db_connection_failure(mock_pool, initializer):
    mock_pool.return_value.initialize.side_effect = Exception("DB unavailable")

    with pytest.raises(Exception):
        initializer.initialize_core_database()


@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_db_connection_failure(mock_pool, initializer):
    mock_pool.return_value.initialize.side_effect = Exception("DB unavailable")

    with pytest.raises(Exception):
        initializer.initialize_storage_volume()

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_core_database_sql_failure(
    mock_pool, mock_execute, initializer, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_execute.side_effect = Exception("SQL error")

    with pytest.raises(Exception):
        initializer.initialize_core_database()


@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_audit_database_sql_failure(
    mock_pool, mock_execute, initializer, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_execute.side_effect = Exception("SQL error")

    with pytest.raises(Exception):
        initializer.initialize_audit_database()

@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_show_volumes_failure(
    mock_pool, initializer, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.side_effect = Exception("Permission denied")

    with pytest.raises(Exception):
        initializer.initialize_storage_volume()

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_create_sql_failure(
    mock_pool, mock_execute, initializer, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.return_value.fetchall.return_value = []
    mock_db_connection.execute.return_value.keys.return_value = ["Storage Volume"]

    mock_execute.side_effect = Exception("Create volume failed")

    with pytest.raises(Exception):
        initializer.initialize_storage_volume()

@patch(f"{MOD}.execute_sql_statement")
@patch(f"{MOD}.DBConnectionPool")
def test_initialize_storage_volume_set_default_failure(
    mock_pool, mock_execute, initializer, mock_db_connection
):
    mock_pool.return_value.initialize.return_value = mock_db_connection
    mock_db_connection.execute.return_value.fetchall.return_value = []
    mock_db_connection.execute.return_value.keys.return_value = ["Storage Volume"]

    # CREATE succeeds, SET DEFAULT fails
    mock_execute.side_effect = [None, Exception("SET failed")]

    with pytest.raises(Exception):
        initializer.initialize_storage_volume()


# ===================================================================
# NEW TESTS — __init__
# ===================================================================

class TestInit:

    @patch(f"{MOD}.os.getenv", return_value="DEBUG")
    @patch(f"{MOD}.Handlers")
    def test_init_calls_logging_configuration(self, mock_handlers, mock_getenv):
        Utilities()
        mock_handlers.logging_configuration.assert_called_once()
        args = mock_handlers.logging_configuration.call_args[0]
        assert isinstance(args[0], list)  # excluded_filenames
        assert args[1] == "DEBUG"


# ===================================================================
# NEW TESTS — initialize
# ===================================================================

class TestInitialize:

    @patch(f"{MOD}.Prerequisites")
    @patch(f"{MOD}.Handlers")
    def test_initialize_success(self, mock_handlers, mock_prereqs):
        mock_prereqs.prerequisite_check.return_value = ({"config": True}, "core_pool", "audit_pool")

        obj = Utilities()
        result = obj.initialize(True)

        mock_prereqs.prerequisite_check.assert_called_once_with(True)
        assert result == ({"config": True}, "core_pool", "audit_pool")

    @patch(f"{MOD}.Prerequisites")
    @patch(f"{MOD}.Handlers")
    def test_initialize_failure_raises_utility_exception(self, mock_handlers, mock_prereqs):
        mock_prereqs.prerequisite_check.side_effect = Exception("prereq fail")

        obj = Utilities()
        with pytest.raises(UtilityException, match="Initialize function failed"):
            obj.initialize(True)


# ===================================================================
# NEW TESTS — check_fhir_server_db_conn
# ===================================================================

class TestCheckFhirServerDbConn:

    def test_success(self, initializer):
        initializer.initialize.return_value = ({}, None, None)
        # Should not raise
        initializer.check_fhir_server_db_conn()
        initializer.initialize.assert_called_once_with(True)

    def test_failure_raises_utility_exception(self, initializer):
        initializer.initialize.side_effect = Exception("conn fail")

        with pytest.raises(UtilityException, match="FHIR Server connection"):
            initializer.check_fhir_server_db_conn()


# ===================================================================
# NEW TESTS — create_silver_layer_schema
# ===================================================================

class TestCreateSilverLayerSchema:

    @patch(f"{MOD}.execute_sql_file")
    @patch(f"{MOD}.ResourceSchemaGenerator")
    @patch(f"{MOD}.FhirServerHandler")
    @patch(f"{MOD}.check_first_run", return_value=True)
    @patch(f"{MOD}.fetch_data", return_value=None)
    @patch(f"{MOD}.insert_or_update_pipeline_meta_info", return_value=("INSERT ...", {}))
    @patch(f"{MOD}.execute_sql_statement")
    def test_returns_true_on_success(
        self, mock_exec, mock_insert_meta, mock_fetch, mock_first_run,
        mock_fsh, mock_rsg, mock_exec_file, initializer, base_config
    ):
        mock_audit = MagicMock()
        initializer.initialize.return_value = (base_config, MagicMock(), mock_audit)
        mock_fsh.return_value.get_resource_list.return_value = ["Patient", "Observation"]

        with patch(f"{MOD}.os.path.exists", return_value=False):
            result = initializer.create_silver_layer_schema()

        assert result is True

    @patch(f"{MOD}.FhirServerHandler")
    @patch(f"{MOD}.check_first_run", return_value=False)
    def test_returns_false_on_exception(self, mock_first_run, mock_fsh, initializer, base_config):
        initializer.initialize.return_value = (base_config, MagicMock(), MagicMock())
        mock_fsh.return_value.get_resource_list.side_effect = Exception("FHIR fail")

        result = initializer.create_silver_layer_schema()

        assert result is False

    @patch(f"{MOD}.execute_sql_file")
    @patch(f"{MOD}.ResourceSchemaGenerator")
    @patch(f"{MOD}.FhirServerHandler")
    @patch(f"{MOD}.check_first_run", return_value=False)
    @patch(f"{MOD}.fetch_data", return_value=None)
    @patch(f"{MOD}.insert_or_update_pipeline_meta_info", return_value=("INSERT ...", {}))
    @patch(f"{MOD}.execute_sql_statement")
    def test_skips_schema_when_exists_and_overwrite_false(
        self, mock_exec, mock_insert_meta, mock_fetch, mock_first_run,
        mock_fsh, mock_rsg, mock_exec_file, initializer, base_config
    ):
        base_config["schema"]["overwrite_schema"] = "false"
        mock_audit = MagicMock()
        initializer.initialize.return_value = (base_config, MagicMock(), mock_audit)
        mock_fsh.return_value.get_resource_list.return_value = ["Patient"]

        with patch(f"{MOD}.os.path.exists", return_value=True):
            result = initializer.create_silver_layer_schema()

        mock_rsg.assert_not_called()
        assert result is True

    @patch(f"{MOD}.execute_sql_file")
    @patch(f"{MOD}.ResourceSchemaGenerator")
    @patch(f"{MOD}.FhirServerHandler")
    @patch(f"{MOD}.check_first_run", return_value=False)
    @patch(f"{MOD}.fetch_data", return_value=None)
    @patch(f"{MOD}.insert_or_update_pipeline_meta_info", return_value=("INSERT ...", {}))
    @patch(f"{MOD}.execute_sql_statement")
    def test_skips_db_init_when_flag_false(
        self, mock_exec, mock_insert_meta, mock_fetch, mock_first_run,
        mock_fsh, mock_rsg, mock_exec_file, initializer, base_config
    ):
        base_config["schema"]["database_initialization_flag"] = "false"
        mock_audit = MagicMock()
        initializer.initialize.return_value = (base_config, MagicMock(), mock_audit)
        mock_fsh.return_value.get_resource_list.return_value = ["Patient"]

        with patch(f"{MOD}.os.path.exists", return_value=False):
            result = initializer.create_silver_layer_schema()

        mock_exec_file.assert_not_called()
        assert result is True

    @patch(f"{MOD}.execute_sql_file")
    @patch(f"{MOD}.ResourceSchemaGenerator")
    @patch(f"{MOD}.FhirServerHandler")
    @patch(f"{MOD}.check_first_run", return_value=True)
    @patch(f"{MOD}.fetch_data", return_value=None)
    @patch(f"{MOD}.insert_or_update_pipeline_meta_info", return_value=("INSERT ...", {}))
    @patch(f"{MOD}.execute_sql_statement")
    def test_first_run_inserts_meta_info(
        self, mock_exec, mock_insert_meta, mock_fetch, mock_first_run,
        mock_fsh, mock_rsg, mock_exec_file, initializer, base_config
    ):
        mock_audit = MagicMock()
        initializer.initialize.return_value = (base_config, MagicMock(), mock_audit)
        mock_fsh.return_value.get_resource_list.return_value = ["Patient"]

        with patch(f"{MOD}.os.path.exists", return_value=False):
            initializer.create_silver_layer_schema()

        # On first run, meta info insert happens at the end
        mock_insert_meta.assert_called_once()

    @patch(f"{MOD}.execute_sql_file")
    @patch(f"{MOD}.ResourceSchemaGenerator")
    @patch(f"{MOD}.FhirServerHandler")
    @patch(f"{MOD}.check_first_run", return_value=False)
    @patch(f"{MOD}.fetch_data", return_value=None)
    @patch(f"{MOD}.insert_or_update_pipeline_meta_info", return_value=("INSERT ...", {}))
    @patch(f"{MOD}.execute_sql_statement")
    def test_not_first_run_inserts_meta_in_overwrite_block(
        self, mock_exec, mock_insert_meta, mock_fetch, mock_first_run,
        mock_fsh, mock_rsg, mock_exec_file, initializer, base_config
    ):
        mock_audit = MagicMock()
        initializer.initialize.return_value = (base_config, MagicMock(), mock_audit)
        mock_fsh.return_value.get_resource_list.return_value = ["Patient"]

        with patch(f"{MOD}.os.path.exists", return_value=False):
            initializer.create_silver_layer_schema()

        # Not first run: meta info insert happens in the overwrite block
        mock_insert_meta.assert_called_once()


# ===================================================================
# NEW TESTS — create_superuser
# ===================================================================

class TestCreateSuperuser:

    @patch(f"{MOD}.execute_sql_statement")
    @patch(f"{MOD}.DBConnectionPool")
    @patch("builtins.input", side_effect=["no"])
    def test_create_user_then_exit(self, mock_input, mock_pool, mock_execute, initializer):
        mock_pool.return_value.initialize.return_value = MagicMock()

        initializer.create_superuser("admin", "pass123")

        # First call: CREATE USER
        create_call = mock_execute.call_args_list[0][0][1]
        assert "CREATE USER" in create_call
        assert "admin" in create_call

    @patch(f"{MOD}.execute_sql_statement")
    @patch(f"{MOD}.DBConnectionPool")
    @patch("builtins.input", side_effect=["yes", "grant all to admin", "no"])
    def test_create_user_grant_then_exit(self, mock_input, mock_pool, mock_execute, initializer):
        mock_pool.return_value.initialize.return_value = MagicMock()

        initializer.create_superuser("admin", "pass123")

        # First call: CREATE USER, second call: grant statement
        assert mock_execute.call_count == 2
        grant_call = mock_execute.call_args_list[1][0][1]
        assert "grant all to admin" in grant_call


# ===================================================================
# NEW TESTS — create_service_account_user
# ===================================================================

class TestCreateServiceAccountUser:

    @patch(f"{MOD}.execute_sql_statement")
    @patch(f"{MOD}.DBConnectionPool")
    def test_grants_engine_databases(self, mock_pool, mock_execute, initializer, base_config):
        initializer.initialize.return_value = (base_config, None, None)
        mock_pool.return_value.initialize.return_value = MagicMock()

        initializer.create_service_account_user()

        # CREATE USER, GRANT catalog, GRANT user_admin, + grants on core_db and audit_db = 5 calls
        assert mock_execute.call_count == 5
        calls = [c[0][1] for c in mock_execute.call_args_list]
        assert any("CREATE USER IF NOT EXISTS" in c for c in calls)
        assert any("GRANT ALL ON CATALOG" in c for c in calls)
        assert any("GRANT user_admin" in c for c in calls)
        assert any("core_db" in c for c in calls)
        assert any("audit_db" in c for c in calls)

    @patch(f"{MOD}.execute_sql_statement")
    @patch(f"{MOD}.DBConnectionPool")
    def test_failure_propagates(self, mock_pool, mock_execute, initializer):
        initializer.initialize.side_effect = Exception("fail")

        with pytest.raises(Exception):
            initializer.create_service_account_user()


# ===================================================================
# NEW TESTS — create_admin_role
# ===================================================================

class TestCreateAdminRole:

    @patch(f"{MOD}.execute_sql_statement")
    @patch(f"{MOD}.DBConnectionPool")
    def test_success(self, mock_pool, mock_execute, initializer, base_config):
        mock_pool.return_value.initialize.return_value = MagicMock()

        initializer.create_admin_role("db_admin")

        assert mock_execute.call_count == 3
        calls = [c[0][1] for c in mock_execute.call_args_list]
        assert any("CREATE ROLE IF NOT EXISTS db_admin" in c for c in calls)
        assert any("GRANT ALL ON CATALOG test_catalog TO ROLE db_admin" in c for c in calls)
        assert any("GRANT user_admin TO ROLE db_admin" in c for c in calls)

    def test_failure_propagates(self, initializer):
        initializer.initialize.side_effect = Exception("fail")

        with pytest.raises(Exception):
            initializer.create_admin_role("admin")


# ===================================================================
# NEW TESTS — activate_all_roles
# ===================================================================

class TestActivateAllRoles:

    @patch(f"{MOD}.execute_sql_statement")
    @patch(f"{MOD}.DBConnectionPool")
    def test_success(self, mock_pool, mock_execute, initializer):
        mock_pool.return_value.initialize.return_value = MagicMock()

        initializer.activate_all_roles()

        mock_execute.assert_called_once()
        assert "activate_all_roles_on_login" in mock_execute.call_args[0][1]

    def test_failure_propagates(self, initializer):
        initializer.initialize.side_effect = Exception("fail")

        with pytest.raises(Exception):
            initializer.activate_all_roles()


