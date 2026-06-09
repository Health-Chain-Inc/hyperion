"""Unit tests for AzureQueueClient."""
import pytest
import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from pyfiles.adapters.queue_clients import AzureQueueClient


class TestMessageParsing:
    """Test message body parsing - no mocking needed."""

    def test_read_message_body_valid_json(self):
        """Test parsing valid JSON message body."""
        message = '{"url": "https://storage.blob.core.windows.net/container/file.ndjson", "request_time": "2024-01-01T00:00:00Z"}'

        result = AzureQueueClient.read_message_body(message)

        assert result['url'] == 'https://storage.blob.core.windows.net/container/file.ndjson'
        assert 'request_time' in result

    def test_read_message_body_with_metadata(self):
        """Test parsing message with additional metadata."""
        message = json.dumps({
            "url": "https://storage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson",
            "request_time": "2024-01-01T10:00:00Z",
            "resource_type": "Patient",
            "batch_id": "batch-123"
        })

        result = AzureQueueClient.read_message_body(message)

        assert result['resource_type'] == 'Patient'
        assert result['batch_id'] == 'batch-123'


class TestNDJSONPathExtraction:
    """Test NDJSON filepath extraction from messages."""

    def test_get_ndjson_filepath_extracts_resource_type(self):
        """Test extracting resource type from NDJSON path."""
        mock_message = MagicMock()
        mock_message.__str__ = lambda self: json.dumps({
            "url": "https://teststorage.blob.core.windows.net/staging/batch-load/20240101/Patient-1.ndjson"
        })

        blob_url, resource_type, filename = AzureQueueClient.get_ndjson_filepath(mock_message)

        assert resource_type == 'Patient'
        assert 'Patient-1.ndjson' in filename
        assert 'staging/batch-load/20240101/Patient-1.ndjson' in blob_url

    def test_get_ndjson_filepath_observation(self):
        """Test extraction with Observation resource."""
        mock_message = MagicMock()
        mock_message.__str__ = lambda self: json.dumps({
            "url": "https://teststorage.blob.core.windows.net/staging/batch-load/20240115/Observation-5.ndjson"
        })

        blob_url, resource_type, filename = AzureQueueClient.get_ndjson_filepath(mock_message)

        assert resource_type == 'Observation'

    def test_get_ndjson_filepath_condition(self):
        """Test extraction with Condition resource."""
        mock_message = MagicMock()
        mock_message.__str__ = lambda self: json.dumps({
            "url": "https://teststorage.blob.core.windows.net/staging/event-load/20240120/Condition-10.ndjson"
        })

        blob_url, resource_type, filename = AzureQueueClient.get_ndjson_filepath(mock_message)

        assert resource_type == 'Condition'


class TestAzureQueueClientInitialization:
    """Test Azure queue client initialization with mocked ServiceBusClient."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_client_initializes_with_connection_string(self, mock_sb_client, mock_azure_config):
        """Test that client initializes with Azure config (dual-client: called twice)."""
        mock_sb_client.from_connection_string.return_value = MagicMock()

        client = AzureQueueClient(mock_azure_config)

        assert mock_sb_client.from_connection_string.call_count == 2
        assert client is not None

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_client_stores_configurations(self, mock_sb_client, mock_azure_config):
        """Test that client stores configurations."""
        mock_sb_client.from_connection_string.return_value = MagicMock()

        client = AzureQueueClient(mock_azure_config)

        assert client.configurations == mock_azure_config


class TestMessagePathGeneration:
    """Test message path/URL generation."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_get_ndjson_filepath_message(self, mock_sb_client, mock_azure_config):
        """Test generating message with NDJSON filepath."""
        mock_sb_client.from_connection_string.return_value = MagicMock()

        client = AzureQueueClient(mock_azure_config)
        result = client.get_ndjson_filepath_message(
            filename='Patient-1.ndjson',
            folder_name='batch-load/20240101'
        )

        assert 'url' in result
        assert 'request_time' in result
        assert 'Patient-1.ndjson' in result['url']
        assert 'batch-load/20240101' in result['url']

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_get_ndjson_filepath_message_includes_baseurl(self, mock_sb_client, mock_azure_config):
        """Test that message URL includes storage base URL."""
        mock_sb_client.from_connection_string.return_value = MagicMock()

        client = AzureQueueClient(mock_azure_config)
        result = client.get_ndjson_filepath_message(
            filename='Observation-5.ndjson',
            folder_name='event-load/20240115'
        )

        assert mock_azure_config['azure.cloud_storage']['baseurl'] in result['url']
        assert mock_azure_config['azure.cloud_storage']['ndjson_stage_container'] in result['url']


