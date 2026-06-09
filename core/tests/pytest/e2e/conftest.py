"""End-to-end test fixtures for complete pipeline testing."""
import pytest
import json
import pandas as pd
from datetime import datetime

from tests.pytest.mocks.mock_queue_client import MockAzureQueueClient, MockServiceBusMessage
from tests.pytest.mocks.mock_storage_client import MockAzureStorageClient
from tests.pytest.mocks.mock_db_pool import MockConnectionPool


@pytest.fixture
def e2e_azure_services(mock_azure_config):
    """Provide fully configured mock Azure services for E2E tests."""
    queue_client = MockAzureQueueClient(configurations=mock_azure_config)
    storage_client = MockAzureStorageClient()
    db_pool = MockConnectionPool()

    return {
        'queue_client': queue_client,
        'storage_client': storage_client,
        'db_pool': db_pool,
        'configurations': mock_azure_config
    }


@pytest.fixture
def complete_patient_bundle():
    """Provide a complete Patient resource bundle for E2E testing."""
    return [
        {
            "resourceType": "Patient",
            "id": "e2e-patient-001",
            "meta": {
                "versionId": "1",
                "lastUpdated": "2024-01-15T10:00:00Z",
                "source": "urn:TestSource"
            },
            "identifier": [
                {"system": "http://hospital.org/mrn", "value": "MRN001"},
                {"system": "urn:Source", "value": "TestSource"},
                {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "123-45-6789"}
            ],
            "name": [
                {
                    "use": "official",
                    "family": "TestFamily",
                    "given": ["TestGiven", "MiddleName"]
                }
            ],
            "gender": "male",
            "birthDate": "1980-01-15",
            "address": [
                {
                    "use": "home",
                    "line": ["123 Test Street"],
                    "city": "TestCity",
                    "state": "TS",
                    "postalCode": "12345",
                    "country": "US"
                }
            ],
            "telecom": [
                {"system": "phone", "value": "555-123-4567", "use": "home"},
                {"system": "email", "value": "test@example.com"}
            ]
        },
        {
            "resourceType": "Patient",
            "id": "e2e-patient-002",
            "meta": {
                "versionId": "1",
                "lastUpdated": "2024-01-15T10:01:00Z"
            },
            "identifier": [
                {"system": "urn:Source", "value": "TestSource"}
            ],
            "name": [{"family": "AnotherPatient", "given": ["Jane"]}],
            "gender": "female",
            "birthDate": "1990-06-20"
        }
    ]


@pytest.fixture
def complete_observation_bundle():
    """Provide a complete Observation resource bundle for E2E testing."""
    return [
        {
            "resourceType": "Observation",
            "id": "e2e-obs-001",
            "meta": {
                "versionId": "1",
                "lastUpdated": "2024-01-15T11:00:00Z"
            },
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "vital-signs"
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "8867-4",
                        "display": "Heart rate"
                    }
                ]
            },
            "subject": {"reference": "Patient/e2e-patient-001"},
            "effectiveDateTime": "2024-01-15T10:30:00Z",
            "valueQuantity": {
                "value": 72,
                "unit": "beats/minute",
                "system": "http://unitsofmeasure.org",
                "code": "/min"
            }
        }
    ]


@pytest.fixture
def mixed_resource_bundle(complete_patient_bundle, complete_observation_bundle):
    """Provide a mixed resource bundle for batch testing."""
    return {
        'Patient': complete_patient_bundle,
        'Observation': complete_observation_bundle
    }


@pytest.fixture
def e2e_message_factory():
    """Factory for creating E2E test messages."""
    def create_message(resource_type, filename, folder="batch-load/20240115"):
        message_body = {
            "url": f"https://test.blob.core.windows.net/staging/{folder}/{filename}",
            "request_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "retry_count": 0
        }
        return MockServiceBusMessage(json.dumps(message_body))

    return create_message


@pytest.fixture
def mock_normalizer_factory():
    """Factory for creating mock normalizer results."""
    def create_normalizer_result(resource_type, records):
        if resource_type == 'Patient':
            return {
                'patient': pd.DataFrame({
                    'id': [r['id'] for r in records],
                    'name_family': [r.get('name', [{}])[0].get('family', '') for r in records],
                    'gender': [r.get('gender', '') for r in records],
                    'birthdate': [r.get('birthDate', '') for r in records],
                    'meta_versionid': [r.get('meta', {}).get('versionId', '1') for r in records],
                    'meta_lastupdated': [r.get('meta', {}).get('lastUpdated', '') for r in records]
                }),
                'identifier_source': pd.DataFrame({
                    'id': [r['id'] for r in records],
                    'identifier_source': ['TestSource' for _ in records]
                })
            }
        elif resource_type == 'Observation':
            return {
                'measurement': pd.DataFrame({
                    'id': [r['id'] for r in records],
                    'status': [r.get('status', '') for r in records],
                    'subject_reference': [r.get('subject', {}).get('reference', '') for r in records],
                    'value_quantity_value': [r.get('valueQuantity', {}).get('value') for r in records]
                })
            }
        return {}

    return create_normalizer_result


@pytest.fixture
def e2e_config(mock_azure_config):
    """Extended configuration for E2E tests with all features enabled."""
    config = mock_azure_config.copy()
    config['default_value']['is_audit'] = 'True'
    config['default_value']['is_lineage'] = 'True'
    config['silver_layer']['is_transaction'] = 'True'
    config['processing']['message'] = '1'
    config['processing']['converter_cores'] = '1'
    return config
