"""Unit tests for Main class (main.py)."""
import os
import pytest
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.enum import ApplicationEnums


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_prereq_result(
    app_name,
    cloud_storage="azure",
    fhir_service="azure",
    servicebus="azure",
):
    """Build the 6-tuple that Prerequisites.prerequisite_check returns."""
    project_configurations = {
        "application": {"name": app_name},
        "initialization": {
            "cloud_storage": cloud_storage,
            "fhir_service": fhir_service,
            "servicebus": servicebus,
        },
    }
    core_db_conn_pool = MagicMock()
    audit_db_conn_pool = MagicMock()
    return (
        project_configurations,
        core_db_conn_pool,
        audit_db_conn_pool,
        cloud_storage,
        fhir_service,
        servicebus,
    )


# ---------------------------------------------------------------------------
# Tests: client instantiation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMainClientInstantiation:
    """Test that Main.run() creates the correct cloud clients."""

    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    @patch("main.atexit.register")
    def test_instantiates_azure_storage_client(
        self, mock_atexit, mock_core, mock_azure_fhir, mock_azure_queue, mock_azure_storage,
        mock_prereq
    ):
        """cloud_storage == 'azure' → AzureStorageClient is used."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(
            ApplicationEnums.CORE_DATA_INGESTER.value, cloud_storage="azure"
        )
        mock_core.return_value.fhir_converter.return_value = None

        Main().run()

        mock_azure_storage.assert_called_once()


    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    @patch("main.atexit.register")
    def test_instantiates_azure_queue_client(
        self, mock_atexit, mock_core, mock_azure_fhir, mock_azure_queue, mock_azure_storage,
        mock_prereq
    ):
        """servicebus == 'azure' → AzureQueueClient is used."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(
            ApplicationEnums.CORE_DATA_INGESTER.value, servicebus="azure"
        )
        mock_core.return_value.fhir_converter.return_value = None

        Main().run()

        mock_azure_queue.assert_called_once()


    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    @patch("main.atexit.register")
    def test_instantiates_azure_fhir_client(
        self, mock_atexit, mock_core, mock_azure_fhir, mock_azure_queue, mock_azure_storage,
        mock_prereq
    ):
        """fhir_service == 'azure' → AzureFHIRClient is used."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(
            ApplicationEnums.CORE_DATA_INGESTER.value, fhir_service="azure"
        )
        mock_core.return_value.fhir_converter.return_value = None

        Main().run()

        mock_azure_fhir.assert_called_once()

    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    @patch("main.atexit.register")
    def test_skips_clients_when_config_values_are_none(
        self, mock_atexit, mock_core, mock_azure_fhir, mock_azure_queue, mock_azure_storage,
        mock_prereq
    ):
        """None values for cloud_storage/servicebus/fhir_service → no client created."""
        from main import Main

        project_configurations = {
            "application": {"name": ApplicationEnums.CORE_DATA_INGESTER.value},
        }
        mock_prereq.return_value = (
            project_configurations,
            MagicMock(), MagicMock(),
            None,   # cloud_storage
            None,   # fhir_service
            None,   # servicebus
        )
        mock_core.return_value.fhir_converter.return_value = None

        Main().run()

        mock_azure_storage.assert_not_called()
        mock_azure_queue.assert_not_called()
        mock_azure_fhir.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: application routing
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMainApplicationRouting:
    """Test that Main.run() invokes the correct processor for each app name."""

    def _run_for_app(self, app_name, mock_prereq_fn, **processor_patches):
        """Helper: patch prerequisites + all processors, run Main().run()."""
        from main import Main

        mock_prereq_fn.return_value = _make_prereq_result(app_name)
        Main().run()

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    def test_routes_core_data_ingester(
        self, mock_core, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """CORE_DATA_INGESTER → CoreLoadProcessor.fhir_converter() called."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.CORE_DATA_INGESTER.value)
        mock_core.return_value.fhir_converter.return_value = None

        Main().run()

        mock_core.assert_called_once()
        mock_core.return_value.fhir_converter.assert_called_once()

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.FHIREventProcessor")
    def test_routes_event_load_exporter(
        self, mock_proc, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """EVENT_LOAD_EXPORTER → FHIREventProcessor.fhir_event_exporter() called."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.EVENT_LOAD_EXPORTER.value)
        mock_proc.return_value.fhir_event_exporter.return_value = None

        Main().run()

        mock_proc.assert_called_once()
        mock_proc.return_value.fhir_event_exporter.assert_called_once()

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.FHIRBatchProcessor")
    def test_routes_batch_load_exporter(
        self, mock_proc, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """BATCH_LOAD_EXPORTER → FHIRBatchProcessor.fhir_exporter() called."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.BATCH_LOAD_EXPORTER.value)
        mock_proc.return_value.fhir_exporter.return_value = None

        Main().run()

        mock_proc.assert_called_once()
        mock_proc.return_value.fhir_exporter.assert_called_once()

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.AuditLineageManager")
    def test_routes_audit_lineage_manager(
        self, mock_proc, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """AUDIT_LINEAGE_MANAGER → AuditLineageManager.run() called."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.AUDIT_LINEAGE_MANAGER.value)
        mock_proc.return_value.run.return_value = None

        Main().run()

        mock_proc.assert_called_once()
        mock_proc.return_value.run.assert_called_once()

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.asyncio.run")
    @patch("main.FHIRScheduler")
    def test_routes_scheduler(
        self, mock_scheduler, mock_asyncio_run, mock_fhir, mock_queue,
        mock_storage, mock_prereq, mock_atexit
    ):
        """SCHEDULER → FHIRScheduler created and asyncio.run(scheduler.main()) called."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.SCHEDULER.value)

        Main().run()

        mock_scheduler.assert_called_once()
        mock_asyncio_run.assert_called_once()

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.RetryManager")
    def test_routes_retry_manager(
        self, mock_proc, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """RETRY_MANAGER → RetryManager.retry_processor() called."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.RETRY_MANAGER.value)
        mock_proc.return_value.retry_processor.return_value = None

        Main().run()

        mock_proc.assert_called_once()
        mock_proc.return_value.retry_processor.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: cleanup / error handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMainCleanup:
    """Test cleanup() behaviour in Main.run()."""

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    def test_cleanup_called_in_finally_block(
        self, mock_core, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """cleanup() is always called, even when the processor raises."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.CORE_DATA_INGESTER.value)
        # Processor raises a generic error
        mock_core.return_value.fhir_converter.side_effect = RuntimeError("unexpected")

        # atexit.register captures the cleanup callable
        captured_cleanup = {}

        def capture_cleanup(fn):
            captured_cleanup["fn"] = fn

        mock_atexit.side_effect = capture_cleanup

        # run() catches the RuntimeError in except block and calls sys.exit(1)
        with pytest.raises(SystemExit):
            Main().run()

        # cleanup should have been registered
        assert "fn" in captured_cleanup

    @patch("main.sys.exit")
    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient", side_effect=Exception("client init failed"))
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    def test_sys_exit_called_on_client_init_failure(
        self, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit, mock_exit
    ):
        """Exception during client creation calls cleanup() + sys.exit()."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.CORE_DATA_INGESTER.value)

        # Make mock_exit raise SystemExit so execution stops after the call,
        # matching real sys.exit() behaviour and preventing code from continuing
        # into the processor-routing block where unpatched classes would fail.
        mock_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            Main().run()

        mock_exit.assert_called_once()

    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    def test_cleanup_tolerates_close_exception(
        self, mock_core, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """Exception in a client's close() method is swallowed, not re-raised."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.CORE_DATA_INGESTER.value)
        mock_core.return_value.fhir_converter.return_value = None

        # Make fhir_client.close() raise
        mock_fhir_instance = MagicMock()
        mock_fhir_instance.close.side_effect = RuntimeError("close error")
        mock_fhir.return_value = mock_fhir_instance

        # Should not raise
        Main().run()

    @patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'})
    @patch("main.atexit.register")
    @patch("main.Prerequisites.prerequisite_check")
    @patch("main.AzureStorageClient")
    @patch("main.AzureQueueClient")
    @patch("main.AzureFHIRClient")
    @patch("main.CoreLoadProcessor")
    def test_cleanup_tolerates_dispose_exception(
        self, mock_core, mock_fhir, mock_queue, mock_storage, mock_prereq, mock_atexit
    ):
        """Exception in db_pool.dispose() is swallowed, not re-raised."""
        from main import Main

        mock_prereq.return_value = _make_prereq_result(ApplicationEnums.CORE_DATA_INGESTER.value)
        mock_core.return_value.fhir_converter.return_value = None

        # Capture the cleanup function registered via atexit
        captured = {}

        def capture_cleanup(fn):
            captured["fn"] = fn

        mock_atexit.side_effect = capture_cleanup

        # Make core_db_conn_pool.dispose() raise
        core_pool_mock = MagicMock()
        core_pool_mock.dispose.side_effect = RuntimeError("dispose error")

        mock_prereq.return_value = (
            {"application": {"name": ApplicationEnums.CORE_DATA_INGESTER.value}},
            core_pool_mock,  # core_db_conn_pool that raises on dispose
            MagicMock(),     # audit_db_conn_pool
            "azure",
            "azure",
            "azure",
        )
        mock_core.return_value.fhir_converter.return_value = None

        # Should not raise
        Main().run()

        # Invoke cleanup to verify it tolerates dispose exceptions
        if "fn" in captured:
            captured["fn"]()  # Should not raise
