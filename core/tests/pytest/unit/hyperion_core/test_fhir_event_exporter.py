"""Unit tests for FHIREventExporter class."""
import pytest
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.handlers import Handlers
from tests.pytest.mocks.mock_fhir_responses import (
    create_mock_single_patient,
    create_mock_error_response
)


class TestFHIREventExporterInitialization:
    """Test FHIREventExporter initialization."""

    def test_initialization_stores_parameters(self, mock_azure_config):
        """Test that initialization stores all parameters."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_fhir = MagicMock()
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        event_dict = {
            'resourceType': 'Patient',
            'id': 'patient-123',
            'action': 'create'
        }

        exporter = FHIREventExporter(
            fhir_event_dict=event_dict,
            configurations=mock_azure_config,
            fhir_client=mock_fhir,
            queue_client=MagicMock(),
            storage_client=MagicMock()
        )

        assert exporter.fhir_event_dict == event_dict
        assert exporter.configurations == mock_azure_config
        assert exporter.fhir_resource_type == 'Patient'
        assert 'Patient/123' in exporter.fhir_resource_url

    def test_initialization_extracts_resource_info(self, mock_azure_config):
        """Test that initialization extracts resource type and URL."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_fhir = MagicMock()
        mock_fhir.get_fhir_event_export_url.return_value = ('Observation', 'https://fhir.test/Observation/456')
        mock_fhir.check_if_update.return_value = True

        event_dict = {
            'resourceType': 'Observation',
            'id': 'obs-456',
            'action': 'update'
        }

        exporter = FHIREventExporter(
            fhir_event_dict=event_dict,
            configurations=mock_azure_config,
            fhir_client=mock_fhir,
            queue_client=MagicMock(),
            storage_client=MagicMock()
        )

        mock_fhir.get_fhir_event_export_url.assert_called_once_with(event_dict)
        mock_fhir.check_if_update.assert_called_once_with(event_dict)
        assert exporter.is_update is True


class TestFhirEventPull:
    """Test fhir_event_pull method."""

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_fhir_event_pull_success(self, mock_session_class, mock_azure_config):
        """Test successful FHIR event data pull."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_response = create_mock_single_patient(patient_id='patient-123')

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/event-load/patient-123/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        event_dict = {'resourceType': 'Patient', 'id': 'patient-123'}

        exporter = FHIREventExporter(
            fhir_event_dict=event_dict,
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        mock_fhir.fhir_get_request.assert_called_once()
        mock_storage.upload_ndjson_to_stage.assert_called_once()
        mock_queue.insert_to_batch_load_queue.assert_called_once()

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_fhir_event_pull_creates_correct_folder_name(self, mock_session_class, mock_azure_config):
        """Test fhir_event_pull creates folder with event-load prefix."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_response = create_mock_single_patient(patient_id='test-patient-456')

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/456')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {'url': 'test'}

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': 'test-patient-456'},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        # Verify folder name contains event-load and patient id
        upload_call = mock_storage.upload_ndjson_to_stage.call_args
        folder_name = upload_call[0][2]  # Third positional arg
        assert 'event-load' in folder_name
        assert 'test-patient-456' in folder_name

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_fhir_event_pull_wraps_resource_in_list(self, mock_session_class, mock_azure_config):
        """Test fhir_event_pull wraps single resource in list format."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_response = create_mock_single_patient(patient_id='patient-123')

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {'url': 'test'}

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': 'patient-123'},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        # Verify data was wrapped in list with 'resource' key
        upload_call = mock_storage.upload_ndjson_to_stage.call_args
        fhir_data_list = upload_call[0][0]  # First positional arg
        assert isinstance(fhir_data_list, list)
        assert len(fhir_data_list) == 1
        assert 'resource' in fhir_data_list[0]

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_fhir_event_pull_raises_on_non_200(self, mock_session_class, mock_azure_config):
        """Test fhir_event_pull raises DataProcessingException on non-200 response.

        Non-200 responses must raise so the error-handling/audit path kicks in,
        preventing silent data loss.
        """
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        error_response = create_mock_error_response(status_code=404)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = error_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_queue = MagicMock()

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': 'patient-123'},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        # Should raise DataProcessingException for non-200 response
        with pytest.raises(DataProcessingException):
            exporter.fhir_event_pull()

        # Verify no upload was attempted for non-200 response
        mock_storage.upload_ndjson_to_stage.assert_not_called()


class TestRunMethod:
    """Test run method."""

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_run_invokes_fhir_event_pull(self, mock_session_class, mock_azure_config):
        """Test run method invokes fhir_event_pull."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_response = create_mock_single_patient()

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {'url': 'test'}

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': 'patient-123'},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.run()

        mock_fhir.fhir_get_request.assert_called_once()


class TestLineageTracking:
    """Test lineage tracking functionality."""

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_fhir_event_pull_creates_lineage_when_enabled(self, mock_session_class, mock_azure_config):
        """Test lineage record is created when is_lineage is True."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_response = create_mock_single_patient(patient_id='patient-123')

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {'url': 'test'}

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'True'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': 'patient-123'},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        # Verify lineage was inserted
        mock_queue.insert_to_audit_queue.assert_called()
        lineage_call = mock_queue.insert_to_audit_queue.call_args
        lineage_data = lineage_call[0][0]
        assert lineage_data['resource_type'] == 'Patient'
        assert lineage_data['record_count'] == 1
        # Enum value is 'event-load-exporter' (lowercase with hyphens)
        assert lineage_data['pipeline_type'] == 'event-load-exporter'

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_fhir_event_pull_skips_lineage_when_disabled(self, mock_session_class, mock_azure_config):
        """Test no lineage record when is_lineage is False."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_response = create_mock_single_patient()

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {'url': 'test'}

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': 'patient-123'},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        mock_queue.insert_to_audit_queue.assert_not_called()


