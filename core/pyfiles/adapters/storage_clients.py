import json
import logging
import time
from datetime import datetime, timezone
from random import randint

from azure.storage.blob import BlobServiceClient, ExponentialRetry

from pyfiles.adapters.interface import StorageClient
from pyfiles.dependencies.enum import ApplicationEnums, PipelineErrorCode


class AzureStorageClient(StorageClient):
    def __init__(self, configurations):
        self.configurations = configurations

        retry = ExponentialRetry(
            initial_backoff=10, increment_base=4, retry_total=3
        )

        self.client = BlobServiceClient.from_connection_string(
            configurations["azure.cloud_storage"]["connection_string"], retry_policy=retry
        )

    def close(self):
        """Close the blob service client and release resources."""
        if self.client:
            try:
                self.client.close()
            except Exception as e:
                logging.warning("Error closing BlobServiceClient: %s", e)
            self.client = None

    def generate_blob_path(self, fhir_event_message, error_code, application_name, filetype):
        if application_name == ApplicationEnums.EVENT_LOAD_EXPORTER.value:
            fhir_id = fhir_event_message.get("data", {}).get(
                "resourceFhirId", randint(0, 1000000)
            )
            event_time = fhir_event_message.get("eventTime")
            if not event_time:
                event_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            try:
                formatted_timestamp = datetime.strptime(event_time[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y%m%dT%H%M%S")
            except Exception:
                logging.exception("Failed to parse event_time '%s' for fhir_id %s", event_time, fhir_id)
                raise
            blob_path = f"{error_code}/{formatted_timestamp}/{fhir_id}.{filetype}"

        else:
            try:
                if "end_time" in fhir_event_message:
                    formatted_timestamp = fhir_event_message['end_time'].replace('-', '').replace(':', '')
                    page_number = str(fhir_event_message.get('page_number', 0))
                    resource_type = fhir_event_message.get('resource_type', None)
                    blob_path = f"{error_code}/{formatted_timestamp}/{resource_type}-{page_number}.{filetype}"
                else:
                    url = fhir_event_message.get("url","")
                    url = url.replace("/","_")
                    url_array = url.split("_")
                    if len(url_array) > 2:
                        blob_path = f"{error_code}/{url_array[-2]}/{url_array[-1]}"
                    else:
                        blob_path = f"{error_code}/{url_array[-1]}"
            except Exception:
                logging.exception("Failed to generate blob path for message %s", fhir_event_message.get('url', 'unknown'))
                raise

        return blob_path

    def get_staging_container_client(self):
        """
        Function creates and returns a container client object
        """
        return self.client.get_container_client(self.configurations["azure.cloud_storage"]["ndjson_stage_container"])

    def get_failure_container_client(self):
        """
        Function creates and returns a container client object
        """
        return self.client.get_container_client(self.configurations["azure.cloud_storage"]["failure_container"])

    def get_utilities_container_client(self):
        """
        Function creates and returns a container client object
        """
        return self.client.get_container_client(self.configurations["azure.cloud_storage"]["utilities_container"])

    def get_metadata_backup_container_client(self):
        """
        Function creates and returns a container client object
        """
        return self.client.get_container_client(self.configurations["azure.cloud_storage"]["metadata_backup_container"])

    def read(self, blob_url, container_client, filename, queue_client, retry_count):
        """
        Function to read data from a container and return the data.
        On failure, re-queues with incremented retry_count or moves to failure container.
        Returns parsed JSON list on success, None on failure.
        """
        try:
            blob_path = "/".join(blob_url.split("/")[4:])
            blob_client = container_client.get_blob_client(blob_path)
            blob_data = blob_client.download_blob().readall()
            data = blob_data.decode("utf-8")
            fhir_json = [json.loads(line) for line in data.splitlines()]
            return fhir_json
        except Exception as e:
            retry_count = int(retry_count) + 1
            max_retry = int(self.configurations["FHIR"]["max_retry_count"])

            if retry_count >= max_retry:
                logging.exception("%s -> %s: Failed to read blob, max retries reached. Moving to failure container",
                                  filename, PipelineErrorCode.BLOB_READ_FAILED.value)
                self.copy_ndjson_to_failure(filename, blob_url, PipelineErrorCode.BLOB_READ_FAILED.value)
            else:
                logging.warning("%s -> %s: Failed to read blob (attempt %d/%d): %s. Re-queuing message",
                                filename, PipelineErrorCode.BLOB_READ_FAILED.value, retry_count, max_retry, e)
                fhir_event_message = {"url": blob_url, "retry_count": retry_count, "request_time": str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))}
                queue_client.insert_to_batch_load_queue(fhir_event_message)

            return None

    def delete(self, blob_url, container_client):
        """
        Function to delete blob from azure storage
        """
        blob_path = "/".join(blob_url.split("/")[4:])
        try:
            blob_client = container_client.get_blob_client(blob=blob_path)
            blob_client.delete_blob()
            logging.debug('File deleted: %s', blob_url.split('?')[0])
            return True
        except Exception:
            logging.exception("Error deleting blob")
            return False

    def upload_json_to_failure(self, json_data, blob_path):
        """
        Generic function to JSON files to Failure container. This is for event load only
        """
        try:
            failure_blob_client = self.get_failure_container_client().get_blob_client(blob=blob_path)
            json_string = json.dumps(json_data, indent=4)
            failure_blob_client.upload_blob(json_string, overwrite=True)
            blob_url = failure_blob_client.url
            logging.debug("Data successfully uploaded to: %s", blob_url.split('?')[0])
        except Exception:
            logging.exception("Error uploading json to Azure Blob Storage")
            raise

    def copy_ndjson_to_failure(
        self, filename, blob_url, error_code, max_retries=5, sleep_duration=6
    ):
        filename_cleaned = filename.split("/")[-1].replace("_", "/")
        destination_container_client = self.get_failure_container_client()

        for count in range(max_retries):
            try:
                if blob_url:
                    blob_path = "/".join(blob_url.split("/")[4:])

                    # Strip an existing 3-digit error-code prefix so re-failed blobs
                    # don't accumulate stacked paths like "601/603/event-load/...".
                    parts = blob_path.split("/", 1)
                    if parts and parts[0].isdigit() and len(parts[0]) == 3:
                        blob_path = parts[1] if len(parts) > 1 else ""

                    destination_blob_client = destination_container_client.get_blob_client(
                        f"{error_code}/{blob_path}"
                    )

                    destination_blob_client.start_copy_from_url(blob_url)
                    logging.info("Copied %s to %s",
                                 filename_cleaned,
                                 f"{self.configurations['azure.cloud_storage']['failure_container']}/{error_code}/{blob_path}")

                    return f"{error_code}/{blob_path}"

            except Exception:
                logging.exception("%s Error moving blob", filename)
                logging.error(
                    "%s Moving %s to %s failed, retrying attempt %d of %d",
                    filename,
                    filename_cleaned,
                    self.configurations["azure.cloud_storage"]["failure_container"],
                    count + 1,
                    max_retries,
                )
                time.sleep(sleep_duration)

        logging.error(
            "Failed to move %s to %s after %d retries",
            filename_cleaned,
            self.configurations["azure.cloud_storage"]["failure_container"],
            max_retries,
        )
        return None

    def upload_ndjson_to_stage(
        self, resource_list, filename, folder_name
    ):
        """
        Function to upload ndjson to azure storage staging container
        """
        if resource_list is not None:

            ndjson_content = "\n".join(
                json.dumps(record.get("resource")) for record in resource_list
            )

            blob_client = self.get_staging_container_client().get_blob_client(f"{folder_name}/{filename}")

            blob_client.upload_blob(ndjson_content, overwrite=True)

            logging.debug("File inserted to stage: %s", f"{folder_name}/{filename}")

            return True

        return False
