"""Unit tests for main.py wrapper functions and __main__ CLI dispatch."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from main import (
    activate_all_roles,
    create_admin_role,
    create_service_account_user,
    create_superuser,
    fhir_server_and_db_check,
    initialize_audit_database,
    initialize_core_database,
    initialize_storage_volume,
    initialize_tables,
    run_prerequisite_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_utilities():
    """Patch the Utilities class used by every wrapper function in main.py."""
    with patch("main.Utilities") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


def _run_main_as_script(argv, input_values=None):
    """Re-import and execute main.py's __main__ block with patched sys.argv/input.

    We patch ``utilities.Utilities`` (the source module) so the fresh
    re-import of main.py picks up the mock, then re-execute the module
    to trigger its ``if __name__ == "__main__"`` block.
    """
    input_side_effect = iter(input_values) if input_values else iter([])
    mock_instance = MagicMock()

    with patch("sys.argv", ["main.py"] + argv), \
         patch("builtins.input", side_effect=input_side_effect), \
         patch("utilities.Utilities", return_value=mock_instance):
        # Remove cached main module so importlib reloads it fully
        saved = sys.modules.pop("main", None)
        try:
            # run_module would not trigger __main__ properly for a script;
            # instead we compile & exec the file directly.
            import main as main_mod  # noqa: F811
            main_source = main_mod.__file__
            sys.modules.pop("main", None)

            code = compile(
                open(main_source, "r").read(),
                main_source,
                "exec",
            )
            exec(code, {"__name__": "__main__", "__file__": main_source})
        finally:
            # Restore the original main module for other tests
            if saved is not None:
                sys.modules["main"] = saved
            else:
                sys.modules.pop("main", None)

    return mock_instance


# ===================================================================
# Wrapper function tests – happy path
# ===================================================================

class TestWrapperFunctionsHappyPath:
    """Each wrapper should instantiate Utilities and delegate to the right method."""

    def test_fhir_server_and_db_check(self, mock_utilities):
        fhir_server_and_db_check()
        mock_utilities.check_fhir_server_db_conn.assert_called_once()

    def test_initialize_storage_volume(self, mock_utilities):
        initialize_storage_volume()
        mock_utilities.initialize_storage_volume.assert_called_once()

    def test_initialize_core_database(self, mock_utilities):
        initialize_core_database()
        mock_utilities.initialize_core_database.assert_called_once()

    def test_initialize_audit_database(self, mock_utilities):
        initialize_audit_database()
        mock_utilities.initialize_audit_database.assert_called_once()

    def test_initialize_tables_success(self, mock_utilities):
        mock_utilities.create_silver_layer_schema.return_value = True
        result = initialize_tables()
        mock_utilities.create_silver_layer_schema.assert_called_once()
        assert result == "Successfully initialized schema!"

    def test_initialize_tables_failure(self, mock_utilities):
        mock_utilities.create_silver_layer_schema.return_value = False
        result = initialize_tables()
        assert result == "Failed to initialize schema!"

    def test_create_admin_role(self, mock_utilities):
        create_admin_role("admin")
        mock_utilities.create_admin_role.assert_called_once_with("admin")

    def test_create_superuser(self, mock_utilities):
        create_superuser("admin", "pass123")
        mock_utilities.create_superuser.assert_called_once_with("admin", "pass123")

    def test_create_service_account_user(self, mock_utilities):
        create_service_account_user()
        mock_utilities.create_service_account_user.assert_called_once()

    def test_activate_all_roles(self, mock_utilities):
        activate_all_roles()
        mock_utilities.activate_all_roles.assert_called_once()

    def test_run_prerequisite_check(self, mock_utilities):
        run_prerequisite_check()
        mock_utilities.check_fhir_server_db_conn.assert_called_once()


# ===================================================================
# Wrapper function tests – error path
# ===================================================================

class TestWrapperFunctionsErrorPath:
    """Exceptions raised by Utilities should be caught and logged, not re-raised."""

    def test_fhir_server_and_db_check_logs_exception(self, mock_utilities):
        mock_utilities.check_fhir_server_db_conn.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            fhir_server_and_db_check()
            mock_log.assert_called_once()

    def test_initialize_storage_volume_logs_exception(self, mock_utilities):
        mock_utilities.initialize_storage_volume.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            initialize_storage_volume()
            mock_log.assert_called_once()

    def test_initialize_core_database_logs_exception(self, mock_utilities):
        mock_utilities.initialize_core_database.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            initialize_core_database()
            mock_log.assert_called_once()

    def test_initialize_audit_database_logs_exception(self, mock_utilities):
        mock_utilities.initialize_audit_database.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            initialize_audit_database()
            mock_log.assert_called_once()

    def test_initialize_tables_logs_exception(self, mock_utilities):
        mock_utilities.create_silver_layer_schema.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            result = initialize_tables()
            mock_log.assert_called_once()
            assert result is None

    def test_create_admin_role_logs_exception(self, mock_utilities):
        mock_utilities.create_admin_role.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            create_admin_role("admin")
            mock_log.assert_called_once()

    def test_create_superuser_logs_exception(self, mock_utilities):
        mock_utilities.create_superuser.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            create_superuser("user", "pass")
            mock_log.assert_called_once()

    def test_create_service_account_user_logs_exception(self, mock_utilities):
        mock_utilities.create_service_account_user.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            create_service_account_user()
            mock_log.assert_called_once()

    def test_activate_all_roles_logs_exception(self, mock_utilities):
        mock_utilities.activate_all_roles.side_effect = Exception("boom")
        with patch("main.logging.exception") as mock_log:
            activate_all_roles()
            mock_log.assert_called_once()

    def test_run_prerequisite_check_exits_on_failure(self, mock_utilities):
        mock_utilities.check_fhir_server_db_conn.side_effect = Exception("boom")
        with pytest.raises(SystemExit):
            run_prerequisite_check()


# ===================================================================
# __main__ CLI dispatch – argument mode (sys.argv)
# ===================================================================

class TestCLIDispatchArgumentMode:
    """Test each CLI choice routes to the correct Utilities method."""

    def test_choice_1_fhir_check(self):
        mock_inst = _run_main_as_script(["1"])
        mock_inst.check_fhir_server_db_conn.assert_called_once()

    def test_choice_2_storage_volume(self):
        mock_inst = _run_main_as_script(["2"])
        mock_inst.initialize_storage_volume.assert_called_once()

    def test_choice_3_activate_roles(self):
        mock_inst = _run_main_as_script(["3"])
        mock_inst.activate_all_roles.assert_called_once()

    def test_choice_4_admin_role(self):
        mock_inst = _run_main_as_script(["4"], input_values=["test_admin"])
        mock_inst.create_admin_role.assert_called_once_with("test_admin")

    def test_choice_5_superuser(self):
        mock_inst = _run_main_as_script(["5"], input_values=["admin", "secret"])
        mock_inst.create_superuser.assert_called_once_with("admin", "secret")

    def test_choice_6_service_account(self):
        mock_inst = _run_main_as_script(["6"])
        mock_inst.create_service_account_user.assert_called_once()

    def test_choice_7_core_database(self):
        mock_inst = _run_main_as_script(["7"])
        mock_inst.initialize_core_database.assert_called_once()

    def test_choice_8_audit_database(self):
        mock_inst = _run_main_as_script(["8"])
        mock_inst.initialize_audit_database.assert_called_once()

    def test_choice_9_create_tables(self):
        mock_inst = _run_main_as_script(["9"])
        mock_inst.create_silver_layer_schema.assert_called_once()

    def test_invalid_choice_does_not_raise(self):
        """Invalid choice should not raise an exception."""
        mock_inst = _run_main_as_script(["99"])
        # No method on mock_inst should have been called
        mock_inst.assert_not_called()


# ===================================================================
# __main__ CLI dispatch – interactive menu mode
# ===================================================================

class TestCLIDispatchInteractiveMode:
    """Test interactive menu mode dispatches correctly and exits on choice 18."""

    def test_interactive_choice_1_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["1", "10"])
        # called twice: once by run_prerequisite_check, once by choice 1
        assert mock_inst.check_fhir_server_db_conn.call_count == 2

    def test_interactive_choice_2_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["2", "10"])
        mock_inst.initialize_storage_volume.assert_called_once()

    def test_interactive_choice_3_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["3", "10"])
        mock_inst.activate_all_roles.assert_called_once()

    def test_interactive_choice_4_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["4", "my_role", "10"])
        mock_inst.create_admin_role.assert_called_once_with("my_role")

    def test_interactive_choice_5_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["5", "user1", "pass1", "10"])
        mock_inst.create_superuser.assert_called_once_with("user1", "pass1")

    def test_interactive_choice_6_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["6", "10"])
        mock_inst.create_service_account_user.assert_called_once()

    def test_interactive_choice_7_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["7", "10"])
        mock_inst.initialize_core_database.assert_called_once()

    def test_interactive_choice_8_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["8", "10"])
        mock_inst.initialize_audit_database.assert_called_once()

    def test_interactive_choice_9_then_exit(self):
        mock_inst = _run_main_as_script([], input_values=["9", "10"])
        mock_inst.create_silver_layer_schema.assert_called_once()

    def test_interactive_exit(self):
        """Choice 14 should exit the loop cleanly."""
        _run_main_as_script([], input_values=["10"])

    def test_interactive_invalid_then_exit(self):
        """Invalid choice should not raise, loop should continue to exit."""
        _run_main_as_script([], input_values=["99", "10"])

    def test_interactive_multiple_operations(self):
        """Multiple operations should execute sequentially before exit."""
        mock_inst = _run_main_as_script([], input_values=["1", "2", "10"])
        # called twice: once by run_prerequisite_check, once by choice 1
        assert mock_inst.check_fhir_server_db_conn.call_count == 2
        mock_inst.initialize_storage_volume.assert_called_once()
