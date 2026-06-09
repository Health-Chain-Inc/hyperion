"""Mock implementations for Azure Service Bus queue client."""
import json
from datetime import datetime
from typing import Dict, List, Optional


class MockServiceBusMessage:
    """Mock Azure Service Bus message."""

    def __init__(self, body: str):
        self._body = body
        self.message_id = "mock-message-id"
        self.enqueued_time_utc = datetime.utcnow()

    def __str__(self):
        return self._body


class MockServiceBusReceiver:
    """Mock Service Bus receiver."""

    def __init__(self, messages: Optional[List[Dict]] = None):
        self._messages = [
            MockServiceBusMessage(json.dumps(m))
            for m in (messages or [])
        ]
        self._completed = []
        self._dead_lettered = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def receive_messages(self, max_message_count: int = 1):
        return self._messages[:max_message_count]

    def complete_message(self, message):
        self._completed.append(message)

    def dead_letter_message(self, message, reason: str = None):
        self._dead_lettered.append((message, reason))


class MockServiceBusSender:
    """Mock Service Bus sender."""

    def __init__(self):
        self.sent_messages = []
        self.scheduled_messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def send_messages(self, message):
        if isinstance(message, list):
            self.sent_messages.extend(message)
        else:
            self.sent_messages.append(message)

    def schedule_messages(self, message, schedule_time_utc):
        self.scheduled_messages.append((message, schedule_time_utc))

    def create_message_batch(self):
        return MockMessageBatch()


class MockMessageBatch:
    """Mock message batch."""

    def __init__(self):
        self._messages = []

    def __len__(self):
        return len(self._messages)

    def add_message(self, message):
        self._messages.append(message)


class MockServiceBusClient:
    """Mock ServiceBusClient."""

    def __init__(self):
        self._receivers = {}
        self._senders = {}

    @classmethod
    def from_connection_string(cls, conn_str: str, retry_total: int = 5, logging_enable: bool = True):
        return cls()

    def get_subscription_receiver(self, topic_name: str, subscription_name: str, receive_mode=None):
        key = f"{topic_name}/{subscription_name}"
        if key not in self._receivers:
            self._receivers[key] = MockServiceBusReceiver()
        return self._receivers[key]

    def get_queue_receiver(self, queue_name: str):
        if queue_name not in self._receivers:
            self._receivers[queue_name] = MockServiceBusReceiver()
        return self._receivers[queue_name]

    def get_queue_sender(self, queue_name: str):
        if queue_name not in self._senders:
            self._senders[queue_name] = MockServiceBusSender()
        return self._senders[queue_name]

    def get_topic_sender(self, topic_name: str):
        if topic_name not in self._senders:
            self._senders[topic_name] = MockServiceBusSender()
        return self._senders[topic_name]

    def close(self):
        pass


class MockAzureQueueClient:
    """Mock implementation of AzureQueueClient for testing."""

    def __init__(self, messages: Optional[List[Dict]] = None, configurations: Optional[Dict] = None):
        self._messages = [
            MockServiceBusMessage(json.dumps(m))
            for m in (messages or [])
        ]
        self.sent_messages = []
        self.completed_messages = []
        self.dead_lettered_messages = []
        self.configurations = configurations or {
            'azure.servicebus': {
                'connection_string': 'mock-connection-string',
                'core_topic': 'test-topic',
                'core_processor_subscription': 'test-sub',
                'eventload_queue_name': 'test-eventload',
                'audit_queue_name': 'test-audit',
                'retry_queue_name': 'test-retry',
                'batch_parameter_queue_name': 'test-params'
            },
            'azure.cloud_storage': {
                'baseurl': 'https://test.blob.core.windows.net/',
                'ndjson_stage_container': 'staging'
            }
        }

    def get_batch_queue_receiver(self):
        """Return a mock receiver."""
        return MockServiceBusReceiver(
            [json.loads(str(m)) for m in self._messages]
        )

    def get_event_queue_receiver(self):
        return MockServiceBusReceiver()

    def get_parameter_queue_receiver(self):
        return MockServiceBusReceiver()

    def get_audit_queue_receiver(self):
        return MockServiceBusReceiver()

    def get_retry_queue_receiver(self):
        return MockServiceBusReceiver()

    def receive_messages(self, receiver, max_message_count: int, max_wait_time: int = None):
        """Return mock messages."""
        return self._messages[:max_message_count]

    @staticmethod
    def read_message_body(message) -> Dict:
        """Parse message body as JSON."""
        return json.loads(str(message))

    def complete_message(self, receiver, queue_name: str, message):
        """Mark message as completed."""
        self.completed_messages.append(message)

    def dead_letter_message(self, receiver, queue_name: str, message, reason: str):
        """Move message to dead letter queue."""
        self.dead_lettered_messages.append((message, reason))

    def insert_to_batch_load_queue(self, message: Dict, scheduled: bool = False, delay_time: int = 0):
        """Record sent message."""
        self.sent_messages.append(('batch', message, scheduled, delay_time))

    def insert_to_audit_queue(self, message: Dict, table_name: str):
        """Record audit message."""
        self.sent_messages.append(('audit', message, table_name))

    def insert_to_reject_queue(self, message: Dict):
        """Record reject message."""
        self.sent_messages.append(('reject', message))

    def insert_to_event_load_queue(self, message: Dict, delay_time: int = 5):
        """Record event load message."""
        self.sent_messages.append(('event', message, delay_time))

    def insert_schedule_message_to_audit_queue(self, message: Dict, scheduled: bool = False, delay_time: int = 1):
        """Record scheduled audit message."""
        self.sent_messages.append(('audit_scheduled', message, scheduled, delay_time))

    def insert_to_fhir_parameter_queue(self, message: Dict):
        """Record FHIR parameter message."""
        self.sent_messages.append(('fhir_param', message))

    def get_ndjson_filepath_message(self, filename: str, folder_name: str) -> Dict:
        """Create exporter message with file path."""
        base_path = f"{self.configurations['azure.cloud_storage']['baseurl']}{self.configurations['azure.cloud_storage']['ndjson_stage_container']}"
        return {
            "url": f"{base_path}/{folder_name}/{filename}",
            "request_time": str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        }

    @staticmethod
    def get_ndjson_filepath(message) -> tuple:
        """Extract filepath info from message."""
        filepath_message_dict = json.loads(str(message))
        blob_url = filepath_message_dict.get("url", "")
        filename = "_".join(blob_url.split("/")[-3:])
        fhir_resource_type = blob_url.split("/")[-1].split("-")[0]
        return blob_url, fhir_resource_type, filename
