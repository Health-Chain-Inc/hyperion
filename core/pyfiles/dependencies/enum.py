from enum import Enum


class ApplicationEnums(Enum):
    """
    Enum class with application name
    """
    EVENT_LOAD_EXPORTER = "event-load-exporter"
    BATCH_LOAD_EXPORTER = "batch-load-exporter"
    CORE_DATA_INGESTER = "core-data-ingester"
    SCHEDULER = "batch-scheduler"
    ADMIN_GRANT_MANAGER = "admin-grant-manager"
    AUDIT_LINEAGE_MANAGER = "audit-lineage-manager"
    ROOT_PASSWORD_MANAGER = "root-password-manager"
    CLUSTER_METADATA_EXPORTER = "cluster-metadata-exporter"
    RETRY_MANAGER = "retry-manager"

class PipelineErrorCode(Enum):
    """Pipeline error codes for ingester failure classification."""
    BLOB_READ_FAILED = "601"
    NORMALIZATION_FAILED = "602"
    INSERTION_FAILED = "603"
    UNEXPECTED_ERROR = "699"


class HyperionDBConnectionEnums(Enum):
    """
    Hyperion database connections types
    """
    CORE_DB_CONNECTION = "core_db_connection"
    AUDIT_DB_CONNECTION = "audit_db_connection"
