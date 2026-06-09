import logging

import requests

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.enum import ApplicationEnums
from pyfiles.dependencies.handlers import Handlers


class FHIRBatchExport:
    def __init__(
        self,
        resource_type,
        start_date,
        end_date,
        fhir_url,
        page_number,
        folder_name,
        retry_count,
        retry_message,
        fhir_client,
        storage_client,
        queue_client
    ):
        self.resource_type = resource_type
        self.start_date = start_date
        self.end_date = end_date
        self.fhir_url = fhir_url
        self.fhir_client = fhir_client
        self.storage_client = storage_client
        self.queue_client = queue_client
        if self.fhir_url is None:
            self.fhir_url = self.fhir_client.get_fhir_batch_export_url(self.resource_type, self.start_date, self.end_date)
        self.page_number = page_number
        self.next_url = None
        self.folder_name = folder_name
        self.retry_count = retry_count
        self.retry_message = retry_message

    def run(self, configurations):
        """
        function to invoke pulling fhir data
        """
        try:
            self.fhirpull(configurations)
            logging.info(
            "FHIR pull complete for resource %s with start date %s and end date %s",
            self.resource_type,
            self.start_date,
            self.end_date,
        )
        except DataProcessingException as dpe:
            try:
                parameters_message = Handlers.create_exporter_parameter_message(
                    self.resource_type,
                    self.start_date,
                    self.end_date,
                    self.page_number,
                    self.fhir_url,
                    self.retry_count,
                    self.retry_message
                )
                dpe.fhirpullerror(parameters_message, configurations, ApplicationEnums.BATCH_LOAD_EXPORTER.value, self.storage_client, self.queue_client)
            except Exception as recovery_error:
                logging.exception("Error-recovery failed for resource_type=%s, page=%s. Original error: %s. Recovery error: %s",
                                  self.resource_type, self.page_number, dpe, recovery_error)

    def fhirpull(self, configurations):
        with requests.Session() as session:
            logging.debug("Fetching FHIR data: url=%s, page=%s", self.fhir_url, self.page_number)

            fhir_header = self.fhir_client.authentication()

            response = None
            try:
                while True:
                    if not fhir_header:
                        fhir_header = self.fhir_client.authentication()

                    response = self.fhir_client.fhir_get_request(
                        session,
                        self.fhir_url,
                        fhir_header,
                        int(configurations["FHIR"]["timeout_seconds"])
                    )

                    if response.status_code == 200:
                        data = response.json()
                        resource_list = data.get("entry")

                        filename = f"{self.resource_type}-{self.page_number}.ndjson"

                        file_uploaded = self.storage_client.upload_ndjson_to_stage(resource_list, filename, self.folder_name)

                        if file_uploaded:

                            exporter_message = self.queue_client.get_ndjson_filepath_message(filename, self.folder_name)
                            filepath_id = Handlers.generate_batch_filepath_id(exporter_message.get('url'))
                            exporter_message["filepath_id"] = filepath_id

                            logging.debug("Exporter: filepath_id=%s", exporter_message.get('filepath_id', 'unknown'))

                            self.queue_client.insert_to_batch_load_queue(
                                exporter_message,
                            )

                            logging.info("File and message inserted: %s", filename)

                            # For lineage
                            if configurations["default_value"]["is_lineage"] == "True":

                                fhir_data_json = {
                                    "resource_type": self.resource_type,
                                    "fhir_request_url": self.fhir_url,
                                    "record_count": len(resource_list),
                                    "pipeline_type": ApplicationEnums.BATCH_LOAD_EXPORTER.value,
                                    "filepath_id": filepath_id,
                                    "destination_location": exporter_message.get('url', None)
                                }
                                self.queue_client.insert_to_audit_queue(fhir_data_json, 'fhir_lineage')

                        if "link" in data and data["link"] and data["link"][0]["relation"] == "next":
                            self.fhir_url = data["link"][0]["url"]
                            logging.debug("Pulled next FHIR link: %s", self.fhir_url)
                            self.page_number += 1
                        else:
                            self.fhir_url = None
                            break

                    elif response.status_code == 401:
                        logging.info("Received 401, re-authenticating")
                        fhir_header = self.fhir_client.authentication()
                        continue
                    else:
                        error_message = f'Received {response.status_code} - error. {response.text}'
                        raise DataProcessingException(error_message, "FHIR Pull Error", response.status_code)
            except DataProcessingException as dpe:
                raise DataProcessingException(f"FHIR Batch exporter failed: {dpe.errors}", dpe, getattr(response, 'status_code', 0)) from dpe
            except Exception as e:
                raise DataProcessingException("FHIR Batch exporter failed", e, getattr(response, 'status_code', 0)) from e
