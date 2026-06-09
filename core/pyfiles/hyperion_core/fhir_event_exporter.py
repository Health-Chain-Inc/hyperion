
import logging

import requests

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.enum import ApplicationEnums
from pyfiles.dependencies.handlers import Handlers


class FHIREventExporter:
    """
    Class to pull FHIR records
    Parameters: fhir_event_dict -> event message
    """

    def __init__(self, fhir_event_dict: dict, configurations, fhir_client, queue_client, storage_client):
        self.fhir_event_dict = fhir_event_dict
        self.configurations = configurations
        self.fhir_client = fhir_client
        self.queue_client = queue_client
        (self.fhir_resource_type,
        self.fhir_resource_url) = self.fhir_client.get_fhir_event_export_url(self.fhir_event_dict)
        self.is_update = self.fhir_client.check_if_update(self.fhir_event_dict)
        self.storage_client = storage_client

    def run(self):
        """
           main run function to process fhir event messages
        """
        self.fhir_event_pull()

    def fhir_event_pull(self):
        """
        Function to pull fhir resource based on event message
        making use of fhir id
        """
        with requests.Session() as session:
            response = None
            try:
                fhir_header = self.fhir_client.authentication()

                response = self.fhir_client.fhir_get_request(
                    session,
                    self.fhir_resource_url,
                    fhir_header,
                    int(self.configurations['FHIR']['timeout_seconds']))
                if response.status_code == 200:
                    fhir_data = response.json()

                    fhir_id = fhir_data["id"]
                    logging.info(
                        "%s - %s -> Pulled FHIR data",
                        self.fhir_resource_type,
                        fhir_id,
                    )

                    filename = f"{self.fhir_resource_type}-1.ndjson"

                    folder_name = f"event-load/{fhir_data['id']}"

                    fhir_data_list = [{"resource":fhir_data}]

                    file_uploaded = self.storage_client.upload_ndjson_to_stage(fhir_data_list, filename, folder_name)

                    if file_uploaded:

                        filepath_id = Handlers.generate_event_filepath_id(
                            fhir_data.get("id"), fhir_data.get("meta", {}).get("versionId"))

                        exporter_message = self.queue_client.get_ndjson_filepath_message(filename, folder_name)
                        exporter_message["filepath_id"] = filepath_id

                        logging.debug("Exporter: filepath_id=%s", exporter_message.get('filepath_id', 'unknown'))

                        self.queue_client.insert_to_batch_load_queue(
                            exporter_message,
                        )

                        logging.info("(filepath_id=%s): File and message inserted: %s", filepath_id, filename)

                        if self.configurations["default_value"]["is_lineage"] == "True":
                            fhir_data_json = {
                                    "resource_type": fhir_data.get("resourceType"),
                                    "fhir_request_url": self.fhir_resource_url,
                                    "record_count": 1,
                                    "pipeline_type": ApplicationEnums.EVENT_LOAD_EXPORTER.value,
                                    "filepath_id": filepath_id,
                                    "destination_location": exporter_message.get('url', None)
                                }
                            self.queue_client.insert_to_audit_queue(fhir_data_json, 'fhir_lineage')
                else:
                    error_message = f"Received {response.status_code} - error. {response.text}"
                    raise DataProcessingException(error_message, "FHIR Event Pull Error", response.status_code)

            except DataProcessingException as e:
                raise DataProcessingException(
                    "An unexpected error occurred during the data fetch process.",
                    e.errors,
                    getattr(response, 'status_code', 0)
                ) from e
            except Exception as e:
                raise DataProcessingException(
                    "An unexpected error occurred during the data fetch process.",
                    e,
                    getattr(response, 'status_code', 0)
                ) from e
