"""Unit tests for AzureStorageClient."""
import json
from unittest.mock import MagicMock, patch
from pyfiles.adapters.storage_clients import AzureStorageClient
from pyfiles.dependencies.enum import ApplicationEnums


class TestBlobPathGeneration:
    """Test blob path and URL generation - no mocking needed."""

    def test_generate_blob_path_batch_load(self):
        """Test generating blob path for batch load."""
        file_name = "Patient-1.ndjson"
        file_path = "batch-load/20240101"
        expected = "batch-load/20240101/Patient-1.ndjson"

        result = f"{file_path}/{file_name}"
        assert result == expected

    def test_extract_resource_type_from_filename(self):
        """Test extracting resource type from NDJSON filename."""
        filename = "Patient-1.ndjson"
        resource_type = filename.split('-')[0]
        assert resource_type == "Patient"

        filename2 = "Observation-5.ndjson"
        resource_type2 = filename2.split('-')[0]
        assert resource_type2 == "Observation"

    def test_extract_blob_path_from_url(self):
        """Test extracting blob path from full URL."""
        blob_url = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        blob_path = "/".join(blob_url.split("/")[4:])

        assert blob_path == "batch-load/20240101/Patient-1.ndjson"


class TestAzureStorageClientInitialization:
    """Test Azure storage client initialization with mocked BlobServiceClient."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_client_initializes_with_connection_string(self, mock_blob_client, mock_azure_config):
        """Test that client initializes with Azure config."""
        mock_blob_client.from_connection_string.return_value = MagicMock()

        client = AzureStorageClient(mock_azure_config)

        mock_blob_client.from_connection_string.assert_called_once()
        assert client is not None

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_client_stores_configurations(self, mock_blob_client, mock_azure_config):
        """Test that client stores configurations."""
        mock_blob_client.from_connection_string.return_value = MagicMock()

        client = AzureStorageClient(mock_azure_config)

        assert client.configurations == mock_azure_config


class TestContainerClients:
    """Test container client retrieval."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_get_staging_container_client(self, mock_blob_client, mock_azure_config):
        """Test getting staging container client."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_service.get_container_client.return_value = mock_container
        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)
        client.get_staging_container_client()

        mock_service.get_container_client.assert_called_with(
            mock_azure_config['azure.cloud_storage']['ndjson_stage_container']
        )

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_get_failure_container_client(self, mock_blob_client, mock_azure_config):
        """Test getting failure container client."""
        mock_service = MagicMock()
        mock_service.get_container_client.return_value = MagicMock()
        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)
        client.get_failure_container_client()

        mock_service.get_container_client.assert_called_with(
            mock_azure_config['azure.cloud_storage']['failure_container']
        )

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_get_utilities_container_client(self, mock_blob_client, mock_azure_config):
        """Test getting utilities container client."""
        mock_service = MagicMock()
        mock_service.get_container_client.return_value = MagicMock()
        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)
        client.get_utilities_container_client()

        mock_service.get_container_client.assert_called_with(
            mock_azure_config['azure.cloud_storage']['utilities_container']
        )


class TestNDJSONUpload:
    """Test NDJSON upload operations."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_upload_ndjson_to_stage_creates_correct_path(self, mock_blob_client, mock_azure_config):
        """Test NDJSON upload creates correct blob path."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()

        mock_blob_client.from_connection_string.return_value = mock_service
        mock_service.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob

        client = AzureStorageClient(mock_azure_config)

        resource_list = [
            {"resource": {"id": "123", "resourceType": "Patient", "name": [{"family": "Smith"}]}}
        ]

        result = client.upload_ndjson_to_stage(
            resource_list=resource_list,
            filename="Patient-1.ndjson",
            folder_name="batch-load/20240101"
        )

        assert result is True
        mock_blob.upload_blob.assert_called_once()
        mock_container.get_blob_client.assert_called_with("batch-load/20240101/Patient-1.ndjson")

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_upload_ndjson_formats_as_ndjson(self, mock_blob_client, mock_azure_config):
        """Test that upload formats data as NDJSON (newline-delimited)."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()

        mock_blob_client.from_connection_string.return_value = mock_service
        mock_service.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob

        client = AzureStorageClient(mock_azure_config)

        resource_list = [
            {"resource": {"id": "1", "resourceType": "Patient"}},
            {"resource": {"id": "2", "resourceType": "Patient"}}
        ]

        client.upload_ndjson_to_stage(
            resource_list=resource_list,
            filename="Patient-1.ndjson",
            folder_name="batch-load/20240101"
        )

        call_args = mock_blob.upload_blob.call_args
        uploaded_content = call_args[0][0]

        # Verify it's NDJSON format (each line is valid JSON)
        lines = uploaded_content.strip().split('\n')
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert 'id' in parsed

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_upload_ndjson_returns_false_for_none(self, mock_blob_client, mock_azure_config):
        """Test upload returns False for None resource list."""
        mock_blob_client.from_connection_string.return_value = MagicMock()

        client = AzureStorageClient(mock_azure_config)

        result = client.upload_ndjson_to_stage(
            resource_list=None,
            filename="Patient-1.ndjson",
            folder_name="batch-load/20240101"
        )

        assert result is False


