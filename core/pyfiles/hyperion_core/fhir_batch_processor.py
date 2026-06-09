import concurrent.futures
import logging
import signal
import threading
import time
import warnings
from queue import Queue

from azure.servicebus.exceptions import ServiceBusConnectionError

from pyfiles.hyperion_core.fhir_batch_exporter import FHIRBatchExport

warnings.simplefilter(action="ignore", category=FutureWarning)


class FHIRBatchProcessor:
    def __init__(self, project_configurations, storage_client, queue_client, fhir_client):
        self.project_configurations = project_configurations
        self.storage_client = storage_client
        self.queue_client = queue_client
        self.fhir_client = fhir_client
        logging.info('Initialized FHIR Batch processor')

    def process_fhir_message(self, messages, message_count, shutdown_event):
        while not shutdown_event.is_set():
            try:
                raw_receiver = self.queue_client.get_parameter_queue_receiver()

                receiver = self.queue_client.get_context_safe_receiver(raw_receiver)
                client = self.queue_client.get_context_safe_client()

                with client:
                    with receiver as r:
                        idle_counter = 0
                        while not shutdown_event.is_set():
                            received_message_array = self.queue_client.receive_messages(
                                r, message_count, 300
                            )

                            if not received_message_array:
                                idle_counter += 1
                                if idle_counter % 100 == 0:
                                    logging.info("No messages to process (batch-load-exporter)")
                                time.sleep(6)
                                continue
                            idle_counter = 0

                            for fhir_message in received_message_array:
                                messages.put(fhir_message)
                                event_trigger_dict = self.queue_client.read_message_body(fhir_message)
                                self.queue_client.complete_message(receiver,
                                                            self.queue_client.get_parameter_queue_receiver(),
                                                            fhir_message)

                                logging.info("Processing batch export: resource_type=%s, page=%s, retry=%s",
                                    event_trigger_dict.get('resource_type', 'unknown'),
                                    event_trigger_dict.get('page_number', 1),
                                    event_trigger_dict.get('retry_count', 0))

                                fhir_exporter = FHIRBatchExport(
                                    resource_type=event_trigger_dict.get("resource_type", None),
                                    start_date=event_trigger_dict.get("start_time", None),
                                    end_date=event_trigger_dict.get("end_time", None),
                                    fhir_url=event_trigger_dict.get("fhir_url", None),
                                    page_number=event_trigger_dict.get("page_number", 1),
                                    folder_name=event_trigger_dict.get("folder_name", None),
                                    retry_count=event_trigger_dict.get("retry_count", 0),
                                    retry_message=event_trigger_dict.get("retry_message",False),
                                    fhir_client=self.fhir_client,
                                    storage_client=self.storage_client,
                                    queue_client=self.queue_client
                                )
                                fhir_exporter.run(self.project_configurations)
            except ValueError as e:
                if "handler has already been shutdown" in str(e).lower():
                    logging.warning("ServiceBus receiver shutdown — reconnecting. "
                                    "Unacknowledged messages will be redelivered.")
                    time.sleep(2)
                    continue
                raise
            except ServiceBusConnectionError as e:
                logging.warning("ServiceBus connection lost: %s — reconnecting", e)
                time.sleep(2)
                continue
            except Exception:
                logging.exception("Exception during submit")
                raise

            break  # inner while exited cleanly (shutdown), exit outer loop

        logging.info("Exiting batch processing loop")

    def fhir_exporter(self):
        """Process FHIR Q messages"""
        shutdown_event = threading.Event()

        def handle_signal(sig, frame):
            logging.info("Received signal %s, initiating graceful shutdown.", sig)
            shutdown_event.set()

        # Register signal handlers for SIGINT and SIGTERM
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            concurrent_receivers = (int(self.project_configurations["processing"]["message"]) *
                                int(self.project_configurations["processing"]["converter_cores"])
            )
            message_queue = Queue()
            futures = []

            # pylint: disable=line-too-long
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_receivers) as thread_pool:
            # pylint: enable=line-too-long
                for _ in range(concurrent_receivers):
                    future = thread_pool.submit(self.process_fhir_message,
                                                message_queue,
                                                concurrent_receivers,
                                                shutdown_event)
                    futures.append(future)

                # Wait for futures to complete or shutdown event
                while not shutdown_event.is_set():
                    done, not_done = concurrent.futures.wait(
                        futures, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    if done:
                        break

                if shutdown_event.is_set():
                    logging.info("Graceful shutdown triggered. Waiting for threads to finish...")
                    # Actually wait for threads with a timeout
                    done, not_done = concurrent.futures.wait(futures, timeout=30)
                    if not_done:
                        logging.warning(
                            "Some threads did not complete within timeout: %d threads remaining",
                            len(not_done)
                        )
        except Exception:
            # Raise: preserve type and stack for the application entry point to handle.
            logging.exception("Exception during fhir converter invocation")
            raise
