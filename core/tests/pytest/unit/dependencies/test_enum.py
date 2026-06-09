"""Unit tests for enum classes in pyfiles.dependencies.enum."""

from pyfiles.dependencies.enum import (
    ApplicationEnums,
    HyperionDBConnectionEnums,
    PipelineErrorCode,
)


class TestApplicationEnums:
    """ApplicationEnums values are part of the public contract — they're matched
    against the ``APPLICATION_NAME`` env var by the entrypoint dispatch. Changing
    or removing a value is a breaking change for K8s deployments. These tests
    pin the values so future edits trigger a deliberate update."""

    def test_event_load_exporter_value(self):
        assert ApplicationEnums.EVENT_LOAD_EXPORTER.value == "event-load-exporter"

    def test_batch_load_exporter_value(self):
        assert ApplicationEnums.BATCH_LOAD_EXPORTER.value == "batch-load-exporter"

    def test_core_data_ingester_value(self):
        assert ApplicationEnums.CORE_DATA_INGESTER.value == "core-data-ingester"

    def test_scheduler_value(self):
        assert ApplicationEnums.SCHEDULER.value == "batch-scheduler"

    def test_admin_grant_manager_value(self):
        assert ApplicationEnums.ADMIN_GRANT_MANAGER.value == "admin-grant-manager"

    def test_audit_lineage_manager_value(self):
        assert ApplicationEnums.AUDIT_LINEAGE_MANAGER.value == "audit-lineage-manager"

    def test_root_password_manager_value(self):
        assert ApplicationEnums.ROOT_PASSWORD_MANAGER.value == "root-password-manager"

    def test_cluster_metadata_exporter_value(self):
        assert ApplicationEnums.CLUSTER_METADATA_EXPORTER.value == "cluster-metadata-exporter"

    def test_retry_manager_value(self):
        assert ApplicationEnums.RETRY_MANAGER.value == "retry-manager"

    def test_omop_data_ingester_removed(self):
        """OMOP was removed in the OSS cleanup. Verify the enum no longer carries it."""
        assert not hasattr(ApplicationEnums, "OMOP_DATA_INGESTER")

    def test_no_unexpected_members(self):
        """Pin the full member set; new members require a deliberate update."""
        expected = {
            "EVENT_LOAD_EXPORTER",
            "BATCH_LOAD_EXPORTER",
            "CORE_DATA_INGESTER",
            "SCHEDULER",
            "ADMIN_GRANT_MANAGER",
            "AUDIT_LINEAGE_MANAGER",
            "ROOT_PASSWORD_MANAGER",
            "CLUSTER_METADATA_EXPORTER",
            "RETRY_MANAGER",
        }
        actual = {m.name for m in ApplicationEnums}
        assert actual == expected


class TestPipelineErrorCode:
    """Error codes are surfaced in audit logs, in retry-queue routing, and in
    failure-blob filenames. The string values are part of the operational contract."""

    def test_blob_read_failed_is_601(self):
        assert PipelineErrorCode.BLOB_READ_FAILED.value == "601"

    def test_normalization_failed_is_602(self):
        assert PipelineErrorCode.NORMALIZATION_FAILED.value == "602"

    def test_insertion_failed_is_603(self):
        assert PipelineErrorCode.INSERTION_FAILED.value == "603"

    def test_unexpected_error_is_699(self):
        assert PipelineErrorCode.UNEXPECTED_ERROR.value == "699"

    def test_error_codes_are_strings(self):
        """The retry manager string-compares these against queue-message codes."""
        for code in PipelineErrorCode:
            assert isinstance(code.value, str)


class TestHyperionDBConnectionEnums:
    """Database connection identifiers used by ``Prerequisites.prerequisite_check``
    to decide which connection pool to instantiate."""

    def test_core_db_connection_value(self):
        assert HyperionDBConnectionEnums.CORE_DB_CONNECTION.value == "core_db_connection"

    def test_audit_db_connection_value(self):
        assert HyperionDBConnectionEnums.AUDIT_DB_CONNECTION.value == "audit_db_connection"

    def test_omop_db_connection_removed(self):
        """OMOP was removed in the OSS cleanup."""
        assert not hasattr(HyperionDBConnectionEnums, "OMOP_DB_CONNECTION")

    def test_no_unexpected_members(self):
        expected = {"CORE_DB_CONNECTION", "AUDIT_DB_CONNECTION"}
        actual = {m.name for m in HyperionDBConnectionEnums}
        assert actual == expected
