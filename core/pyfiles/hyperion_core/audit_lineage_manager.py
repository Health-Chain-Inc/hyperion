import concurrent.futures
import gc
import json
import logging
import re
import signal
import threading
import time
from datetime import datetime
from queue import Queue

import requests
from azure.servicebus.exceptions import ServiceBusConnectionError

from pyfiles.dependencies.resource_manager import ResourceManager

_DEFAULT_BATCH_SIZE = 50
_DEFAULT_FLUSH_INTERVAL = 3.0  # seconds

# Only these keys from second-half lineage messages are merged into the first-half row.
# Prevents unexpected queue message keys from overwriting authoritative DB values.
_SECOND_HALF_KEYS = {'is_inserted', 'retry_count', 'error_code', 'reject_location'}

# Filepath IDs originate as UUIDs (uuid5 of blob URL or uuid5 of resource id+versionid).
# Validate against the canonical 8-4-4-4-12 hex form before string-joining into a
# SQL IN clause. The engine HTTP /sql endpoint takes raw query text only — no
# bind-param mechanism — so application-side allowlist validation is the right
# defense against any malformed or hostile filepath_id arriving via the queue.
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


class AuditLineageManager:
    """"FHIR Audit and Lineage"""
    def __init__(self,
                project_configurations,
                queue_client):
        self.queue_client = queue_client
        self.project_configurations = project_configurations
        self._session_local = threading.local()
        self._auth = (
            project_configurations["silver_layer"]["username"],
            project_configurations["silver_layer"]["password"],
        )
        self.batch_size = int(project_configurations['processing']["audit_batch_size"])
        self.flush_interval = float(project_configurations['processing']["audit_flush_interval"])

    def _get_http_session(self):
        """Return a per-thread requests.Session (requests.Session is not thread-safe)."""
        if not hasattr(self._session_local, 'session'):
            session = requests.Session()
            session.auth = self._auth
            self._session_local.session = session
        return self._session_local.session

    def run(self):
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

            futures = []

            # pylint: disable=line-too-long
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_receivers) as thread_pool:
            # pylint: enable=line-too-long
                for _ in range(concurrent_receivers):
                    future = thread_pool.submit(self.loader, message_queue, concurrent_receivers, shutdown_event)
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
        finally:
            # Drain the message queue to prevent memory accumulation
            while not message_queue.empty():
                try:
                    message_queue.get_nowait()
                except Exception:
                    break
            gc.collect()

    _label_counter = 0
    _label_lock = threading.Lock()

    @staticmethod
    def _generate_timestamp():
        """Generate a timestamp string for created_date/updated_date fields."""
        now = datetime.now()
        return now.strftime("%Y%m%dT%H%M%S") + str(
            int(now.microsecond / 1000)
        ).zfill(3)

    @classmethod
    def _generate_label_suffix(cls):
        """Thread-safe monotonic counter + timestamp for unique transaction labels."""
        with cls._label_lock:
            cls._label_counter += 1
            counter = cls._label_counter
        return f"{cls._generate_timestamp()}_{counter}"

    def _build_query_url(self):
        return (
            (
                "http://"
                + self.project_configurations["silver_layer"]["http_server"]
                + self.project_configurations["transaction_api"]["sql_query_url"]
            )
            .replace("catalog_name", self.project_configurations["silver_layer"]["catalog"])
            .replace(
                "database_name", self.project_configurations["silver_layer"]["audit_database"]
            )
        )

    def get_sql_query_result(self, query, audit_message_dict):
        try:
            query_url = self._build_query_url()

            query_headers = {
                "format": "application/json"
            }

            query_body = {
                "query": query
            }

            load_response = self._get_http_session().post(
                query_url,
                headers=query_headers,
                json=query_body,
                timeout=(10, 30),
            )

            if load_response.status_code != 200:
                logging.error(
                    "SQL query returned HTTP %s: %s",
                    load_response.status_code,
                    load_response.text[:500]
                )
                return {}, False

            response_data = {}
            for line in load_response.text.strip().split('\n'):
                if line.strip():
                    response_data.update(json.loads(line))

            return response_data, True

        except (requests.RequestException, json.JSONDecodeError, KeyError) as err:
            # Narrowly catch the transport / parse / shape errors that signal a
            # transient SQL-API failure. Programming bugs (NameError, TypeError, etc.)
            # are NOT retried — they propagate so the operator sees the real cause.
            logging.exception("Transient error executing SQL query: %s", err)
            try:
                self.queue_client.insert_schedule_message_to_audit_queue(
                    message=audit_message_dict, scheduled=True)
            except Exception:
                logging.exception("Failed to re-queue message after SQL query error")
            return {}, False

    def _batch_select_lineage(self, filepath_ids):
        """Batch SELECT for multiple filepath_ids. Returns (dict[filepath_id -> row_dict], success)."""
        try:
            query_url = self._build_query_url()
            lineage_table = 'fhir_lineage'

            # Allowlist filepath_ids to canonical UUID form before string-concatenating
            # into the SQL IN clause. Anything that arrives via the audit queue with a
            # non-UUID-shaped filepath_id is dropped here with a warning rather than
            # interpolated into SQL.
            valid_ids = [fid for fid in filepath_ids if _UUID_RE.match(str(fid) or '')]
            if len(valid_ids) != len(filepath_ids):
                logging.warning(
                    "Dropped %d filepath_id(s) with non-UUID shape before lineage SELECT",
                    len(filepath_ids) - len(valid_ids),
                )
            if not valid_ids:
                return {}, True

            id_list = ", ".join(f"'{fid}'" for fid in valid_ids)
            query = (
                f"SELECT filepath_id, resource_type, fhir_request_url, record_count, "
                f"pipeline_type, destination_location, created_date "
                f"FROM {lineage_table} WHERE filepath_id IN ({id_list})"
            )

            load_response = self._get_http_session().post(
                query_url,
                headers={"format": "application/json"},
                json={"query": query},
                timeout=(10, 30),
            )

            if load_response.status_code != 200:
                logging.error(
                    "Batch lineage SELECT returned HTTP %s: %s",
                    load_response.status_code,
                    load_response.text[:500]
                )
                return {}, False

            # Parse multi-row NDJSON: one {"meta": ...} line, then one {"data": ...} per row
            meta = None
            rows = []
            for line in load_response.text.strip().split('\n'):
                if line.strip():
                    parsed = json.loads(line)
                    if 'meta' in parsed:
                        meta = parsed['meta']
                    if 'data' in parsed:
                        rows.append(parsed['data'])

            columns = [col['name'] for col in meta] if meta else []
            lookup = {}
            for row in rows:
                row_dict = dict(zip(columns, row, strict=False))
                fid = row_dict.get('filepath_id')
                if fid:
                    lookup[fid] = row_dict

            return lookup, True

        except Exception:
            logging.exception("Error executing batch lineage SELECT")
            return {}, False

    def streamload_insert_data_get_result(self, transaction_label, audit_lineage_dict, table_name):
        """Stream load data to the engine. Returns True on success, False on failure."""
        try:
            retry_count = 0
            load_status = False

            while retry_count < 3 and not load_status:
                load_url = (
                    (
                        "http://"
                        + self.project_configurations["silver_layer"]["http_server"]
                        + self.project_configurations["transaction_api"]["stream_load_url"]
                    )
                    .replace("table_name", table_name)
                    .replace(
                        "silver_layer_database", self.project_configurations["silver_layer"]["audit_database"]
                    )
                )

                if isinstance(audit_lineage_dict, list):
                    data_to_send = audit_lineage_dict
                else:
                    data_to_send = [audit_lineage_dict]

                headers = {
                    "label": f"{transaction_label}",
                    "format": "json",
                    "Expect": "100-continue",
                    "strip_outer_array": "true",
                }

                try:
                    load_response = self._get_http_session().put(
                        load_url,
                        data=json.dumps(data_to_send),
                        headers=headers,
                        timeout=(10, 30),
                    )
                    response_data = load_response.json()
                    if response_data.get("Status") == "Success" and response_data.get("Message") == "OK":
                        load_status = True
                    logging.debug("Stream load status: %s", response_data.get("Status"))
                except (requests.exceptions.ChunkedEncodingError,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout) as e:
                    logging.warning("Stream load attempt %d/3 failed: %s — retrying",
                                    retry_count + 1, e)
                retry_count += 1

            if not load_status:
                logging.error(
                    "Stream load failed after %d attempts for table %s, label %s",
                    retry_count, table_name, transaction_label
                )
                return False

            return True

        except Exception:
            logging.exception("Error during stream load")
            return False

    def _requeue_messages(self, messages_to_requeue):
        """Requeue a list of message dicts individually."""
        for msg in messages_to_requeue:
            try:
                self.queue_client.insert_schedule_message_to_audit_queue(
                    message=msg, scheduled=True)
            except Exception:
                logging.exception("Failed to re-queue message during batch failure recovery")

    def _flush_audit_buffer(self, buffer):
        """Batch stream load all buffered fhir_audit messages."""
        if not buffer:
            return
        data_rows = [audit_lineage_dict for audit_lineage_dict, audit_lineage_dict_og in buffer]
        label_suffix = self._generate_label_suffix()
        transaction_label = f"audit_batch_{threading.get_ident()}_{label_suffix}"
        success = self.streamload_insert_data_get_result(transaction_label, data_rows, 'fhir_audit')
        if not success:
            self._requeue_messages([audit_lineage_dict_og for audit_lineage_dict, audit_lineage_dict_og in buffer])
        buffer.clear()

    def _flush_lineage_first_half_buffer(self, buffer):
        """Batch stream load all buffered first-half lineage messages (upsert, no SELECT needed)."""
        if not buffer:
            return
        data_rows = [audit_lineage_dict for audit_lineage_dict, audit_lineage_dict_og in buffer]
        label_suffix = self._generate_label_suffix()
        transaction_label = f"lineage_first_{threading.get_ident()}_{label_suffix}"
        success = self.streamload_insert_data_get_result(transaction_label, data_rows, 'fhir_lineage')
        if not success:
            self._requeue_messages([audit_lineage_dict_og for audit_lineage_dict, audit_lineage_dict_og in buffer])
        buffer.clear()

    def _flush_lineage_second_half_buffer(self, buffer):
        """Batch SELECT + merge + stream load for second-half lineage messages."""
        if not buffer:
            return

        filepath_ids = [item[0]['filepath_id'] for item in buffer]
        lookup, is_success = self._batch_select_lineage(filepath_ids)

        if not is_success:
            # Requeue all original messages with reschedule tracking
            for _, og_dict in buffer:
                og_dict['_reschedule_count'] = og_dict.get('_reschedule_count', 0) + 1
                if og_dict['_reschedule_count'] % 10 == 0:
                    logging.warning("Second-half lineage rescheduled %d times (SELECT failed): filepath_id=%s",
                                    og_dict['_reschedule_count'], og_dict.get('filepath_id', 'unknown'))
            self._requeue_messages([og_dict for _, og_dict in buffer])
            buffer.clear()
            return

        merged_rows = []
        og_dicts_for_merged = []
        for msg_dict, og_dict in buffer:
            fid = msg_dict['filepath_id']
            if fid in lookup:
                second_half = {k: v for k, v in msg_dict.items() if k in _SECOND_HALF_KEYS}
                merged = {**lookup[fid], **second_half}
                merged["__op"] = 0
                merged['updated_date'] = self._generate_timestamp()
                merged_rows.append(merged)
                og_dicts_for_merged.append(og_dict)
            else:
                # First half not yet arrived — reschedule
                try:
                    og_dict['_reschedule_count'] = og_dict.get('_reschedule_count', 0) + 1
                    if og_dict['_reschedule_count'] % 10 == 0:
                        logging.warning("Second-half lineage rescheduled %d times: filepath_id=%s",
                                        og_dict['_reschedule_count'], fid)
                    self.queue_client.insert_schedule_message_to_audit_queue(
                        message=og_dict, scheduled=True)
                except Exception:
                    logging.exception("Failed to re-queue second-half lineage message awaiting first half")

        if merged_rows:
            label_suffix = self._generate_label_suffix()
            transaction_label = f"lineage_second_{threading.get_ident()}_{label_suffix}"
            success = self.streamload_insert_data_get_result(transaction_label, merged_rows, 'fhir_lineage')
            if not success:
                self._requeue_messages(og_dicts_for_merged)

        buffer.clear()

    def _flush_all_buffers(self, audit_buffer, lineage_first_half_buffer, lineage_second_half_buffer):
        """Flush all three buffers independently. One failure does not block the others."""
        for flush_fn, buf in [
            (self._flush_audit_buffer, audit_buffer),
            (self._flush_lineage_first_half_buffer, lineage_first_half_buffer),
            (self._flush_lineage_second_half_buffer, lineage_second_half_buffer),
        ]:
            try:
                flush_fn(buf)
            except Exception:
                logging.exception("Flush failed for %s", flush_fn.__name__)
                if buf:  # only requeue if flush didn't already handle cleanup
                    self._requeue_messages([og for _d, og in buf])
                    buf.clear()

    def loader(self, messages, message_count, shutdown_event):
        logging.info('Starting Audit and Lineage load')

        # Buffers live outside the try block so they survive ServiceBus reconnections.
        # Messages are ACKed before buffering, so losing buffered messages = data loss.
        audit_buffer = []
        lineage_first_half_buffer = []
        lineage_second_half_buffer = []
        last_flush_time = time.monotonic()

        while not shutdown_event.is_set():
            try:
                raw_receiver = self.queue_client.get_audit_queue_receiver()
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
                                # Flush any remaining buffered messages before sleeping
                                self._flush_all_buffers(
                                    audit_buffer, lineage_first_half_buffer,
                                    lineage_second_half_buffer
                                )
                                last_flush_time = time.monotonic()
                                if idle_counter % 100 == 0:
                                    logging.info("No messages to process (audit-lineage-manager)")
                                time.sleep(6)
                                continue
                            idle_counter = 0

                            for message in received_message_array:
                                audit_lineage_dict_og = None
                                try:
                                    messages.put(message)
                                    self.queue_client.complete_message(
                                        receiver,
                                        raw_receiver,
                                        message)

                                    audit_lineage_dict = self.queue_client.read_message_body(message)
                                    audit_lineage_dict_og = audit_lineage_dict.copy()

                                    logging.debug("(filepath_id=%s): Received %s message",
                                        audit_lineage_dict.get('filepath_id', 'unknown'),
                                        audit_lineage_dict.get('table_name', 'unknown'))

                                    if audit_lineage_dict['table_name'] == 'fhir_audit':
                                        audit_lineage_dict["__op"] = 0
                                        audit_lineage_dict['created_date'] = self._generate_timestamp()
                                        audit_buffer.append((audit_lineage_dict, audit_lineage_dict_og))

                                    elif 'pipeline_type' in audit_lineage_dict:
                                        # First-half lineage from exporter — direct upsert via PRIMARY KEY
                                        audit_lineage_dict["__op"] = 0
                                        audit_lineage_dict['created_date'] = self._generate_timestamp()
                                        lineage_first_half_buffer.append((audit_lineage_dict, audit_lineage_dict_og))

                                    else:
                                        # Second-half lineage from ingester — needs merge with first half
                                        lineage_second_half_buffer.append(
                                            (audit_lineage_dict, audit_lineage_dict_og)
                                        )

                                    # Check size-based flush
                                    if (len(audit_buffer) >= self.batch_size
                                            or len(lineage_first_half_buffer) >= self.batch_size
                                            or len(lineage_second_half_buffer) >= self.batch_size):
                                        self._flush_all_buffers(
                                            audit_buffer, lineage_first_half_buffer,
                                            lineage_second_half_buffer
                                        )
                                        last_flush_time = time.monotonic()

                                except Exception:
                                    logging.exception(
                                        "Unexpected error processing message in thread %s",
                                        threading.get_ident()
                                    )
                                    try:
                                        requeue_body = (
                                            audit_lineage_dict_og
                                            if audit_lineage_dict_og
                                            else self.queue_client.read_message_body(message)
                                        )
                                        self.queue_client.insert_schedule_message_to_audit_queue(
                                            message=requeue_body, scheduled=True)
                                    except Exception:
                                        logging.exception("Failed to re-queue message after unexpected error")

                            # After processing all messages: time-based flush
                            if time.monotonic() - last_flush_time >= self.flush_interval:
                                self._flush_all_buffers(
                                    audit_buffer, lineage_first_half_buffer,
                                    lineage_second_half_buffer
                                )
                                last_flush_time = time.monotonic()

                        # Shutdown: flush remaining buffered messages
                        self._flush_all_buffers(
                            audit_buffer, lineage_first_half_buffer,
                            lineage_second_half_buffer
                        )

            except ValueError as e:
                if "handler has already been shutdown" in str(e).lower():
                    logging.warning("ServiceBus receiver shutdown — reconnecting. "
                                    "Unacknowledged messages will be redelivered.")
                    # Flush buffered messages before reconnecting (already ACKed)
                    self._flush_all_buffers(
                        audit_buffer, lineage_first_half_buffer,
                        lineage_second_half_buffer
                    )
                    time.sleep(2)
                    continue
                raise
            except ServiceBusConnectionError as e:
                logging.warning("ServiceBus connection lost: %s — reconnecting", e)
                # Flush buffered messages before reconnecting (already ACKed)
                self._flush_all_buffers(
                    audit_buffer, lineage_first_half_buffer,
                    lineage_second_half_buffer
                )
                time.sleep(2)
                continue
            except Exception:
                logging.exception("Exception during audit/lineage processing")
                # Flush buffered messages before re-raising (already ACKed)
                self._flush_all_buffers(
                    audit_buffer, lineage_first_half_buffer,
                    lineage_second_half_buffer
                )
                raise

            break  # inner while exited cleanly (shutdown), exit outer loop

        logging.info("Exiting audit/lineage processing loop")