class TestFileNaming:
    """Test file naming conventions."""

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_filename_follows_convention(self, mock_session_class, mock_azure_config):
        """Test filename follows ResourceType-1.ndjson convention."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        mock_response = create_mock_single_patient()

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/123')
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {'url': 'test'}

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': 'patient-123'},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        upload_call = mock_storage.upload_ndjson_to_stage.call_args
        filename = upload_call[0][1]  # Second positional arg
        assert filename == 'Patient-1.ndjson'


class TestLineageFilepathId:
    """Test that lineage data uses filepath_id from Handlers.generate_event_filepath_id."""

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_lineage_filepath_id_matches_handlers_generate(self, mock_session_class, mock_azure_config):
        """When lineage is enabled, lineage data filepath_id must equal Handlers.generate_event_filepath_id(id, versionId)."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        patient_id = 'patient-lineage-001'
        version_id = '1'  # create_mock_single_patient always sets meta.versionId to '1'
        mock_response = create_mock_single_patient(patient_id=patient_id)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/' + patient_id)
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/event-load/' + patient_id + '/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'True'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': patient_id},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        expected_filepath_id = Handlers.generate_event_filepath_id(patient_id, version_id)

        # Verify insert_to_audit_queue was called and lineage filepath_id matches expected value
        mock_queue.insert_to_audit_queue.assert_called_once()
        lineage_call_args = mock_queue.insert_to_audit_queue.call_args
        lineage_data = lineage_call_args[0][0]
        assert lineage_data['filepath_id'] == expected_filepath_id

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_queue_message_contains_filepath_id(self, mock_session_class, mock_azure_config):
        """When lineage is enabled, the queue message sent via insert_to_batch_load_queue must contain a filepath_id key."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        patient_id = 'patient-lineage-002'
        mock_response = create_mock_single_patient(patient_id=patient_id)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/' + patient_id)
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/event-load/' + patient_id + '/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'True'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': patient_id},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        mock_queue.insert_to_batch_load_queue.assert_called_once()
        queue_call_args = mock_queue.insert_to_batch_load_queue.call_args
        queue_message = queue_call_args[0][0]
        assert 'filepath_id' in queue_message


class TestFilepathIdInQueueMessage:
    """Test that the filepath_id on the queue message is consistent with Handlers.generate_event_filepath_id."""

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_queue_message_filepath_id_present_after_fhir_event_pull(self, mock_session_class, mock_azure_config):
        """After fhir_event_pull, insert_to_batch_load_queue call args must include a filepath_id key."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        patient_id = 'patient-queue-001'
        mock_response = create_mock_single_patient(patient_id=patient_id)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/' + patient_id)
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/event-load/' + patient_id + '/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': patient_id},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        mock_queue.insert_to_batch_load_queue.assert_called_once()
        queue_call_args = mock_queue.insert_to_batch_load_queue.call_args
        queue_message = queue_call_args[0][0]
        assert 'filepath_id' in queue_message

    @patch('pyfiles.hyperion_core.fhir_event_exporter.requests.Session')
    def test_queue_message_filepath_id_consistent_with_handlers(self, mock_session_class, mock_azure_config):
        """The filepath_id on the queue message must equal Handlers.generate_event_filepath_id(patient_id, version_id)."""
        from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter

        patient_id = 'patient-queue-002'
        version_id = '1'  # create_mock_single_patient always sets meta.versionId to '1'
        mock_response = create_mock_single_patient(patient_id=patient_id)

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_fhir = MagicMock()
        mock_fhir.authentication.return_value = {'Authorization': 'Bearer token'}
        mock_fhir.fhir_get_request.return_value = mock_response
        mock_fhir.get_fhir_event_export_url.return_value = ('Patient', 'https://fhir.test/Patient/' + patient_id)
        mock_fhir.check_if_update.return_value = False

        mock_storage = MagicMock()
        mock_storage.upload_ndjson_to_stage.return_value = True

        mock_queue = MagicMock()
        mock_queue.get_ndjson_filepath_message.return_value = {
            'url': 'https://storage/staging/event-load/' + patient_id + '/Patient-1.ndjson'
        }

        config = mock_azure_config.copy()
        config['FHIR'] = {'timeout_seconds': '30'}
        config['default_value'] = {'is_lineage': 'False'}

        exporter = FHIREventExporter(
            fhir_event_dict={'resourceType': 'Patient', 'id': patient_id},
            configurations=config,
            fhir_client=mock_fhir,
            queue_client=mock_queue,
            storage_client=mock_storage
        )

        exporter.fhir_event_pull()

        expected_filepath_id = Handlers.generate_event_filepath_id(patient_id, version_id)

        queue_call_args = mock_queue.insert_to_batch_load_queue.call_args
        queue_message = queue_call_args[0][0]
        assert queue_message['filepath_id'] == expected_filepath_id
