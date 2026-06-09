"""Unit tests for AzureFHIRClient."""
import pytest
import responses

from pyfiles.adapters.fhir_clients import AzureFHIRClient


class TestAzureFHIRClientInitialization:
    """Test FHIR client initialization."""

    def test_client_initializes_with_config(self, mock_azure_config):
        """Test that client initializes and stores config values."""
        client = AzureFHIRClient(mock_azure_config)

        assert client.project_configurations == mock_azure_config
        assert client.session is not None


class TestBatchExportURLGeneration:
    """Test batch export URL generation."""

    def test_get_fhir_batch_export_url(self, mock_azure_config):
        """Test generating batch export URL."""
        client = AzureFHIRClient(mock_azure_config)

        url = client.get_fhir_batch_export_url(
            fhir_resource="Patient",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-15T00:00:00Z"
        )

        assert mock_azure_config['azure.fhir']['server_url'] in url
        assert 'Patient' in url
        assert '_lastUpdated=ge2024-01-01T00:00:00Z' in url
        assert '_lastUpdated=le2024-01-15T00:00:00Z' in url
        assert f"_count={mock_azure_config['FHIR']['ndjson_file_size']}" in url

    def test_get_fhir_batch_export_url_observation(self, mock_azure_config):
        """Test batch export URL for Observation resource."""
        client = AzureFHIRClient(mock_azure_config)

        url = client.get_fhir_batch_export_url(
            fhir_resource="Observation",
            start_date="2024-01-01T00:00:00Z",
            end_date="2024-01-31T23:59:59Z"
        )

        assert 'Observation' in url


class TestEventExportURLGeneration:
    """Test event export URL generation."""

    def test_get_fhir_event_export_url(self, mock_azure_config):
        """Test generating event export URL."""
        client = AzureFHIRClient(mock_azure_config)

        fhir_event = {
            "subject": "fhir.azurehealthcareapis.com/Patient/patient-123"
        }

        resource_type, url = client.get_fhir_event_export_url(fhir_event)

        assert resource_type == "Patient"
        assert "Patient/patient-123" in url
        assert url.startswith("https://")


class TestCheckIfUpdate:
    """Test update event detection."""

    def test_check_if_update_true(self, mock_azure_config):
        """Test detecting update event."""
        client = AzureFHIRClient(mock_azure_config)

        event = {"eventType": "Microsoft.HealthcareApis.FhirResourceUpdate"}

        result = client.check_if_update(event)

        assert result is True

    def test_check_if_update_false(self, mock_azure_config):
        """Test detecting non-update event."""
        client = AzureFHIRClient(mock_azure_config)

        event = {"eventType": "Microsoft.HealthcareApis.FhirResourceCreate"}

        result = client.check_if_update(event)

        assert result is False

    def test_check_if_update_no_event_type(self, mock_azure_config):
        """Test event without eventType field."""
        client = AzureFHIRClient(mock_azure_config)

        event = {}

        result = client.check_if_update(event)

        assert result is False


class TestAuthentication:
    """Test OAuth2 authentication flow."""

    @responses.activate
    def test_authentication_returns_bearer_token(self, mock_azure_config):
        """Test that authentication returns Bearer token header."""
        responses.add(
            responses.POST,
            mock_azure_config['azure.fhir']['token_url'],
            json={
                'access_token': 'mock-access-token-12345',
                'token_type': 'Bearer',
                'expires_in': 3600
            },
            status=200
        )

        client = AzureFHIRClient(mock_azure_config)
        headers = client.authentication()

        assert 'Authorization' in headers
        assert headers['Authorization'] == 'Bearer mock-access-token-12345'
        assert headers['Accept'] == 'application/fhir+json'

    @responses.activate
    def test_authentication_sends_correct_credentials(self, mock_azure_config):
        """Test that authentication sends correct client credentials."""
        responses.add(
            responses.POST,
            mock_azure_config['azure.fhir']['token_url'],
            json={'access_token': 'token', 'expires_in': 3600},
            status=200
        )

        client = AzureFHIRClient(mock_azure_config)
        client.authentication()

        assert len(responses.calls) == 1
        request_body = responses.calls[0].request.body

        assert f"client_id={mock_azure_config['azure.fhir']['client_id']}" in request_body
        assert 'grant_type=client_credentials' in request_body

    @responses.activate
    def test_authentication_failure_raises_error(self, mock_azure_config):
        """Test that authentication failure raises appropriate error."""
        responses.add(
            responses.POST,
            mock_azure_config['azure.fhir']['token_url'],
            json={'error': 'invalid_client', 'error_description': 'Invalid credentials'},
            status=401
        )

        client = AzureFHIRClient(mock_azure_config)

        with pytest.raises(Exception):
            client.authentication()


class TestFHIRConnectivityCheck:
    """Test FHIR server connectivity checks."""

    @responses.activate
    def test_fhir_connectivity_check_success(self, mock_azure_config):
        """Test successful FHIR server connectivity check."""
        # Mock OAuth token endpoint
        responses.add(
            responses.POST,
            mock_azure_config['azure.fhir']['token_url'],
            json={'access_token': 'token', 'expires_in': 3600},
            status=200
        )

        # Mock FHIR server endpoint
        responses.add(
            responses.GET,
            mock_azure_config['azure.fhir']['server_url'],
            json={
                'resourceType': 'CapabilityStatement',
                'status': 'active',
                'fhirVersion': '4.0.1'
            },
            status=200
        )

        client = AzureFHIRClient(mock_azure_config)
        result = client.fhir_connectivity_check()

        assert result is True

    @responses.activate
    def test_fhir_connectivity_check_server_error(self, mock_azure_config):
        """Test connectivity check exits on server error."""
        # Mock OAuth token endpoint
        responses.add(
            responses.POST,
            mock_azure_config['azure.fhir']['token_url'],
            json={'access_token': 'token', 'expires_in': 3600},
            status=200
        )

        # Mock FHIR server returning error
        responses.add(
            responses.GET,
            mock_azure_config['azure.fhir']['server_url'],
            json={'error': 'Service unavailable'},
            status=503
        )

        client = AzureFHIRClient(mock_azure_config)

        from pyfiles.dependencies.data_processing_error import PrerequisiteError
        with pytest.raises(PrerequisiteError):
            client.fhir_connectivity_check()


class TestFHIRGetRequest:
    """Test FHIR GET request method."""

    @responses.activate
    def test_fhir_get_request(self, mock_azure_config):
        """Test making FHIR GET request."""
        test_url = f"{mock_azure_config['azure.fhir']['server_url']}/Patient/123"

        responses.add(
            responses.GET,
            test_url,
            json={'resourceType': 'Patient', 'id': '123'},
            status=200
        )

        client = AzureFHIRClient(mock_azure_config)

        response = AzureFHIRClient.fhir_get_request(
            session=client.session,
            fhir_url=test_url,
            authorization={'Authorization': 'Bearer test-token'},
            timeout=30
        )

        assert response.status_code == 200
        assert response.json()['id'] == '123'


class TestFHIRClientURLFormats:
    """Test URL format consistency."""

    def test_azure_url_includes_count(self, mock_azure_config):
        """Test Azure URL includes _count parameter."""
        client = AzureFHIRClient(mock_azure_config)

        url = client.get_fhir_batch_export_url(
            fhir_resource="Observation",
            start_date="2024-01-01",
            end_date="2024-01-31"
        )

        assert '_count=' in url
        assert str(mock_azure_config['FHIR']['ndjson_file_size']) in url

