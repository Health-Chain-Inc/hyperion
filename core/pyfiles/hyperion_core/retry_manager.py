import concurrent.futures
import json
import logging
import signal
import threading
import time
from datetime import datetime
from queue import Queue

from azure.servicebus.exceptions import ServiceBusConnectionError

from pyfiles.dependencies.enum import PipelineErrorCode


class RetryManager:
    def __init__(
        self,
        queue_client,
        storage_client,
        project_configurations,
    ):
        self.storage_client = storage_client
        self.queue_client = queue_client
        self.project_configurations = project_configurations
        self.application_name = project_configurations["application"]["name"]
        logging.info('Initialized RetryManager')

    def run(self, message_queue, message_count, shutdown_event):
        while not shutdown_event.is_set():
            try:
                raw_receiver = self.queue_client.get_retry_queue_receiver()

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
                                    logging.info("No messages to process (retry-manager)")
                                time.sleep(6)
                                continue
                            idle_counter = 0

                            for retry_message in received_message_array:
                                message_queue.put(retry_message)
                                self.queue_client.complete_message(receiver,
                                                                raw_receiver,
                                                                retry_message)

                                retry_message = self.queue_client.read_message_body(
                                    retry_message
                                )

                                logging.info("(filepath_id=%s): Processing retry, error_code=%s",
                                    retry_message.get('filepath_id', 'unknown'), retry_message.get('error_code'))

                                blob_url = retry_message.get("url", None)
                                if blob_url and retry_message.get("error_code", None) in [PipelineErrorCode.INSERTION_FAILED.value, PipelineErrorCode.NORMALIZATION_FAILED.value]:
                                    logging.debug("Processing retry: url=%s, error_code=%s", retry_message.get('url'), retry_message.get('error_code'))
                                    if blob_url.split("/")[-1].count('-') == 1:
                                        self.process_message(retry_message)
                                    else:
                                        logging.warning("Retry processing skipped after one retry: url=%s", retry_message.get('url'))
                                else:
                                    logging.warning("Retry skipped — invalid url or error_code: url=%s, error_code=%s", retry_message.get('url'), retry_message.get('error_code'))
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
                logging.exception("Exception during retry processing")
                raise

            break

        logging.info("Exiting retry processing loop")

    def process_message(self, retry_message):

        failure_container_client = self.storage_client.get_failure_container_client()

        try:

            (blob_url, _, filename) = self.queue_client.get_ndjson_filepath(
                json.dumps(retry_message)
            )

            blob_data = self.storage_client.read(
                blob_url,
                failure_container_client,
                filename,
                self.queue_client,
                retry_message.get("retry_count", 0),
            )

            if blob_data is None:
                logging.error("Failed to read blob from failure container: %s", blob_url.split('?')[0])
                return

            filename = filename.replace(".ndjson", "")

            folder_name = "/".join(filename.replace("_", "/").split("/")[:2])

            filename = filename.replace("_", "/").split("/")[-1]

            for index, fhir_resource in enumerate(blob_data):

                ind_filename = f"{filename}-{index + 1}.ndjson"

                staging_blob_url = f"{folder_name}/{ind_filename}"

                fhir_data_list = [{"resource": fhir_resource}]

                self.storage_client.upload_ndjson_to_stage(
                    fhir_data_list, ind_filename, folder_name
                )

                if self.project_configurations["initialization"]["cloud_storage"].lower() == "azure":
                    fhir_retry_message = {
                        "url": f"{self.project_configurations['azure.cloud_storage']['baseurl']}{self.project_configurations['azure.cloud_storage']['ndjson_stage_container']}/{staging_blob_url}",
                        "request_time": str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
                        "filepath_id": retry_message.get("filepath_id"),
                    }

                    self.queue_client.insert_to_batch_load_queue(fhir_retry_message)

            self.storage_client.delete(blob_url, failure_container_client)

        except Exception:
            logging.exception(
                "Exception during processing of message %s (error_code=%s)",
                retry_message.get('url'), retry_message.get('error_code')
            )

    def retry_processor(self):
        shutdown_event = threading.Event()

        def handle_signal(sig, frame):
            logging.info("Received signal %s, initiating graceful shutdown.", sig)
            shutdown_event.set()

        # Register signal handlers for SIGINT and SIGTERM
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            concurrent_receivers = int(
                self.project_configurations["processing"]["message"]
            ) * int(self.project_configurations["processing"]["converter_cores"])
            # concurrent_receivers = 1
            message_queue = Queue()
            futures = []

            # pylint: disable=line-too-long
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=concurrent_receivers
            ) as thread_pool:
                # pylint: enable=line-too-long
                for _ in range(concurrent_receivers):
                    future = thread_pool.submit(
                        self.run, message_queue, concurrent_receivers, shutdown_event
                    )
                    futures.append(future)

                # Wait for futures to complete or shutdown event
                while not shutdown_event.is_set():
                    done, not_done = concurrent.futures.wait(
                        futures,
                        timeout=1,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    if done:
                        break

                if shutdown_event.is_set():
                    logging.info(
                        "Graceful shutdown triggered. Waiting for threads to finish..."
                    )
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
