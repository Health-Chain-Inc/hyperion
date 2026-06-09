"""Shared pytest fixtures for all tests."""
import pytest
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# pytest/ directory (where conftest.py and test_data live)
PYTEST_DIR = Path(__file__).parent


# ============== Path Fixtures ==============

@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir():
    """Return the test_data directory."""
    return PYTEST_DIR / "test_data"


@pytest.fixture(scope="session")
def schema_dir(project_root):
    """Return the schema directory."""
    return project_root / "schema"


# ============== Schema Fixtures ==============

@pytest.fixture(scope="session")
def fhir_schema(schema_dir):
    """Load the FHIR schema (cached for session)."""
    with open(schema_dir / "fhir.schema.json", "r", encoding="utf-8") as f:
        return json.load(f)


# ============== Sample Data Fixtures ==============

@pytest.fixture
def sample_patient_ndjson(test_data_dir):
    """Load sample Patient NDJSON data."""
    with open(test_data_dir / "Patient-1.ndjson", "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture
def sample_diagnostic_report_ndjson(test_data_dir):
    """Load sample DiagnosticReport NDJSON data."""
    with open(test_data_dir / "DiagnosticReport-1.ndjson", "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture
def sample_procedure_ndjson(test_data_dir):
    """Load sample Procedure NDJSON data."""
    with open(test_data_dir / "Procedure-1.ndjson", "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture
def sample_patient_json(test_data_dir):
    """Load sample Patient JSON data."""
    with open(test_data_dir / "Patient.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_observation_json(test_data_dir):
    """Load sample Observation JSON data."""
    with open(test_data_dir / "Observation.json", "r", encoding="utf-8") as f:
        return json.load(f)


# ============== Configuration Fixtures ==============

@pytest.fixture
def mock_azure_config():
    """Return a mock Azure configuration."""
    return {
        'application': {'name': 'test-app'},
        'initialization': {
            'cloud_storage': 'azure',
            'servicebus': 'azure',
            'fhir_service': 'azure'
        },
        'schema': {
            'hl7_file_name': 'schema/fhir.schema.json'
        },
        'default_value': {
            'meta_source': 'test-source',
            'is_audit': 'False',
            'is_lineage': 'False',
            'delay_time': '5'
        },
        'silver_layer': {
            'username': 'test_user',
            'password': 'test_password',
            'query_server': 'localhost:9030',
            'http_server': 'localhost:8030',
            'catalog': 'default_catalog',
            'core_database': 'test_core_db',
            'audit_database': 'test_audit_db',
            'is_transaction': 'False'
        },
        'pools': {'database': '5'},
        'processing': {
            'message': '1',
            'converter_cores': '2',
            'audit_batch_size': '50',
            'audit_flush_interval': '3.0'
        },
        'FHIR': {
            'max_retry_count': '3',
            'ndjson_file_size': '100'
        },
        'azure.servicebus': {
            'connection_string': 'Endpoint=sb://test.servicebus.windows.net/;SharedAccessKeyName=test;SharedAccessKey=dGVzdA==',
            'core_topic': 'test-topic',
            'core_processor_subscription': 'test-sub',
            'eventload_queue_name': 'test-eventload',
            'audit_queue_name': 'test-audit',
            'retry_queue_name': 'test-retry',
            'batch_parameter_queue_name': 'test-params'
        },
        'azure.cloud_storage': {
            'connection_string': 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net',
            'baseurl': 'https://test.blob.core.windows.net/',
            'ndjson_stage_container': 'staging',
            'failure_container': 'failures',
            'utilities_container': 'utilities',
            'metadata_backup_container': 'backup'
        },
        'azure.fhir': {
            'server_url': 'https://test-fhir.azurehealthcareapis.com',
            'client_id': 'test-client-id',
            'client_secret': 'test-client-secret',
            'scope': 'https://test-fhir.azurehealthcareapis.com/.default',
            'grant_type': 'client_credentials',
            'token_url': 'https://login.microsoftonline.com/test-tenant/oauth2/v2.0/token'
        }
    }



# ============== FHIR Data Fixtures ==============

@pytest.fixture
def sample_fhir_patient():
    """Return a sample FHIR Patient resource."""
    return {
        "resourceType": "Patient",
        "id": "test-patient-123",
        "meta": {
            "versionId": "1",
            "lastUpdated": "2024-01-15T10:30:00Z"
        },
        "identifier": [
            {
                "system": "http://hospital.org/mrn",
                "value": "MRN12345"
            },
            {
                "system": "urn:Source",
                "value": "TestSource"
            }
        ],
        "name": [
            {
                "use": "official",
                "family": "Smith",
                "given": ["John", "Michael"]
            }
        ],
        "gender": "male",
        "birthDate": "1990-05-15",
        "address": [
            {
                "use": "home",
                "line": ["123 Main St", "Apt 4B"],
                "city": "New York",
                "state": "NY",
                "postalCode": "10001",
                "country": "US"
            }
        ],
        "telecom": [
            {
                "system": "phone",
                "value": "+1-555-123-4567",
                "use": "home"
            }
        ],
        "maritalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
                    "code": "M",
                    "display": "Married"
                }
            ]
        }
    }


@pytest.fixture
def sample_fhir_observation():
    """Return a sample FHIR Observation resource."""
    return {
        "resourceType": "Observation",
        "id": "test-obs-456",
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
                        "code": "vital-signs",
                        "display": "Vital Signs"
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
            ],
            "text": "Heart rate"
        },
        "subject": {
            "reference": "Patient/test-patient-123"
        },
        "effectiveDateTime": "2024-01-15T10:00:00Z",
        "valueQuantity": {
            "value": 72,
            "unit": "beats/minute",
            "system": "http://unitsofmeasure.org",
            "code": "/min"
        }
    }


# ============== DataFrame Fixtures ==============

@pytest.fixture
def sample_patient_dataframe(sample_fhir_patient):
    """Create a DataFrame from sample patient data."""
    import pandas as pd
    return pd.DataFrame([sample_fhir_patient])


@pytest.fixture
def sample_observation_dataframe(sample_fhir_observation):
    """Create a DataFrame from sample observation data."""
    import pandas as pd
    return pd.DataFrame([sample_fhir_observation])