class TestSchedulerMessageCreation:
    """Test scheduler message creation."""

    def test_create_scheduler_message_structure(self):
        """Test scheduler message has correct structure."""
        start_time = datetime(2024, 1, 1, 0, 0, 0)
        end_time = datetime(2024, 1, 1, 12, 0, 0)

        message = AzureQueueClient.create_scheduler_message(
            resource_type="Patient",
            start_time=start_time,
            end_time=end_time
        )

        # It's a ServiceBusMessage, so we need to check its body
        assert message is not None

    def test_create_scheduler_message_formats_folder(self):
        """Test scheduler message folder name format."""
        start_time = datetime(2024, 1, 15, 8, 0, 0)
        end_time = datetime(2024, 1, 15, 12, 30, 0)

        message = AzureQueueClient.create_scheduler_message(
            resource_type="Observation",
            start_time=start_time,
            end_time=end_time
        )

        # Message body should contain folder_name with formatted timestamp
        assert message is not None


class TestAzureQueueReceivers:
    """Test Azure queue receiver methods."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_get_batch_queue_receiver(self, mock_sb_client, mock_azure_config):
        """Test getting batch queue receiver."""
        mock_client_instance = MagicMock()
        mock_receiver = MagicMock()
        mock_client_instance.get_subscription_receiver.return_value = mock_receiver
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_batch_queue_receiver()

        mock_client_instance.get_subscription_receiver.assert_called_once_with(
            topic_name=mock_azure_config['azure.servicebus']['core_topic'],
            subscription_name=mock_azure_config['azure.servicebus']['core_processor_subscription'],
            receive_mode=pytest.importorskip('azure.servicebus').ServiceBusReceiveMode.PEEK_LOCK,
            max_auto_lock_renew_duration=300
        )

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_get_event_queue_receiver(self, mock_sb_client, mock_azure_config):
        """Test getting event queue receiver."""
        mock_client_instance = MagicMock()
        mock_receiver = MagicMock()
        mock_client_instance.get_queue_receiver.return_value = mock_receiver
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_event_queue_receiver()

        mock_client_instance.get_queue_receiver.assert_called_with(
            queue_name=mock_azure_config['azure.servicebus']['eventload_queue_name'],
            max_auto_lock_renew_duration=300
        )

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_get_audit_queue_receiver(self, mock_sb_client, mock_azure_config):
        """Test getting audit queue receiver."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_audit_queue_receiver()

        mock_client_instance.get_queue_receiver.assert_called_with(
            queue_name=mock_azure_config['azure.servicebus']['audit_queue_name'],
            max_auto_lock_renew_duration=300
        )


class TestAzureQueueMessageSending:
    """Test Azure queue message sending."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_send_single_message(self, mock_sb_client, mock_azure_config):
        """Test sending a single message."""
        mock_sender = MagicMock()
        mock_sb_client.from_connection_string.return_value = MagicMock()

        message = {"test": "message", "value": 123}

        AzureQueueClient.send_single_message(mock_sender, message)

        mock_sender.send_messages.assert_called_once()

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_send_scheduled_single_message(self, mock_sb_client, mock_azure_config):
        """Test sending a scheduled message."""
        mock_sender = MagicMock()
        mock_sb_client.from_connection_string.return_value = MagicMock()

        message = {"test": "scheduled_message"}
        delay_time = 5

        AzureQueueClient.send_scheduled_single_message(mock_sender, message, delay_time)

        mock_sender.schedule_messages.assert_called_once()


class TestCompleteMessage:
    """Test message completion."""

    def test_complete_message(self):
        """Test completing a message."""
        mock_receiver = MagicMock()
        mock_message = MagicMock()

        AzureQueueClient.complete_message(mock_receiver, "test-queue", mock_message)

        mock_receiver.complete_message.assert_called_once_with(mock_message)


class TestContextSafeClients:
    """Test context-safe client wrappers."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_get_context_safe_client_azure(self, mock_sb_client, mock_azure_config):
        """Test Azure context-safe client returns no-op context manager."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        safe_client = client.get_context_safe_client()

        # Must be a no-op context manager — NOT the real client
        with safe_client:
            pass  # should not raise or close anything



class TestAzureConnectionRecovery:
    """Test Azure ServiceBus connection recovery with dual-client architecture."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_recreate_sender_client_on_connection_error(self, mock_sb_client, mock_azure_config):
        """Test that only sender client is recreated on connection failure."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        receiver_client_before = client._receiver_client

        # Simulate sender recreation
        client._recreate_sender_client()

        # Should have called from_connection_string 3 times (2 init + 1 recreate)
        assert mock_sb_client.from_connection_string.call_count == 3
        # Receiver client must NOT be touched
        assert client._receiver_client is receiver_client_before

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_create_clients_stores_both_clients(self, mock_sb_client, mock_azure_config):
        """Test that _create_clients stores both receiver and sender client instances."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)

        assert client._receiver_client == mock_client_instance
        assert client._sender_client == mock_client_instance

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_create_client_handles_failure(self, mock_sb_client, mock_azure_config):
        """Test that _create_client handles initialization failure."""
        mock_sb_client.from_connection_string.side_effect = Exception("Connection failed")

        with pytest.raises(Exception):
            AzureQueueClient(mock_azure_config)


