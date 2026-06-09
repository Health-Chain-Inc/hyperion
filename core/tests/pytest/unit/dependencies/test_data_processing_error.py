"""Unit tests for DataProcessingException class."""
import pytest
from unittest.mock import MagicMock

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.enum import ApplicationEnums


class TestPipelineErrorHierarchy:
    """Verify the typed exception hierarchy added by the High fix (replaces sys.exit)."""

    def test_pipeline_error_subclasses_exception(self):
        from pyfiles.dependencies.data_processing_error import PipelineError
        assert issubclass(PipelineError, Exception)

    def test_prerequisite_error_subclasses_pipeline_error(self):
        from pyfiles.dependencies.data_processing_error import PipelineError, PrerequisiteError
        assert issubclass(PrerequisiteError, PipelineError)

    def test_prerequisite_error_is_caught_as_pipeline_error(self):
        from pyfiles.dependencies.data_processing_error import PipelineError, PrerequisiteError
        try:
            raise PrerequisiteError("FHIR connectivity check failed")
        except PipelineError as caught:
            assert "FHIR connectivity check failed" in str(caught)

    def test_prerequisite_error_supports_raise_from(self):
        from pyfiles.dependencies.data_processing_error import PrerequisiteError
        with pytest.raises(PrerequisiteError) as exc_info:
            try:
                raise ConnectionError("network down")
            except ConnectionError as err:
                raise PrerequisiteError("prereq failed") from err
        assert isinstance(exc_info.value.__cause__, ConnectionError)

    def test_data_processing_exception_independent_from_pipeline_error(self):
        """DataProcessingException is the original error class; not in the new hierarchy."""
        from pyfiles.dependencies.data_processing_error import DataProcessingException, PipelineError
        # Sanity: existing exception unrelated to new hierarchy
        assert not issubclass(DataProcessingException, PipelineError)


class TestDataProcessingExceptionInit:
    """Test DataProcessingException class initialization."""

    def test_stores_error_code_and_message(self):
        """Test exception initialization stores error code and message."""
        exception = DataProcessingException(
            message="Test error message",
            errors="Detailed error info",
            error_code="602"
        )

        assert str(exception) == "Test error message"
        assert exception.errors == "Detailed error info"
        assert exception.error_code == "602"

    def test_string_representation(self):
        """Test exception __str__ method."""
        exception = DataProcessingException(
            message="Normalization failed",
            errors="Invalid data format",
            error_code="602"
        )

        assert "Normalization failed" in str(exception)

    def test_inherits_from_exception(self):
        """Test that DataProcessingException inherits from Exception."""
        exception = DataProcessingException(
            message="Test",
            errors="Error",
            error_code="603"
        )

        assert isinstance(exception, Exception)

    def test_different_error_codes(self):
        """Test exception with different error codes."""
        codes = ["601", "602", "603", "604"]
        for code in codes:
            exception = DataProcessingException(
                message=f"Error with code {code}",
                errors="Some error",
                error_code=code
            )
            assert exception.error_code == code

    def test_exception_can_be_raised_and_caught(self):
        """Test exception can be raised and caught."""
        with pytest.raises(DataProcessingException) as exc_info:
            raise DataProcessingException(
                message="Test raise",
                errors="Test error",
                error_code="602"
            )

        assert exc_info.value.error_code == "602"
        assert exc_info.value.errors == "Test error"


