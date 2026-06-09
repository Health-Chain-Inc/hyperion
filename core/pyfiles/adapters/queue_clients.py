import functools
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from azure.servicebus import (ServiceBusClient, ServiceBusMessage,
                              ServiceBusReceiveMode)
from azure.servicebus.exceptions import (ServiceBusConnectionError,
                                         MessageLockLostError)

from pyfiles.adapters.interface import ServiceBusMessageQueueClient
from pyfiles.dependencies.resource_manager import ResourceManager


class _NoOpContext:
    """No-op context manager returned by get_context_safe_client().

    Processors use `with client:` which previously called client.close() on exit,
    killing all receivers across all threads. This no-op prevents that — lifecycle
    is managed by AzureQueueClient.close() via ResourceManager on shutdown.
    """
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class AzureQueueClient(ServiceBusMessageQueueClient):
    """
    Azure Service Bus client with dual-client architecture for thread safety.

    Uses two separate ServiceBusClient instances:
    - _receiver_client: Long-lived, used by receiver factory methods. Never
      replaced by send retries, so receiver threads are never disrupted.
    - _sender_client: Used by send methods. Replaceable on connection errors
      via _recreate_sender_client() with thread-safe locking.

    On send connection errors:
    1. Recreates only the sender client (receivers unaffected)
    2. Retries the operation (up to 3 times with exponential backoff)
    3. Raises exception if all retries fail
    """

    def __init__(self, configurations):
        self.configurations = configurations
        self._receiver_client = None
        self._sender_client = None
        self._sender_lock = threading.Lock()
        self._receivers = []
        self._senders = []
        self._create_clients()
        # Register with ResourceManager for cleanup on shutdown
        ResourceManager().register("azure_queue_client", self, self.close)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _create_clients(self):
        """Create separate receiver and sender ServiceBusClient instances."""
        conn_str = self.configurations["azure.servicebus"]["connection_string"]
        try:
            self._receiver_client = ServiceBusClient.from_connection_string(
                conn_str=conn_str, retry_total=5, logging_enable=True)
            self._sender_client = ServiceBusClient.from_connection_string(
                conn_str=conn_str, retry_total=5, logging_enable=True)
        except Exception:
            logging.exception("Failed to create ServiceBusClients")
            self._receiver_client = None
            self._sender_client = None
            raise

    def _recreate_sender_client(self):
        """Recreate ONLY the sender client after a connection failure.

        The receiver client and all its receivers are completely unaffected.
        Thread-safe via _sender_lock.
        """
        with self._sender_lock:
            if self._sender_client:
                try:
                    self._sender_client.close()
                except Exception as e:
                    logging.warning("Error closing old sender client: %s", str(e))
            try:
                self._sender_client = ServiceBusClient.from_connection_string(
                    conn_str=self.configurations["azure.servicebus"]["connection_string"],
                    retry_total=5, logging_enable=True)
                logging.info("Sender ServiceBusClient recreated — receiver client unaffected")
            except Exception as e:
                logging.error("Failed to recreate sender ServiceBusClient: %s", str(e))
                self._sender_client = None
                raise

    @staticmethod
    def _retry_on_connection_error(func):
        """
        Decorator for retry on connection errors (OSError, ServiceBusConnectionError).
        Retries 3 times with exponential backoff (1s, 2s, 4s).
        Only recreates the sender client — receiver client is never touched.
        """
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            max_retries = 3
            last_error = None

            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except (ServiceBusConnectionError, OSError, ConnectionError) as e:
                    last_error = e
                    logging.warning(
                        "%s: Connection error on attempt %d/%d: %s",
                        func.__name__, attempt + 1, max_retries, str(e)
                    )
                    self._recreate_sender_client()
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s

            logging.error("%s failed after %d attempts", func.__name__, max_retries)
            raise last_error
        return wrapper

    def get_batch_queue_receiver(self):
        receiver = self._receiver_client.get_subscription_receiver(
            topic_name=self.configurations['azure.servicebus']['core_topic'],
            subscription_name=self.configurations['azure.servicebus']['core_processor_subscription'],
            receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
            max_auto_lock_renew_duration=300
        )
        self._receivers.append(receiver)
        return receiver

    def get_event_queue_receiver(self):
        receiver = self._receiver_client.get_queue_receiver(
            queue_name=self.configurations["azure.servicebus"]["eventload_queue_name"],
            max_auto_lock_renew_duration=300
        )
        self._receivers.append(receiver)
        return receiver

    def get_parameter_queue_receiver(self):
        receiver = self._receiver_client.get_queue_receiver(
            queue_name=self.configurations["azure.servicebus"]["batch_parameter_queue_name"],
            max_auto_lock_renew_duration=300
        )
        self._receivers.append(receiver)
        return receiver

    def get_parameter_queue_sender(self):
        sender = self._sender_client.get_queue_sender(
            queue_name=self.configurations["azure.servicebus"]["batch_parameter_queue_name"]
        )
        self._senders.append(sender)
        return sender

    def get_audit_queue_receiver(self):
        receiver = self._receiver_client.get_queue_receiver(
            queue_name=self.configurations["azure.servicebus"]["audit_queue_name"],
            max_auto_lock_renew_duration=300
        )
        self._receivers.append(receiver)
        return receiver

    def get_retry_queue_receiver(self):
        receiver = self._receiver_client.get_queue_receiver(
            queue_name=self.configurations["azure.servicebus"]["retry_queue_name"],
            max_auto_lock_renew_duration=300
        )
        self._receivers.append(receiver)
        return receiver

    def receive_messages(self, receiver, max_message_count, max_wait_time=None):
        return receiver.receive_messages(
            max_message_count=max_message_count,
            max_wait_time=max_wait_time
        )

    @staticmethod
    def read_message_body(message):
        return json.loads(str(message))

    @staticmethod
    def complete_message(receiver, queue_name, message):
        try:
            receiver.complete_message(message)
        except MessageLockLostError:
            logging.warning("Message lock expired before completion — "
                            "message will be redelivered by ServiceBus")

    @staticmethod
    def get_ndjson_filepath(message):
        filepath_message_dict = json.loads(str(message))
        blob_url = filepath_message_dict.get("url", None)
        filename = "_".join(blob_url.split("/")[-3:])
        fhir_resource_type = blob_url.split("/")[-1].split("-")[0]
        return blob_url, fhir_resource_type, filename

    @staticmethod
    def send_single_message(sender, message: dict):
        """Send a single message to queue."""
        message_json = json.dumps(message)
        sb_message = ServiceBusMessage(message_json)
        sender.send_messages(sb_message)

    @staticmethod
    def send_scheduled_single_message(sender, message: dict, delay_time: int):
        """Send a scheduled message to queue."""
        schedule_time_utc = datetime.now(timezone.utc) + timedelta(minutes=delay_time)
        message_json = json.dumps(message)
        sb_message = ServiceBusMessage(message_json)
        sender.schedule_messages(sb_message, schedule_time_utc)

    @_retry_on_connection_error
    def insert_to_reject_queue(self, message: dict):
        """Send message to reject queue."""
        queue_name = self.configurations["azure.servicebus"]["retry_queue_name"]
        sender = self._sender_client.get_queue_sender(queue_name=queue_name)
        with sender:
            self.send_single_message(sender, message)

    @_retry_on_connection_error
    def insert_to_event_load_queue(self, message: dict, delay_time: int = 5):
        """Send scheduled message to event load queue."""
        queue_name = self.configurations["azure.servicebus"]["eventload_queue_name"]
        sender = self._sender_client.get_queue_sender(queue_name=queue_name)
        with sender:
            self.send_scheduled_single_message(sender, message, delay_time)

    @_retry_on_connection_error
    def insert_to_batch_load_queue(self, message: dict, scheduled: bool = False, delay_time: int = 0):
        """Send message to batch load topic."""
        topic_name = self.configurations["azure.servicebus"]["core_topic"]
        sender = self._sender_client.get_topic_sender(topic_name=topic_name)
        with sender:
            if scheduled:
                self.send_scheduled_single_message(sender, message, delay_time)
            else:
                self.send_single_message(sender, message)

    @_retry_on_connection_error
    def insert_schedule_message_to_audit_queue(self, message: dict, scheduled: bool = False):
        """Send message to audit queue (optionally scheduled)."""
        queue_name = self.configurations["azure.servicebus"]["audit_queue_name"]
        sender = self._sender_client.get_queue_sender(queue_name=queue_name)
        with sender:
            delay_time = int(self.configurations["azure.servicebus"]["audit_queue_schedule_interval"])
            if scheduled:
                self.send_scheduled_single_message(sender, message, delay_time)
            else:
                self.send_single_message(sender, message)

    @_retry_on_connection_error
    def insert_to_fhir_parameter_queue(self, message: dict):
        """Send message to FHIR parameter queue."""
        queue_name = self.configurations["azure.servicebus"]["batch_parameter_queue_name"]
        sender = self._sender_client.get_queue_sender(queue_name=queue_name)
        with sender:
            self.send_single_message(sender, message)

    @_retry_on_connection_error
    def insert_to_audit_queue(self, message: list | dict, table_name: str):
        """
        Send messages to the audit queue.

        Args:
            message: Single message dict or list of message dicts
            table_name: Name of the destination table
        """
        queue_name = self.configurations["azure.servicebus"]["audit_queue_name"]
        messages = message if isinstance(message, list) else [message]

        for msg in messages:
            msg["table_name"] = table_name

        sender = self._sender_client.get_queue_sender(queue_name=queue_name)
        with sender:
            if len(messages) > 1:
                batch = sender.create_message_batch()
                for msg in messages:
                    message_json = json.dumps(msg)
                    sb_message = ServiceBusMessage(message_json)
                    try:
                        batch.add_message(sb_message)
                    except ValueError:
                        sender.send_messages(batch)
                        batch = sender.create_message_batch()
                        batch.add_message(sb_message)

                if len(batch) > 0:
                    sender.send_messages(batch)
            else:
                self.send_single_message(sender, messages[0])

    def get_ndjson_filepath_message(self, filename, folder_name, filepath_id=None):
        """Create exporter message with file path."""
        base_path = f"{self.configurations['azure.cloud_storage']['baseurl']}{self.configurations['azure.cloud_storage']['ndjson_stage_container']}"
        msg = {
            "url": f"{base_path}/{folder_name}/{filename}",
            "request_time": str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        }
        if filepath_id:
            msg["filepath_id"] = filepath_id
        return msg

    async def create_message_batch(self, sender_client):
        return sender_client.create_message_batch()

    async def send_batch_messages(self, sender_client, servicebus_batch):
        return sender_client.send_messages(servicebus_batch)

    async def add_batch_message(self, batch_message_sender, resource_scheduler_message, index):
        batch_message_sender.add_message(resource_scheduler_message)

    @staticmethod
    def create_scheduler_message(resource_type: str, start_time: datetime, end_time: datetime):
        """Create a scheduler message for batch processing."""
        return ServiceBusMessage(json.dumps({
            "resource_type": resource_type.strip(),
            "start_time": str(start_time.strftime("%Y-%m-%dT%H:%M:%S")),
            "end_time": str(end_time.strftime("%Y-%m-%dT%H:%M:%S")),
            "request_time": str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
            "folder_name": "batch-load/" + (
                str(end_time.strftime("%Y-%m-%dT%H:%M"))
                .replace(":", "")
                .replace("-", "")
            ),
        }))

    def get_context_safe_client(self):
        return _NoOpContext()

    def get_context_safe_receiver(self, receiver):
        return receiver

    def close(self):
        """Close all receivers, senders, and both clients."""
        for receiver in self._receivers:
            try:
                receiver.close()
            except Exception:
                pass
        self._receivers.clear()

        for sender in self._senders:
            try:
                sender.close()
            except Exception:
                pass
        self._senders.clear()

        for client_name, client in [("receiver", self._receiver_client), ("sender", self._sender_client)]:
            if client:
                try:
                    client.close()
                    logging.info("ServiceBusClient (%s) closed successfully", client_name)
                except Exception as e:
                    logging.warning("Error closing ServiceBusClient (%s): %s", client_name, e)
        self._receiver_client = None
        self._sender_client = None