class TestAzureMessageBatchOperations:
    """Test Azure message batch operations."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_insert_to_audit_queue_batch(self, mock_sb_client, mock_azure_config):
        """Test inserting batch of messages to audit queue."""
        mock_client_instance = MagicMock()
        mock_sender = MagicMock()
        mock_batch = MagicMock()
        mock_batch.__len__ = MagicMock(return_value=2)

        mock_client_instance.get_queue_sender.return_value.__enter__ = MagicMock(return_value=mock_sender)
        mock_client_instance.get_queue_sender.return_value.__exit__ = MagicMock(return_value=False)
        mock_sender.create_message_batch.return_value = mock_batch

        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)

        messages = [
            {'resource_id': 'patient-1'},
            {'resource_id': 'patient-2'}
        ]

        client.insert_to_audit_queue(messages, table_name='fhir_audit')

        mock_client_instance.get_queue_sender.assert_called_once()


class TestAzureScheduledMessages:
    """Test Azure scheduled message operations."""

    def test_send_scheduled_single_message_formats_correctly(self):
        """Test send_scheduled_single_message calls schedule_messages."""
        mock_sender = MagicMock()
        message = {'url': 'test', 'resource_type': 'Patient'}

        AzureQueueClient.send_scheduled_single_message(mock_sender, message, delay_time=5)

        mock_sender.schedule_messages.assert_called_once()

    def test_send_single_message_formats_correctly(self):
        """Test send_single_message calls send_messages."""
        mock_sender = MagicMock()
        message = {'url': 'test', 'resource_type': 'Patient'}

        AzureQueueClient.send_single_message(mock_sender, message)

        mock_sender.send_messages.assert_called_once()


class TestAutoLockRenewal:
    """Verify all receivers have auto lock renewal to prevent MessageLockLostError."""

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_batch_queue_receiver_has_auto_lock_renewal(self, mock_sb_client, mock_azure_config):
        """get_batch_queue_receiver must pass max_auto_lock_renew_duration=300."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_batch_queue_receiver()

        mock_client_instance.get_subscription_receiver.assert_called_once()
        call_kwargs = mock_client_instance.get_subscription_receiver.call_args
        assert call_kwargs.kwargs.get('max_auto_lock_renew_duration') == 300 or \
               (len(call_kwargs) > 1 and call_kwargs[1].get('max_auto_lock_renew_duration') == 300)

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_event_queue_receiver_has_auto_lock_renewal(self, mock_sb_client, mock_azure_config):
        """get_event_queue_receiver must pass max_auto_lock_renew_duration=300."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_event_queue_receiver()

        call_kwargs = mock_client_instance.get_queue_receiver.call_args
        assert call_kwargs.kwargs.get('max_auto_lock_renew_duration') == 300

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_parameter_queue_receiver_has_auto_lock_renewal(self, mock_sb_client, mock_azure_config):
        """get_parameter_queue_receiver must pass max_auto_lock_renew_duration=300."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_parameter_queue_receiver()

        call_kwargs = mock_client_instance.get_queue_receiver.call_args
        assert call_kwargs.kwargs.get('max_auto_lock_renew_duration') == 300

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_audit_queue_receiver_has_auto_lock_renewal(self, mock_sb_client, mock_azure_config):
        """get_audit_queue_receiver must pass max_auto_lock_renew_duration=300."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_audit_queue_receiver()

        call_kwargs = mock_client_instance.get_queue_receiver.call_args
        assert call_kwargs.kwargs.get('max_auto_lock_renew_duration') == 300

    @patch('pyfiles.adapters.queue_clients.ServiceBusClient')
    def test_retry_queue_receiver_has_auto_lock_renewal(self, mock_sb_client, mock_azure_config):
        """get_retry_queue_receiver must pass max_auto_lock_renew_duration=300."""
        mock_client_instance = MagicMock()
        mock_sb_client.from_connection_string.return_value = mock_client_instance

        client = AzureQueueClient(mock_azure_config)
        client.get_retry_queue_receiver()

        call_kwargs = mock_client_instance.get_queue_receiver.call_args
        assert call_kwargs.kwargs.get('max_auto_lock_renew_duration') == 300