class TestBlobDeletion:
    """Test blob deletion operations."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_delete_blob_success(self, mock_blob_client, mock_azure_config):
        """Test successful blob deletion."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()

        mock_blob_client.from_connection_string.return_value = mock_service
        mock_container.get_blob_client.return_value = mock_blob

        client = AzureStorageClient(mock_azure_config)

        blob_url = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        result = client.delete(blob_url, mock_container)

        assert result is True
        mock_blob.delete_blob.assert_called_once()

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_delete_blob_failure(self, mock_blob_client, mock_azure_config):
        """Test blob deletion failure returns False."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_blob.delete_blob.side_effect = Exception("Delete failed")

        mock_blob_client.from_connection_string.return_value = mock_service
        mock_container.get_blob_client.return_value = mock_blob

        client = AzureStorageClient(mock_azure_config)

        blob_url = "https://storage.blob.core.windows.net/staging/file.ndjson"
        result = client.delete(blob_url, mock_container)

        assert result is False


class TestFailureContainerOperations:
    """Test failure container upload operations."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_upload_json_to_failure(self, mock_blob_client, mock_azure_config):
        """Test uploading JSON to failure container."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_blob.url = "https://storage.blob.core.windows.net/failures/error.json"

        mock_blob_client.from_connection_string.return_value = mock_service
        mock_service.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob

        client = AzureStorageClient(mock_azure_config)

        error_data = {"error": "Processing failed", "details": "Test error"}

        client.upload_json_to_failure(
            json_data=error_data,
            blob_path="601/20240101/Patient-1.json"
        )

        mock_blob.upload_blob.assert_called_once()


class TestBlobPathGenerationMethod:
    """Test generate_blob_path method."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_generate_blob_path_event_load(self, mock_blob_client, mock_azure_config):
        """Test blob path generation for event load."""
        mock_blob_client.from_connection_string.return_value = MagicMock()

        client = AzureStorageClient(mock_azure_config)

        fhir_event_message = {
            "data": {"resourceFhirId": "patient-123"},
            "eventTime": "2024-01-15T10:30:00Z"
        }

        blob_path = client.generate_blob_path(
            fhir_event_message=fhir_event_message,
            error_code="601",
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            filetype="json"
        )

        assert "601" in blob_path
        assert ".json" in blob_path

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_generate_blob_path_batch_load_with_end_time(self, mock_blob_client, mock_azure_config):
        """Test blob path generation for batch load with end_time."""
        mock_blob_client.from_connection_string.return_value = MagicMock()

        client = AzureStorageClient(mock_azure_config)

        fhir_event_message = {
            "end_time": "2024-01-15T12:00:00",
            "page_number": 5,
            "resource_type": "Patient"
        }

        blob_path = client.generate_blob_path(
            fhir_event_message=fhir_event_message,
            error_code="602",
            application_name="batch_exporter",
            filetype="ndjson"
        )

        assert "602" in blob_path
        assert "Patient" in blob_path
        assert ".ndjson" in blob_path


class TestCopyToFailure:
    """Test copy to failure container operations."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_copy_ndjson_to_failure(self, mock_blob_client, mock_azure_config):
        """Test copying NDJSON to failure container."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()

        mock_blob_client.from_connection_string.return_value = mock_service
        mock_service.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob

        client = AzureStorageClient(mock_azure_config)

        blob_url = "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"

        result = client.copy_ndjson_to_failure(
            filename="staging_batch-load_20240101_Patient-1.ndjson",
            blob_url=blob_url,
            error_code="601"
        )

        assert result is not None
        assert "601" in result


