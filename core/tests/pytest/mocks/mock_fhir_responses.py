"""Mock implementations for FHIR REST API responses."""
import json
from typing import Dict, List, Optional, Any
from datetime import datetime


class MockFHIRResponse:
    """Mock HTTP response from FHIR server."""

    def __init__(self, status_code: int = 200, data: Optional[Dict] = None,
                 text: str = None, headers: Optional[Dict] = None):
        self.status_code = status_code
        self._data = data or {}
        self._text = text
        self.headers = headers or {}

    def json(self):
        return self._data

    @property
    def text(self):
        if self._text:
            return self._text
        return json.dumps(self._data)


class MockFHIRSession:
    """Mock requests.Session for FHIR API calls."""

    def __init__(self, responses: Optional[List[MockFHIRResponse]] = None):
        self._responses = responses or [MockFHIRResponse()]
        self._call_index = 0
        self.get_calls = []
        self.post_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def get(self, url: str, headers: Dict = None, timeout: int = None):
        self.get_calls.append({
            'url': url,
            'headers': headers,
            'timeout': timeout
        })

        if self._call_index < len(self._responses):
            response = self._responses[self._call_index]
            self._call_index += 1
            return response
        return self._responses[-1] if self._responses else MockFHIRResponse()

    def post(self, url: str, headers: Dict = None, data: Any = None,
             timeout: int = None):
        self.post_calls.append({
            'url': url,
            'headers': headers,
            'data': data,
            'timeout': timeout
        })
        if self._call_index < len(self._responses):
            response = self._responses[self._call_index]
            self._call_index += 1
            return response
        return self._responses[-1] if self._responses else MockFHIRResponse()


def create_mock_oauth_response(access_token: str = "mock-access-token-12345",
                               expires_in: int = 3600):
    """Create a mock OAuth token response."""
    return MockFHIRResponse(
        status_code=200,
        data={
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': expires_in
        }
    )


def create_mock_patient_bundle(count: int = 2, has_next: bool = False,
                               next_url: str = None):
    """Create a mock FHIR Patient Bundle response."""
    entries = []
    for i in range(count):
        entries.append({
            'resource': {
                'resourceType': 'Patient',
                'id': f'patient-{i+1}',
                'meta': {
                    'versionId': '1',
                    'lastUpdated': datetime.now().isoformat() + 'Z'
                },
                'identifier': [
                    {
                        'system': 'http://hospital.org/mrn',
                        'value': f'MRN{1000+i}'
                    }
                ],
                'name': [
                    {
                        'family': f'TestFamily{i+1}',
                        'given': [f'TestGiven{i+1}']
                    }
                ],
                'gender': 'male' if i % 2 == 0 else 'female',
                'birthDate': f'199{i}-01-15'
            }
        })

    bundle = {
        'resourceType': 'Bundle',
        'type': 'searchset',
        'total': count,
        'entry': entries
    }

    if has_next and next_url:
        bundle['link'] = [
            {'relation': 'next', 'url': next_url}
        ]

    return MockFHIRResponse(status_code=200, data=bundle)


def create_mock_observation_bundle(count: int = 2, has_next: bool = False,
                                   next_url: str = None):
    """Create a mock FHIR Observation Bundle response."""
    entries = []
    for i in range(count):
        entries.append({
            'resource': {
                'resourceType': 'Observation',
                'id': f'obs-{i+1}',
                'meta': {
                    'versionId': '1',
                    'lastUpdated': datetime.now().isoformat() + 'Z'
                },
                'status': 'final',
                'category': [
                    {
                        'coding': [
                            {
                                'system': 'http://terminology.hl7.org/CodeSystem/observation-category',
                                'code': 'vital-signs'
                            }
                        ]
                    }
                ],
                'code': {
                    'coding': [
                        {
                            'system': 'http://loinc.org',
                            'code': '8867-4',
                            'display': 'Heart rate'
                        }
                    ]
                },
                'subject': {
                    'reference': f'Patient/patient-{i+1}'
                },
                'valueQuantity': {
                    'value': 72 + i,
                    'unit': 'beats/minute'
                }
            }
        })

    bundle = {
        'resourceType': 'Bundle',
        'type': 'searchset',
        'total': count,
        'entry': entries
    }

    if has_next and next_url:
        bundle['link'] = [
            {'relation': 'next', 'url': next_url}
        ]

    return MockFHIRResponse(status_code=200, data=bundle)


