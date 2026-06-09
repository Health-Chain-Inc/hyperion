
import concurrent.futures
import logging
import signal
import threading
import time
from queue import Queue

from azure.servicebus.exceptions import ServiceBusConnectionError

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.enum import ApplicationEnums
from pyfiles.hyperion_core.fhir_event_exporter import FHIREventExporter


class FHIREventProcessor:
    """
    Class to pull FHIR records
    Parameters: fhir_event_dict -> event message
    """

    def __init__(self, configurations, storage_client, queue_client, fhir_client):
        self.project_configurations = configurations
        self.fhir_client = fhir_client
        self.queue_client = queue_client
        self.storage_client = storage_client
        self.application_name = ApplicationEnums.EVENT_LOAD_EXPORTER.value

    def process_fhir_event_message(self, messages, message_count, shutdown_event):
        """
        Function to process fhir event messages
        """
        while not shutdown_event.is_set():
            try:
                raw_receiver = self.queue_client.get_event_queue_receiver()
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
                                    logging.info("No messages to process (event-load-exporter)")
                                time.sleep(6)
                                continue
                            idle_counter = 0

                            for fhir_message in received_message_array:
                                messages.put(fhir_message)
                                self.queue_client.complete_message(
                                    receiver,
                                    self.queue_client.get_event_queue_receiver(),
                                    fhir_message)

                                fhir_message_dict = self.queue_client.read_message_body(fhir_message)
                                logging.info("Processing event: resource=%s, id=%s",
                                    fhir_message_dict.get('data', {}).get('resourceType', 'unknown'),
                                    fhir_message_dict.get('data', {}).get('resourceFhirId', 'unknown'))

                                try:
                                    fhir_event_exporter = FHIREventExporter(
                                        fhir_message_dict, self.project_configurations,
                                        self.fhir_client, self.queue_client, self.storage_client
                                    )

                                    fhir_event_exporter.run()

                                except DataProcessingException as dpe:
                                    try:
                                        logging.info("Re-queuing event message (error_code=%s): %s",
                                            dpe.error_code, dpe.errors)
                                        dpe.fhirpullerror(
                                            fhir_message_dict,
                                            self.project_configurations,
                                            self.application_name,
                                            self.storage_client,
                                            self.queue_client)
                                    except Exception:
                                        logging.exception(
                                            "Error-recovery failed for event message (filepath_id=%s, error_code=%s)",
                                            fhir_message_dict.get('data', {}).get('resourceFhirId', 'unknown'),
                                            getattr(dpe, 'error_code', 'unknown'))
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
                logging.exception("Exception during event processing")
                raise

            break

        logging.info("Exiting event processing loop")

    def fhir_event_exporter(self):
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
                    future = thread_pool.submit(self.process_fhir_event_message,
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
