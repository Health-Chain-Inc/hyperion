"""Unit tests for adapter interface ABCs in pyfiles.adapters.interface.

These ABCs define the contract every cloud adapter must satisfy. The tests
below pin the abstract method set so that:
1. A new concrete adapter (e.g. AWS, GCP) knows exactly what to implement.
2. Renaming or removing a method on the ABC fails CI loudly rather than
   silently leaving subclasses to drift.
3. The Azure / local adapters already implemented can be smoke-instantiated
   against the ABC contract.
"""
import inspect
import pytest

from pyfiles.adapters.interface import (
    FHIRServerClient,
    ServiceBusMessageQueueClient,
    StorageClient,
)


def _abstract_method_names(cls):
    """Return the set of abstract method names declared on ``cls``."""
    return set(getattr(cls, "__abstractmethods__", set()))


class TestServiceBusMessageQueueClientAbc:
    def test_is_abstract_base_class(self):
        with pytest.raises(TypeError):
            ServiceBusMessageQueueClient()  # cannot instantiate ABC directly

    def test_abstract_methods_pinned(self):
        """The full abstract surface; new entries require a deliberate update."""
        expected = {
            "get_batch_queue_receiver",
            "get_event_queue_receiver",
            "get_parameter_queue_receiver",
            "get_parameter_queue_sender",
            "get_audit_queue_receiver",
            "get_retry_queue_receiver",
            "receive_messages",
            "read_message_body",
            "complete_message",
            "get_ndjson_filepath",
            "send_single_message",
            "send_scheduled_single_message",
            "insert_to_reject_queue",
            "insert_to_audit_queue",
            "insert_to_event_load_queue",
            "insert_to_batch_load_queue",
            "insert_to_fhir_parameter_queue",
            "get_context_safe_client",
            "get_context_safe_receiver",
        }
        assert _abstract_method_names(ServiceBusMessageQueueClient) == expected

    def test_subclass_must_implement_all_methods(self):
        class Incomplete(ServiceBusMessageQueueClient):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_azure_queue_client_satisfies_contract(self):
        from pyfiles.adapters.queue_clients import AzureQueueClient
        assert issubclass(AzureQueueClient, ServiceBusMessageQueueClient)


class TestFhirServerClientAbc:
    def test_is_abstract_base_class(self):
        with pytest.raises(TypeError):
            FHIRServerClient()

    def test_abstract_methods_pinned(self):
        expected = {
            "get_fhir_batch_export_url",
            "get_fhir_event_export_url",
            "check_if_update",
            "authentication",
            "fhir_connectivity_check",
            "fhir_get_request",
        }
        assert _abstract_method_names(FHIRServerClient) == expected

    def test_subclass_must_implement_all_methods(self):
        class Incomplete(FHIRServerClient):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_azure_fhir_client_satisfies_contract(self):
        from pyfiles.adapters.fhir_clients import AzureFHIRClient
        assert issubclass(AzureFHIRClient, FHIRServerClient)

    def test_hapi_fhir_client_satisfies_contract(self):
        """HapiFhirClient was added in the OSS cleanup — verify it implements the ABC."""
        from pyfiles.adapters.fhir_clients import HapiFhirClient
        assert issubclass(HapiFhirClient, FHIRServerClient)


class TestStorageClientAbc:
    def test_is_abstract_base_class(self):
        with pytest.raises(TypeError):
            StorageClient()

    def test_abstract_methods_pinned(self):
        expected = {
            "generate_blob_path",
            "get_staging_container_client",
            "get_failure_container_client",
            "get_utilities_container_client",
            "get_metadata_backup_container_client",
            "read",
            "delete",
            "upload_json_to_failure",
            "upload_ndjson_to_stage",
        }
        assert _abstract_method_names(StorageClient) == expected

    def test_subclass_must_implement_all_methods(self):
        class Incomplete(StorageClient):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_azure_storage_client_satisfies_contract(self):
        from pyfiles.adapters.storage_clients import AzureStorageClient
        assert issubclass(AzureStorageClient, StorageClient)


class TestInterfaceMethodSignatures:
    """Method-signature smoke tests — useful when adding a new cloud adapter,
    so the contract is discoverable from the test file alone."""

    def test_receive_messages_signature(self):
        sig = inspect.signature(ServiceBusMessageQueueClient.receive_messages)
        params = list(sig.parameters.keys())
        assert params == ["self", "receiver", "max_message_count", "max_wait_time"]

    def test_get_fhir_batch_export_url_signature(self):
        sig = inspect.signature(FHIRServerClient.get_fhir_batch_export_url)
        params = list(sig.parameters.keys())
        assert params == ["self", "fhir_resource", "start_date", "end_date"]

    def test_generate_blob_path_signature(self):
        sig = inspect.signature(StorageClient.generate_blob_path)
        params = list(sig.parameters.keys())
        assert params == ["self", "fhir_event_message", "error_code", "application_name", "filetype"]
