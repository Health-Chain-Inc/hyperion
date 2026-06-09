"""Mock implementations for Azure Blob Storage client."""
import json
from typing import Dict, List, Optional


class MockBlobClient:
    """Mock Azure Blob client."""

    def __init__(self, container_name: str, blob_name: str, data: bytes = b''):
        self.container_name = container_name
        self.blob_name = blob_name
        self._data = data
        self._exists = True
        self.url = f"https://test.blob.core.windows.net/{container_name}/{blob_name}"

    def exists(self) -> bool:
        return self._exists

    def download_blob(self):
        return MockStorageStreamDownloader(self._data)

    def upload_blob(self, data, overwrite: bool = False):
        self._data = data if isinstance(data, bytes) else data.encode()
        return {"etag": "mock-etag"}

    def delete_blob(self):
        self._exists = False
        return True

    def start_copy_from_url(self, source_url: str):
        return {"copy_status": "success"}


class MockStorageStreamDownloader:
    """Mock for Azure Storage stream downloader."""

    def __init__(self, data: bytes):
        self._data = data

    def readall(self) -> bytes:
        return self._data

    def content_as_text(self) -> str:
        return self._data.decode('utf-8')


class MockContainerClient:
    """Mock Azure Container client."""

    def __init__(self, container_name: str, blobs: Optional[Dict[str, bytes]] = None):
        self.container_name = container_name
        self._blobs = blobs or {}

    def list_blobs(self, name_starts_with: str = None):
        """List blobs with optional prefix filter."""
        for blob_name, _data in self._blobs.items():
            if name_starts_with is None or blob_name.startswith(name_starts_with):
                yield MockBlobProperties(blob_name)

    def get_blob_client(self, blob: str = None, blob_name: str = None):
        name = blob or blob_name
        data = self._blobs.get(name, b'')
        return MockBlobClient(self.container_name, name, data)


class MockBlobProperties:
    """Mock blob properties."""

    def __init__(self, name: str):
        self.name = name


class MockBlobServiceClient:
    """Mock Azure BlobServiceClient."""

    def __init__(self, containers: Optional[Dict[str, Dict[str, bytes]]] = None):
        self._containers = containers or {}

    @classmethod
    def from_connection_string(cls, conn_str: str, retry_policy=None):
        """Create mock client from connection string."""
        return cls()

    def get_container_client(self, container_name: str):
        blobs = self._containers.get(container_name, {})
        return MockContainerClient(container_name, blobs)


class MockAzureStorageClient:
    """Mock implementation of AzureStorageClient for testing."""

    def __init__(self, containers: Optional[Dict[str, Dict[str, bytes]]] = None):
        self._containers = containers or {}
        self.uploaded_blobs = []
        self.deleted_blobs = []
        self.copied_blobs = []

    def get_staging_container_client(self):
        return MockContainerClient('staging', self._containers.get('staging', {}))

    def get_failure_container_client(self):
        return MockContainerClient('failures', self._containers.get('failures', {}))

    def get_utilities_container_client(self):
        return MockContainerClient('utilities', self._containers.get('utilities', {}))

    def get_metadata_backup_container_client(self):
        return MockContainerClient('backup', self._containers.get('backup', {}))

    def upload_ndjson_to_stage(self, resource_list: List[Dict], filename: str, folder_name: str) -> bool:
        """Record uploaded NDJSON."""
        if resource_list is None:
            return False
        ndjson_content = '\n'.join(json.dumps(r.get('resource', r)) for r in resource_list)
        self.uploaded_blobs.append({
            'container': 'staging',
            'path': f"{folder_name}/{filename}",
            'content': ndjson_content
        })
        return True

    def upload_json_to_failure(self, json_data: dict, blob_path: str) -> bool:
        """Record failure upload."""
        self.uploaded_blobs.append({
            'container': 'failures',
            'path': blob_path,
            'content': json.dumps(json_data)
        })
        return True

    def copy_ndjson_to_failure(self, filename: str, blob_url: str, error_code: str, max_retries: int = 5, sleep_duration: int = 6) -> str:
        """Record blob copy to failure container."""
        blob_path = "/".join(blob_url.split("/")[4:])
        destination_path = f"{error_code}/{blob_path}"
        self.copied_blobs.append({
            'source_url': blob_url,
            'destination': destination_path
        })
        return destination_path

    def read(self, blob_url: str, container_client, filename: str, queue_client, retry_count: int) -> List[Dict]:
        """Return mock NDJSON data."""
        return [{"id": "mock-1", "resourceType": "Patient"}]

    def delete(self, blob_url: str, container_client) -> bool:
        """Record blob deletion."""
        self.deleted_blobs.append({'url': blob_url})
        return True

    def generate_blob_path(self, fhir_event_message: dict, error_code: str, application_name: str, filetype: str) -> str:
        """Generate a blob path for the message."""
        return f"{error_code}/20240101T120000/Patient-1.{filetype}"