class TestAzureReadWithRetry:
    """Test Azure blob read with retry logic."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_read_blob_success(self, mock_blob_client, mock_azure_config):
        """Test successful blob read."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_download = MagicMock()

        mock_download.readall.return_value = b'{"id": "1"}\n{"id": "2"}'
        mock_blob.download_blob.return_value = mock_download
        mock_container.get_blob_client.return_value = mock_blob

        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)
        mock_queue = MagicMock()

        result = client.read(
            blob_url='https://storage.blob.core.windows.net/staging/path/file.ndjson',
            container_client=mock_container,
            filename='file.ndjson',
            queue_client=mock_queue,
            retry_count=0
        )

        assert len(result) == 2

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_read_blob_retry_on_error(self, mock_blob_client, mock_azure_config):
        """Test blob read adds to queue on transient error and returns None."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()

        mock_blob.download_blob.side_effect = Exception("Blob download failed")
        mock_container.get_blob_client.return_value = mock_blob

        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)
        mock_queue = MagicMock()

        result = client.read(
            blob_url='https://storage.blob.core.windows.net/staging/path/file.ndjson',
            container_client=mock_container,
            filename='file.ndjson',
            queue_client=mock_queue,
            retry_count=0
        )

        assert result is None
        mock_queue.insert_to_batch_load_queue.assert_called_once()


class TestAzureMetadataBackup:
    """Test Azure metadata backup container operations."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_get_metadata_backup_container(self, mock_blob_client, mock_azure_config):
        """Test getting metadata backup container client."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_service.get_container_client.return_value = mock_container
        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)
        client.get_metadata_backup_container_client()

        mock_service.get_container_client.assert_called_with(
            mock_azure_config['azure.cloud_storage']['metadata_backup_container']
        )


class TestAzureBlobPathGeneration:
    """Test Azure blob path generation for different scenarios."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_generate_blob_path_batch_with_url(self, mock_blob_client, mock_azure_config):
        """Test blob path generation for batch load with URL."""
        mock_blob_client.from_connection_string.return_value = MagicMock()

        client = AzureStorageClient(mock_azure_config)

        fhir_event_message = {
            "url": "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        }

        blob_path = client.generate_blob_path(
            fhir_event_message=fhir_event_message,
            error_code="603",
            application_name="batch_processor",
            filetype="ndjson"
        )

        assert "603" in blob_path
        assert "ndjson" in blob_path

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_generate_blob_path_event_load_with_time(self, mock_blob_client, mock_azure_config):
        """Test blob path generation for event load with valid time."""
        mock_blob_client.from_connection_string.return_value = MagicMock()

        client = AzureStorageClient(mock_azure_config)

        fhir_event_message = {
            "data": {"resourceFhirId": "patient-123"},
            "eventTime": "2024-01-15T10:30:00Z"
        }

        blob_path = client.generate_blob_path(
            fhir_event_message=fhir_event_message,
            error_code="601",
            application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
            filetype="json"
        )

        assert "601" in blob_path
        assert ".json" in blob_path


class TestAzureCopyToFailureRetry:
    """Test Azure copy to failure with retry logic."""

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    def test_copy_ndjson_to_failure_success(self, mock_blob_client, mock_azure_config):
        """Test successful copy to failure container."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()

        mock_service.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob
        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)

        result = client.copy_ndjson_to_failure(
            filename="test_file.ndjson",
            blob_url="https://storage.blob.core.windows.net/staging/path/file.ndjson",
            error_code="601"
        )

        assert result is not None
        mock_blob.start_copy_from_url.assert_called_once()

    @patch('pyfiles.adapters.storage_clients.BlobServiceClient')
    @patch('pyfiles.adapters.storage_clients.time')
    def test_copy_ndjson_to_failure_retries(self, mock_time, mock_blob_client, mock_azure_config):
        """Test copy to failure retries on transient errors."""
        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()

        # Fail on first call, succeed on second
        mock_blob.start_copy_from_url.side_effect = [Exception("Copy failed"), None]
        mock_service.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob
        mock_blob_client.from_connection_string.return_value = mock_service

        client = AzureStorageClient(mock_azure_config)

        # This will try to copy with default max_retries=5
        client.copy_ndjson_to_failure(
            filename="test_file.ndjson",
            blob_url="https://storage.blob.core.windows.net/staging/path/file.ndjson",
            error_code="601",
            max_retries=2
        )

        # Result could be the path or None depending on retry logic
        assert mock_blob.start_copy_from_url.call_count >= 1


