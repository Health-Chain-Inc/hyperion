import concurrent.futures
import faulthandler
import gc
import logging
import signal
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from queue import Queue

from azure.servicebus.exceptions import ServiceBusConnectionError

import pandas as pd
import requests

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.db_ops import DBOps
from pyfiles.dependencies.df_ops import DFOps
from pyfiles.dependencies.enum import PipelineErrorCode
from pyfiles.dependencies.handlers import Handlers
from pyfiles.dependencies.resource_manager import ResourceManager
from pyfiles.hyperion_core.normalizer import Normalizer
from pyfiles.hyperion_core.transaction_manager import TransactionManager

faulthandler.enable()


class CoreLoadProcessor:
    # Class-level cache for deletion attributes (lazy loaded)
    _deletion_attributes = None

    @classmethod
    def get_deletion_attributes(cls):
        """Lazy load deletion attributes with singleton pattern."""
        if cls._deletion_attributes is None:
            cls._deletion_attributes = Handlers.json_reader(
                "schema/deletion_attributes.json"
            )
        return cls._deletion_attributes

    @staticmethod
    @lru_cache(maxsize=50)
    def get_fhir_structure(hl7_file_name: str):
        """
        Get HL7 resource structure for caching.

        Args:
            hl7_file_name: Path to the HL7 schema file
        """
        return Handlers.get_schema_file(hl7_file_name)

    def __init__(self,
                queue_client,
                storage_client,
                fhir_client,
                project_configurations,
                db_connection_pool):
        self.storage_client = storage_client
        self.queue_client = queue_client
        self.fhir_client = fhir_client
        self.project_configurations = project_configurations
        self.db_connection_pool = db_connection_pool
        self.application_name = project_configurations['application']['name']
        self.resource_structure = CoreLoadProcessor.get_fhir_structure(
            self.project_configurations["schema"]["hl7_file_name"]
        )

    def fhir_converter(self):
        shutdown_event = threading.Event()

        def handle_signal(sig, frame):
            logging.info("Received signal %s, initiating graceful shutdown.", sig)
            shutdown_event.set()
            # Clean up all registered resources
            ResourceManager().shutdown()

        # Register signal handlers for SIGINT and SIGTERM
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        message_queue = Queue()
        try:
            concurrent_receivers = (int(self.project_configurations["processing"]["message"]) *
                                int(self.project_configurations["processing"]["converter_cores"])
            )
            # concurrent_receivers = 1
            futures = []

            # pylint: disable=line-too-long
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_receivers) as thread_pool:
            # pylint: enable=line-too-long
                for _ in range(concurrent_receivers):
                    future = thread_pool.submit(self.run, message_queue, concurrent_receivers, shutdown_event)
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
            # Library code does not own the process-exit decision.
            logging.exception("Exception during fhir converter invocation")
            raise
        finally:
            # Drain the message queue to prevent memory accumulation
            while not message_queue.empty():
                try:
                    message_queue.get_nowait()
                except Exception:
                    break
            gc.collect()

    def get_processed_data(self,
                            fhir_data,
                            fhir_resource_type,
                            blob_url,
                            filepath_id=None):
        process_data = False
        array_counts_df = pd.DataFrame()
        fhir_data_df = DFOps.create_pandas_dataframe(fhir_data)

        (process_data,
         fhir_data_df,
         array_counts_df,
         audit_data_json) = (
            DBOps.filter_data_to_be_processed(self.db_connection_pool,
                                    fhir_resource_type,
                                    fhir_data_df,
                                    self.application_name,
                                    self.project_configurations["default_value"]["meta_source"],
                                    blob_url,
                                    filepath_id=filepath_id)
        )
        return (process_data, fhir_data_df,
                array_counts_df, audit_data_json)

    def normalizer(self,
                   fhir_resource_type,
                   process_data,
                   fhir_data_df,
                   filepath_id):
        """
        FHIR data normalization
        incase of batch load fhir_id is the file name.
        """

        try:
            if process_data:
                normalizer = Normalizer(
                    self.resource_structure,
                    fhir_resource_type,
                    fhir_data_df,
                    filepath_id
                )
                data_dictionary = normalizer.run()
                return data_dictionary

            logging.info("(filepath_id=%s): Received duplicate data", filepath_id)
            return None
        except DataProcessingException as e:
            raise DataProcessingException(f"(filepath_id={filepath_id}): normalizer failed: {e.errors}", str(e), PipelineErrorCode.NORMALIZATION_FAILED.value) from e
        except Exception as e:
            raise DataProcessingException(f"(filepath_id={filepath_id}): normalizer failed", str(e), PipelineErrorCode.NORMALIZATION_FAILED.value) from e

    def run(self, message_queue, message_count, shutdown_event):
        self.process_load_messages(message_queue, message_count, shutdown_event)

    def process_load_messages(self, messages, message_count, shutdown_event):
        batch_container_client = self.storage_client.get_staging_container_client()

        while not shutdown_event.is_set():
            try:
                raw_receiver = self.queue_client.get_batch_queue_receiver()

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
                                    logging.info("No messages to process (core-data-ingester)")
                                time.sleep(6)
                                continue
                            idle_counter = 0

                            for fhir_message in received_message_array:
                                messages.put(fhir_message)
                                self.queue_client.complete_message(receiver,
                                                                raw_receiver,
                                                                fhir_message)

                                fhir_message_dict = self.queue_client.read_message_body(fhir_message)

                                filepath_id = fhir_message_dict.get("filepath_id", None)
                                retry_count = fhir_message_dict.get("retry_count",0)
                                logging.info("(filepath_id=%s): Processing message, retry_count=%s", filepath_id, retry_count)

                                (blob_url,
                                fhir_resource_type,
                                filename) = self.queue_client.get_ndjson_filepath(fhir_message)

                                fhir_data = self.storage_client.read(
                                    blob_url,
                                    batch_container_client,
                                    filename,
                                    self.queue_client,
                                    retry_count)
                                if fhir_data is None:
                                    continue

                                is_normalization_fail = False
                                resource_data_dictionary = None

                                audit_data_json = None
                                try:
                                    try:
                                        (process_data,
                                        fhir_data_df,
                                        array_counts_df,
                                        audit_data_json) = self.get_processed_data(
                                                            fhir_data=fhir_data,
                                                            fhir_resource_type=fhir_resource_type,
                                                            blob_url=blob_url,
                                                            filepath_id=filepath_id)
                                        lineage_data_json = {}

                                        try:
                                            if self.project_configurations["default_value"]["is_audit"] == "True":
                                                self.queue_client.insert_to_audit_queue(audit_data_json, 'fhir_audit')
                                        except Exception:
                                            logging.exception("(filepath_id=%s): Failed to send audit message, continuing processing", filepath_id)

                                        if not process_data:
                                            logging.debug("(filepath_id=%s): Received only duplicate data. No normalization required", filepath_id)

                                        else:
                                            resource_data_dictionary = self.normalizer(
                                                fhir_resource_type, process_data, fhir_data_df, filepath_id
                                            )

                                            logging.info('(filepath_id=%s): Normalization complete', filepath_id)

                                    except DataProcessingException as dpe:
                                        logging.exception('(filepath_id=%s): Error %s and moving file to failure',
                                                          filepath_id, PipelineErrorCode.NORMALIZATION_FAILED.value)
                                        reject_filepath, blob_url = dpe.data_processing_error(fhir_message_dict,
                                                                                    filename,
                                                                                    self.storage_client)
                                        is_normalization_fail = True

                                        retry_message_dict = {}

                                        if self.project_configurations["initialization"]["cloud_storage"].lower() == "azure":
                                            retry_message_dict = {"url":f"{self.project_configurations['azure.cloud_storage']['baseurl']}{self.project_configurations['azure.cloud_storage']['failure_container']}/{reject_filepath}",
                                                                "error_code":PipelineErrorCode.NORMALIZATION_FAILED.value,
                                                                "filepath_id": filepath_id,
                                                                    "request_time":str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))}
                                        # need to add aws related retry message dict creation here

                                        self.queue_client.insert_to_reject_queue(retry_message_dict)

                                        self.queue_client.insert_to_audit_queue(audit_data_json, 'fhir_audit')

                                        lineage_data_json = Handlers.get_lineage_message(audit_data_json,
                                                                                is_insert = False,
                                                                                retry_count= 0,
                                                                                error_code = PipelineErrorCode.NORMALIZATION_FAILED.value,
                                                                                reject_location = reject_filepath)

                                    if not is_normalization_fail and resource_data_dictionary:
                                        complex_dtypes = CoreLoadProcessor.get_deletion_attributes()[
                                            fhir_resource_type
                                        ]

                                        try:
                                            self.streamloader(
                                                filename,
                                                filepath_id,
                                                resource_data_dictionary,
                                                complex_dtypes,
                                                array_counts_df
                                            )

                                            lineage_data_json = Handlers.get_lineage_message(audit_data_json,
                                                                                            is_insert = True,
                                                                                            retry_count=None,
                                                                                            error_code=None,
                                                                                            reject_location=None)
                                        except DataProcessingException as dpe:
                                            logging.exception('(filepath_id=%s): Error %s and moving file to failure',
                                                              filepath_id, PipelineErrorCode.INSERTION_FAILED.value)


                                            reject_filepath, blob_url = dpe.data_processing_error(fhir_message_dict,
                                                                                    filename,
                                                                                    self.storage_client)

                                            retry_message_dict = {}

                                            if self.project_configurations["initialization"]["cloud_storage"].lower() == "azure":
                                                retry_message_dict = {"url":f"{self.project_configurations['azure.cloud_storage']['baseurl']}{self.project_configurations['azure.cloud_storage']['failure_container']}/{reject_filepath}",
                                                                      "error_code":PipelineErrorCode.INSERTION_FAILED.value,
                                                                      "filepath_id": filepath_id,
                                                                        "request_time":str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))}

                                            # need to add aws related retry message dict creation here

                                            self.queue_client.insert_to_reject_queue(retry_message_dict)

                                            lineage_data_json = Handlers.get_lineage_message(
                                                                    audit_data_json,
                                                                    is_insert = False,
                                                                    retry_count = 0,
                                                                    error_code = PipelineErrorCode.INSERTION_FAILED.value,
                                                                    reject_location = reject_filepath)

                                    else:
                                        if is_normalization_fail:
                                            pass
                                        else:
                                            """If all records are duplicate/ outdated
                                            then data was already inserted before.
                                            Hence, flag is True """

                                            lineage_data_json = Handlers.get_lineage_message(audit_data_json,
                                                                                            is_insert = True,
                                                                                            retry_count=None,
                                                                                            error_code=None,
                                                                                            reject_location=None)

                                    try:
                                        if self.project_configurations["default_value"]["is_lineage"] == "True":
                                            self.queue_client.insert_to_audit_queue(lineage_data_json, 'fhir_lineage')
                                    except Exception:
                                        logging.exception("(filepath_id=%s): Failed to send lineage message", filepath_id)

                                except Exception:
                                    logging.exception("(filepath_id=%s): Unexpected error processing message.", filepath_id)
                                    reject_filepath = None
                                    try:
                                        reject_filepath = self.storage_client.copy_ndjson_to_failure(filename, blob_url, PipelineErrorCode.UNEXPECTED_ERROR.value)
                                    except Exception:
                                        logging.exception("(filepath_id=%s): Failed to move blob to failure during error recovery", filepath_id)
                                    # Write lineage record for observability — no retry for 699
                                    try:
                                        if audit_data_json is not None and self.project_configurations["default_value"]["is_lineage"] == "True":
                                            lineage_699 = Handlers.get_lineage_message(
                                                audit_data_json,
                                                is_insert=False,
                                                retry_count=None,
                                                error_code=PipelineErrorCode.UNEXPECTED_ERROR.value,
                                                reject_location=reject_filepath)
                                            self.queue_client.insert_to_audit_queue(lineage_699, 'fhir_lineage')
                                    except Exception:
                                        logging.exception("(filepath_id=%s):Failed to send %s lineage message", filepath_id, PipelineErrorCode.UNEXPECTED_ERROR.value)
                                    continue

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
                logging.exception("Exception during core load processing")
                raise

            break  # inner while exited cleanly (shutdown), exit outer loop

        logging.info("Exiting core load processing loop")

    def streamloader(
        self,
        filename:str,
        filepath_id: str,
        resource_data_dictionary,
        complex_dtypes,
        array_counts_df=None):
        """
        Insert data into resource specific and common tables

        Args:
            filename: Incoming filename
            resource_data_dictionary: Dictionary of dataframes with data to be inserted
            complex_dtypes: attributes (or field_names) to be deleted from common tables
        """

        transaction_labels_array = []
        is_prepared_array = []
        tables = []
        try:
            http_session = requests.Session()
            http_session.auth = (
                self.project_configurations["silver_layer"]["username"],
                self.project_configurations["silver_layer"]["password"],
            )
        except Exception as e:
            raise DataProcessingException(
                f"(filepath_id={filepath_id}): Failed to create HTTP session for stream load",
                str(e), PipelineErrorCode.INSERTION_FAILED.value
            ) from e
        try:
            for key, normalized_dataframe in resource_data_dictionary.items():
                db_columns = normalized_dataframe.columns.tolist()
                if "resourceType" in db_columns:
                    db_columns.remove("resourceType")
                    normalized_dataframe = normalized_dataframe.drop(
                        "resourceType", axis=1
                    )
                processed_dataframe = DFOps.process_dataframe(
                    key, normalized_dataframe
                )
                DFOps.rename_column(
                    processed_dataframe, "extension_extension", "extension"
                )

                if processed_dataframe.empty:
                    logging.info(
                        "(filepath_id=%s): Skipping data insertion for dataframe %s, received empty dataframe",
                        filepath_id, key.lower(),
                    )

                else:
                    if not array_counts_df.empty:
                        # check to see if array counts has meta columns, if present we are ignoring these
                        if "meta_source" in array_counts_df.columns:
                            array_counts_df = array_counts_df.drop(columns=["meta_source"])
                        if "meta_lastupdated" in array_counts_df.columns:
                            array_counts_df = array_counts_df.drop(columns=["meta_lastupdated"])
                        processed_dataframe = pd.merge(
                            processed_dataframe, array_counts_df, on="id", how="left"
                        )

                        processed_dataframe[
                            [
                                "identifier_max_array_size_db",
                                "codeableconcept_max_array_size_db",
                                "reference_max_array_size_db",
                            ]
                        ] = processed_dataframe[
                            [
                                "identifier_max_array_size_db",
                                "codeableconcept_max_array_size_db",
                                "reference_max_array_size_db",
                            ]
                        ].fillna(
                            0
                        )

                        processed_dataframe[
                            [
                                "identifier_max_array_size_db",
                                "codeableconcept_max_array_size_db",
                                "reference_max_array_size_db",
                            ]
                        ] = processed_dataframe[
                            [
                                "identifier_max_array_size_db",
                                "codeableconcept_max_array_size_db",
                                "reference_max_array_size_db",
                            ]
                        ].astype(
                            int
                        )

                    try:
                        (is_prepared, transaction_label, table_name) = (
                            TransactionManager.transaction_block(
                                self.project_configurations,
                                key.lower(),
                                filename,
                                processed_dataframe,
                                complex_dtypes,
                                self.project_configurations["silver_layer"]["core_database"],
                                filepath_id,
                                http_session
                            )
                        )

                        transaction_labels_array.append(transaction_label)
                        is_prepared_array.append(is_prepared)
                        tables.append(table_name)
                    except DataProcessingException as e:
                        raise DataProcessingException(f"(filepath_id={filepath_id}): Stream Load Failed. {e.errors}", e, PipelineErrorCode.INSERTION_FAILED.value) from e

            transaction_labels_array = [
                x for x in transaction_labels_array if x is not None
            ]
            is_prepared_array = [x for x in is_prepared_array if x is not None]
            tables = [x for x in tables if x is not None]

            """If one of them fails, rollback the other. If both succeed, proceed with COMMIT.
            The engine guarantees that a prepared transaction can always be successfully committed."""
            if self.project_configurations["silver_layer"]["is_transaction"] == "True":
                if all(is_prepared_array):

                    for transaction_label_index, transaction_label in enumerate(
                        transaction_labels_array
                    ):
                        TransactionManager.commit_transaction(
                            self.project_configurations,
                            transaction_label,
                            tables[transaction_label_index],
                            filename,
                            filepath_id,
                            http_session,
                        )
                else:
                    logging.debug("(filepath_id=%s): Rollback started", filepath_id)
                    for transaction_label_index, transaction_label in enumerate(
                        transaction_labels_array
                    ):
                        TransactionManager.rollback_transaction(
                            self.project_configurations,
                            transaction_label,
                            tables[transaction_label_index],
                            filename,
                            filepath_id,
                            http_session,
                        )

                    # pylint: disable=line-too-long
                    raise DataProcessingException(f"(filepath_id={filepath_id}): Transaction failed. Rollback complete",
                                                   "Streamload preparation failed",
                                                    PipelineErrorCode.INSERTION_FAILED.value)
                    # pylint: enable=line-too-long

        except Exception as e:
            raise DataProcessingException(
                f"(filepath_id={filepath_id}): Stream Load Failed.", str(e), PipelineErrorCode.INSERTION_FAILED.value
            ) from e
        finally:
            http_session.close()

    def local_converter(self):
        """Local-mode pipeline: pull each resource type from HAPI, normalize, stream-load.

        Used when ``queue_client`` and ``storage_client`` are both ``None`` (local
        development with HAPI FHIR + the Hyperion Engine). Bypasses the queue/blob
        batching path entirely but runs the SAME downstream pipeline as Azure mode:
        ``get_processed_data`` → ``normalizer`` → ``streamloader`` →
        ``TransactionManager.transaction``. Avoids a separate stream-load code path,
        so any fix or improvement to the load mechanics applies to both modes.
        """
        cfg = self.project_configurations
        resource_types_raw = cfg["default_value"].get("resource_types", "")
        resource_types = [r.strip() for r in resource_types_raw.split(",") if r.strip()]
        lookback_days = int(cfg["default_value"].get("lookback_days", "30"))
        now_utc = datetime.now(timezone.utc)
        until = now_utc.isoformat()
        since = (now_utc - timedelta(days=lookback_days)).isoformat()

        for resource_type in resource_types:
            logging.info("Local mode: pulling %s [%s -> %s]", resource_type, since, until)
            resources = list(self.fhir_client.iter_resources(resource_type, since, until))
            if not resources:
                logging.info("Local mode: no %s resources in window; skipping", resource_type)
                continue

            filepath_id = str(uuid.uuid4())
            # filename with underscores so transaction_block's upsert path triggers
            filename = f"local_{resource_type}_{filepath_id}.ndjson"

            try:
                (process_data,
                 fhir_data_df,
                 array_counts_df,
                 _audit) = self.get_processed_data(
                    fhir_data=resources,
                    fhir_resource_type=resource_type,
                    blob_url=f"local://{filename}",
                    filepath_id=filepath_id,
                )

                if not process_data:
                    logging.info("Local mode: %s — all rows duplicate, skipping", resource_type)
                    continue

                resource_data_dictionary = self.normalizer(
                    resource_type, process_data, fhir_data_df, filepath_id
                )
                if not resource_data_dictionary:
                    logging.info("Local mode: %s normalization returned no tables", resource_type)
                    continue

                complex_dtypes = CoreLoadProcessor.get_deletion_attributes()[resource_type]
                self.streamloader(
                    filename,
                    filepath_id,
                    resource_data_dictionary,
                    complex_dtypes,
                    array_counts_df,
                )
                logging.info("Local mode: %s done (%d resources)", resource_type, len(resources))
            except DataProcessingException:
                logging.exception("Local mode: %s pipeline failed", resource_type)
                raise