class TestDataProcessingError:
    """Test data_processing_error method."""

    def test_copies_to_failure_container(self):
        """Test that blob is copied to failure container."""
        exception = DataProcessingException(
            message="Processing failed",
            errors="Invalid format",
            error_code="602"
        )

        mock_storage = MagicMock()
        mock_storage.copy_ndjson_to_failure.return_value = "602/batch-load/20240101/Patient-1.ndjson"

        fhir_event_message = {
            "url": "https://test.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        }

        reject_filepath, blob_url = exception.data_processing_error(
            fhir_event_message=fhir_event_message,
            filename="Patient-1.ndjson",
            storage_client=mock_storage
        )

        mock_storage.copy_ndjson_to_failure.assert_called_once_with(
            filename="Patient-1.ndjson",
            blob_url="https://test.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson",
            error_code="602"
        )
        assert reject_filepath == "602/batch-load/20240101/Patient-1.ndjson"
        assert blob_url == "https://test.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"

    def test_returns_blob_url_from_message(self):
        """Test that blob_url is extracted from message."""
        exception = DataProcessingException(
            message="Failed",
            errors="Error",
            error_code="603"
        )

        mock_storage = MagicMock()
        mock_storage.copy_ndjson_to_failure.return_value = "603/test/file.ndjson"

        fhir_event_message = {
            "url": "https://storage.blob.core.windows.net/container/test/file.ndjson",
            "resource_type": "Observation"
        }

        reject_filepath, blob_url = exception.data_processing_error(
            fhir_event_message=fhir_event_message,
            filename="Observation-1.ndjson",
            storage_client=mock_storage
        )

        assert blob_url == "https://storage.blob.core.windows.net/container/test/file.ndjson"

    def test_handles_missing_url_in_message(self):
        """Test handling when URL is missing from message."""
        exception = DataProcessingException(
            message="Failed",
            errors="Error",
            error_code="602"
        )

        mock_storage = MagicMock()
        mock_storage.copy_ndjson_to_failure.return_value = "602/default/file.ndjson"

        fhir_event_message = {}  # No URL

        reject_filepath, blob_url = exception.data_processing_error(
            fhir_event_message=fhir_event_message,
            filename="Patient-1.ndjson",
            storage_client=mock_storage
        )

        assert blob_url is None
        mock_storage.copy_ndjson_to_failure.assert_called_with(
            filename="Patient-1.ndjson",
            blob_url=None,
            error_code="602"
        )


class TestFhirPullError:
    """Test fhirpullerror method."""

    def test_increments_retry_count(self):
        """Test retry count is incremented."""
        exception = DataProcessingException(
            message="FHIR pull failed",
            errors="Connection error",
            error_code="601"
        )

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_config = {
            "FHIR": {"max_retry_count": "3"},
            "default_value": {"delay_time": "5"}
        }

        fhir_event_message = {
            "resource_id": "patient-123",
            "retry_count": 0
        }

        exception.fhirpullerror(
            fhir_event_message=fhir_event_message,
            configurations=mock_config,
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        assert fhir_event_message["retry_count"] == 1
        mock_queue.insert_to_event_load_queue.assert_called_once()

    def test_inserts_to_event_load_queue_with_delay(self):
        """Test message is inserted to event load queue with delay."""
        exception = DataProcessingException(
            message="Pull failed",
            errors="Timeout",
            error_code="601"
        )

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_config = {
            "FHIR": {"max_retry_count": "3"},
            "default_value": {"delay_time": "10"}
        }

        fhir_event_message = {
            "resource_id": "obs-456",
            "retry_count": 1
        }

        exception.fhirpullerror(
            fhir_event_message=fhir_event_message,
            configurations=mock_config,
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        mock_queue.insert_to_event_load_queue.assert_called_once_with(
            fhir_event_message, 10
        )

    def test_moves_to_reject_queue_at_max_retries(self):
        """Test message moves to reject queue at max retries."""
        exception = DataProcessingException(
            message="Pull failed",
            errors="Max retries",
            error_code="601"
        )

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_config = {
            "FHIR": {"max_retry_count": "3"},
            "default_value": {"delay_time": "5"}
        }

        fhir_event_message = {
            "resource_id": "patient-123",
            "retry_count": 2  # Will become 3, hitting max
        }

        exception.fhirpullerror(
            fhir_event_message=fhir_event_message,
            configurations=mock_config,
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        mock_queue.insert_to_reject_queue.assert_called_once()
        assert fhir_event_message.get("retry_message") is True
        assert "retry_count" not in fhir_event_message

    def test_uploads_to_failure_on_retry_message(self):
        """Test failure upload when retry_message is True."""
        exception = DataProcessingException(
            message="Pull failed",
            errors="Final failure",
            error_code="601"
        )

        mock_storage = MagicMock()
        mock_storage.generate_blob_path.return_value = "601/20240101/Patient-1.json"
        mock_queue = MagicMock()
        mock_config = {
            "FHIR": {"max_retry_count": "3"},
            "default_value": {"delay_time": "5"}
        }

        fhir_event_message = {
            "resource_id": "patient-123",
            "retry_count": 0,
            "retry_message": True
        }

        exception.fhirpullerror(
            fhir_event_message=fhir_event_message,
            configurations=mock_config,
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        mock_storage.upload_json_to_failure.assert_called_once()
        mock_storage.generate_blob_path.assert_called_once()

    def test_batch_load_uses_fhir_parameter_queue(self):
        """Test batch load uses FHIR parameter queue for retries."""
        exception = DataProcessingException(
            message="Pull failed",
            errors="Batch error",
            error_code="601"
        )

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_config = {
            "FHIR": {"max_retry_count": "3"},
            "default_value": {"delay_time": "5"}
        }

        fhir_event_message = {
            "resource_id": "patient-123",
            "retry_count": 0
        }

        exception.fhirpullerror(
            fhir_event_message=fhir_event_message,
            configurations=mock_config,
            application_name=ApplicationEnums.BATCH_LOAD_EXPORTER.value,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        mock_queue.insert_to_fhir_parameter_queue.assert_called_once()

    def test_sets_application_name_on_reject(self):
        """Test application name is set when moving to reject queue."""
        exception = DataProcessingException(
            message="Pull failed",
            errors="Error",
            error_code="601"
        )

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_config = {
            "FHIR": {"max_retry_count": "3"},
            "default_value": {"delay_time": "5"}
        }

        fhir_event_message = {
            "resource_id": "patient-123",
            "retry_count": 2  # Will hit max
        }

        exception.fhirpullerror(
            fhir_event_message=fhir_event_message,
            configurations=mock_config,
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        assert fhir_event_message.get("application_name") == ApplicationEnums.EVENT_LOAD_EXPORTER.value

    def test_handles_no_initial_retry_count(self):
        """Test handling when retry_count is not in message."""
        exception = DataProcessingException(
            message="Pull failed",
            errors="Error",
            error_code="601"
        )

        mock_storage = MagicMock()
        mock_queue = MagicMock()
        mock_config = {
            "FHIR": {"max_retry_count": "3"},
            "default_value": {"delay_time": "5"}
        }

        fhir_event_message = {
            "resource_id": "patient-123"
            # No retry_count
        }

        exception.fhirpullerror(
            fhir_event_message=fhir_event_message,
            configurations=mock_config,
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            storage_client=mock_storage,
            queue_client=mock_queue
        )

        assert fhir_event_message["retry_count"] == 1


class TestExceptionChaining:
    """Test exception chaining behavior."""

    def test_exception_chain_preserves_original(self):
        """Test that exception chaining preserves original exception."""
        original = ValueError("Original error")

        try:
            try:
                raise original
            except ValueError as e:
                raise DataProcessingException(
                    message="Wrapped error",
                    errors=str(e),
                    error_code="602"
                ) from e
        except DataProcessingException as dpe:
            assert dpe.__cause__ is original
            assert dpe.error_code == "602"

    def test_exception_can_wrap_multiple_errors(self):
        """Test exception can wrap multiple error details."""
        errors = ["Error 1", "Error 2", "Error 3"]

        exception = DataProcessingException(
            message="Multiple errors occurred",
            errors="; ".join(errors),
            error_code="602"
        )

        assert "Error 1" in exception.errors
        assert "Error 2" in exception.errors
        assert "Error 3" in exception.errors
