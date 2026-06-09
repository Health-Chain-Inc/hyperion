"""Integration test fixtures for multi-component testing."""
import pytest
import json
import pandas as pd
from unittest.mock import MagicMock, patch

from tests.pytest.mocks.mock_queue_client import MockAzureQueueClient, MockServiceBusMessage
from tests.pytest.mocks.mock_storage_client import MockAzureStorageClient
from tests.pytest.mocks.mock_db_pool import MockConnectionPool


@pytest.fixture
def mock_azure_services(mock_azure_config):
    """Provide mocked Azure services for integration tests."""
    return {
        'queue_client': MockAzureQueueClient(configurations=mock_azure_config),
        'storage_client': MockAzureStorageClient(),
        'db_pool': MockConnectionPool()
    }


@pytest.fixture
def sample_ndjson_content():
    """Provide sample NDJSON content for processing."""
    return '\n'.join([
        json.dumps({
            "resourceType": "Patient",
            "id": "p1",
            "meta": {"versionId": "1", "lastUpdated": "2024-01-15T10:00:00Z"},
            "identifier": [{"system": "urn:Source", "value": "TestSource"}],
            "name": [{"family": "Smith", "given": ["John"]}]
        }),
        json.dumps({
            "resourceType": "Patient",
            "id": "p2",
            "meta": {"versionId": "1", "lastUpdated": "2024-01-15T10:01:00Z"},
            "identifier": [{"system": "urn:Source", "value": "TestSource"}],
            "name": [{"family": "Doe", "given": ["Jane"]}]
        })
    ])


@pytest.fixture
def sample_observation_ndjson_content():
    """Provide sample Observation NDJSON content for processing."""
    return '\n'.join([
        json.dumps({
            "resourceType": "Observation",
            "id": "obs1",
            "meta": {"versionId": "1", "lastUpdated": "2024-01-15T11:00:00Z"},
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
            "subject": {"reference": "Patient/p1"},
            "valueQuantity": {"value": 72, "unit": "beats/minute"}
        })
    ])


@pytest.fixture
def sample_queue_message():
    """Provide a sample queue message for batch load."""
    message_body = {
        "url": "https://test.blob.core.windows.net/staging/batch-load/20240115/Patient-1.ndjson",
        "request_time": "2024-01-15T10:00:00Z",
        "retry_count": 0
    }
    return MockServiceBusMessage(json.dumps(message_body))


@pytest.fixture
def sample_event_message():
    """Provide a sample queue message for event load."""
    message_body = {
        "url": "https://test.blob.core.windows.net/staging/event-load/20240115/Patient-p1.ndjson",
        "request_time": "2024-01-15T10:00:00Z",
        "retry_count": 0,
        "resource_id": "p1",
        "event_load_is_update": False
    }
    return MockServiceBusMessage(json.dumps(message_body))


@pytest.fixture
def configured_processor(mock_azure_services, mock_azure_config):
    """Create a CoreLoadProcessor with mocked dependencies."""
    with patch('pyfiles.hyperion_core.core_load_processor.Handlers.json_reader') as mock_json_reader:
        with patch('pyfiles.hyperion_core.core_load_processor.Handlers.get_schema_file') as mock_get_schema:
            mock_get_schema.return_value = {
                'Patient': {'fields': []},
                'Observation': {'fields': []}
            }
            mock_json_reader.return_value = {
                'Patient': ['identifier'],
                'Observation': ['code']
            }

            from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor

            processor = CoreLoadProcessor(
                queue_client=mock_azure_services['queue_client'],
                storage_client=mock_azure_services['storage_client'],
                fhir_client=MagicMock(),
                project_configurations=mock_azure_config,
                db_connection_pool=mock_azure_services['db_pool']
            )

            yield processor


@pytest.fixture
def mock_normalizer_result():
    """Provide a mock normalizer result."""
    return {
        'patient': pd.DataFrame({
            'id': ['p1', 'p2'],
            'name_family': ['Smith', 'Doe'],
            'name_given': [['John'], ['Jane']],
            'meta_versionid': ['1', '1'],
            'meta_lastupdated': ['2024-01-15T10:00:00Z', '2024-01-15T10:01:00Z']
        }),
        'identifier_source': pd.DataFrame({
            'id': ['p1', 'p2'],
            'identifier_system': ['urn:Source', 'urn:Source'],
            'identifier_value': ['TestSource', 'TestSource']
        })
    }


@pytest.fixture
def mock_filter_result(sample_fhir_patient):
    """Provide a mock filter_data_to_be_processed result."""
    return (
        True,  # process_data
        pd.DataFrame([sample_fhir_patient]),  # fhir_data_df
        pd.DataFrame({
            'id': ['test-patient-123'],
            'identifier_max_array_size_db': [2],
            'codeableconcept_max_array_size_db': [1],
            'reference_max_array_size_db': [0]
        }),  # array_counts_df
        [{
            'filepath_id': 'batch-load/20240115/Patient-1.ndjson',
            'resource_type': 'Patient',
            'record_count': 1,
            'operation': 'new'
        }]  # audit_data_json
    )


@pytest.fixture
def integration_config(mock_azure_config):
    """Extended configuration for integration tests."""
    config = mock_azure_config.copy()
    config['default_value']['is_audit'] = 'True'
    config['default_value']['is_lineage'] = 'True'
    config['silver_layer']['is_transaction'] = 'True'
    return config


@pytest.fixture
def mock_transaction_manager():
    """Provide mocked TransactionManager for integration tests."""
    with patch('pyfiles.hyperion_core.core_load_processor.TransactionManager') as mock_tm:
        mock_tm.transaction_block.return_value = (True, 'tx-label-123', 'patient')
        mock_tm.commit_transaction.return_value = None
        mock_tm.rollback_transaction.return_value = None
        yield mock_tm


@pytest.fixture
def mock_db_ops():
    """Provide mocked DBOps for integration tests."""
    with patch('pyfiles.hyperion_core.core_load_processor.DBOps') as mock_db:
        mock_db.filter_data_to_be_processed.return_value = (
            True,
            pd.DataFrame(),
            pd.DataFrame(),
            [{'filepath_id': 'test'}]
        )
        yield mock_db


@pytest.fixture
def mock_df_ops():
    """Provide mocked DFOps for integration tests."""
    with patch('pyfiles.hyperion_core.core_load_processor.DFOps') as mock_df:
        mock_df.create_pandas_dataframe.return_value = pd.DataFrame()
        mock_df.process_dataframe.return_value = pd.DataFrame({'id': ['test-1']})
        mock_df.rename_column.return_value = None
        yield mock_df