def create_mock_single_patient(patient_id: str = "patient-123"):
    """Create a mock single Patient resource response."""
    return MockFHIRResponse(
        status_code=200,
        data={
            'resourceType': 'Patient',
            'id': patient_id,
            'meta': {
                'versionId': '1',
                'lastUpdated': datetime.now().isoformat() + 'Z'
            },
            'identifier': [
                {
                    'system': 'http://hospital.org/mrn',
                    'value': 'MRN12345'
                }
            ],
            'name': [
                {
                    'family': 'Smith',
                    'given': ['John']
                }
            ],
            'gender': 'male',
            'birthDate': '1990-01-15'
        }
    )


def create_mock_capability_statement():
    """Create a mock FHIR CapabilityStatement response."""
    return MockFHIRResponse(
        status_code=200,
        data={
            'resourceType': 'CapabilityStatement',
            'status': 'active',
            'fhirVersion': '4.0.1',
            'format': ['json', 'xml'],
            'rest': [
                {
                    'mode': 'server',
                    'resource': [
                        {'type': 'Patient'},
                        {'type': 'Observation'},
                        {'type': 'Condition'}
                    ]
                }
            ]
        }
    )


def create_mock_error_response(status_code: int = 500,
                               error_message: str = "Internal Server Error"):
    """Create a mock error response."""
    return MockFHIRResponse(
        status_code=status_code,
        data={
            'resourceType': 'OperationOutcome',
            'issue': [
                {
                    'severity': 'error',
                    'code': 'exception',
                    'diagnostics': error_message
                }
            ]
        }
    )


def create_mock_event_message(resource_type: str = "Patient",
                              resource_id: str = "patient-123",
                              action: str = "create"):
    """Create a mock FHIR event message."""
    return {
        'resourceType': resource_type,
        'id': resource_id,
        'action': action,
        'timestamp': datetime.now().isoformat() + 'Z'
    }


def create_mock_batch_parameter_message(resource_type: str = "Patient",
                                        start_time: str = None,
                                        end_time: str = None,
                                        folder_name: str = None):
    """Create a mock batch export parameter message."""
    if start_time is None:
        start_time = "2024-01-01T00:00:00Z"
    if end_time is None:
        end_time = "2024-01-02T00:00:00Z"
    if folder_name is None:
        folder_name = f"batch-load/{datetime.now().strftime('%Y%m%d')}"

    return {
        'resource_type': resource_type,
        'start_time': start_time,
        'end_time': end_time,
        'fhir_url': None,
        'page_number': 1,
        'folder_name': folder_name,
        'retry_count': 0,
        'retry_message': False
    }


class MockFHIRClient:
    """Mock implementation of FHIR client for testing."""

    def __init__(self, server_url: str = "https://test-fhir.azurehealthcareapis.com"):
        self.server_url = server_url
        self.auth_calls = []
        self.get_calls = []

    def authentication(self):
        """Return mock authentication headers."""
        self.auth_calls.append(datetime.now())
        return {
            'Authorization': 'Bearer mock-access-token-12345',
            'Content-Type': 'application/fhir+json'
        }

    def fhir_connectivity_check(self):
        """Mock connectivity check."""
        return True

    def get_fhir_batch_export_url(self, resource_type: str, start_date: str, end_date: str):
        """Generate mock batch export URL."""
        base_url = f"{self.server_url}/{resource_type}"
        params = []
        if start_date:
            params.append(f"_lastUpdated=ge{start_date}")
        if end_date:
            params.append(f"_lastUpdated=lt{end_date}")
        if params:
            return f"{base_url}?{'&'.join(params)}"
        return base_url

    def get_fhir_event_export_url(self, fhir_event_dict: Dict):
        """Generate mock event export URL."""
        resource_type = fhir_event_dict.get('resourceType', 'Patient')
        resource_id = fhir_event_dict.get('id', 'unknown')
        return resource_type, f"{self.server_url}/{resource_type}/{resource_id}"

    def check_if_update(self, fhir_event_dict: Dict):
        """Check if event is an update."""
        return fhir_event_dict.get('action', 'create') == 'update'

    def fhir_get_request(self, session, url: str, headers: Dict, timeout: int):
        """Mock FHIR GET request."""
        self.get_calls.append({'url': url, 'headers': headers})
        # Return a successful patient bundle by default
        return create_mock_patient_bundle(count=2)
