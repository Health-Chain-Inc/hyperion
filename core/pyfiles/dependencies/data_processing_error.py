# Standard library imports
import logging

from pyfiles.dependencies.enum import ApplicationEnums


class PipelineError(Exception):
    """Base class for hyperion-core pipeline errors.

    Library code raises subclasses of this rather than calling ``sys.exit``;
    the application entry point (``main.py``) catches and decides whether to
    exit. Tests can ``pytest.raises(PipelineError)`` instead of mocking
    ``sys.exit``.
    """


class PrerequisiteError(PipelineError):
    """Raised when a startup prerequisite (FHIR connectivity, DB pool init,
    config load, logging setup) fails. Caught at the application entry point."""


class DataProcessingException(Exception):
    """ "
    custom exception class
    """

    def __init__(self, message, errors, error_code):
        super().__init__(message)
        self.errors=errors
        self.error_code=error_code

    def fhirpullerror(self,
                      fhir_event_message: dict,
                      configurations,
                      application_name,
                      storage_client,
                      queue_client
                      ):
        logging.exception(
            "FHIR pull error (app=%s, error_code=%s, retry_count=%s): %s",
            application_name,
            self.error_code,
            fhir_event_message.get("retry_count", 0),
            self
        )
        fhir_event_message["retry_count"] = 1 + fhir_event_message.get(
            "retry_count", 0
        )

        # This exception doesn't need lineage
        # handling as the start of lineage is from pulling FHIR data

        if fhir_event_message.get("retry_message",False):

            del fhir_event_message['retry_message']

            if application_name == ApplicationEnums.EVENT_LOAD_EXPORTER.value:
                blob_path=storage_client.generate_blob_path(fhir_event_message=fhir_event_message,
                                                        error_code=self.error_code,
                                                        application_name=ApplicationEnums.EVENT_LOAD_EXPORTER.value,
                                                        filetype='json')
            else:
                blob_path=storage_client.generate_blob_path(fhir_event_message=fhir_event_message,
                                                        error_code=self.error_code,
                                                        application_name=ApplicationEnums.BATCH_LOAD_EXPORTER.value,
                                                        filetype='json')

            logging.debug('Uploading to storage (hit max retry): filepath_id=%s', fhir_event_message.get('filepath_id', 'unknown'))
            storage_client.upload_json_to_failure(
            fhir_event_message,
            blob_path
            )


        elif fhir_event_message["retry_count"] == int(
            configurations["FHIR"]["max_retry_count"]
        ):
            del fhir_event_message['retry_count']
            fhir_event_message["retry_message"] = True

            logging.debug("Adding message to retry queue")
            if application_name == ApplicationEnums.EVENT_LOAD_EXPORTER.value:
                fhir_event_message["application_name"] = ApplicationEnums.EVENT_LOAD_EXPORTER.value
            else:
                fhir_event_message["application_name"] = ApplicationEnums.BATCH_LOAD_EXPORTER.value

            queue_client.insert_to_reject_queue(
                fhir_event_message,
            )

        else:
            logging.debug("Adding message back to queue with retry count %s",
                        fhir_event_message["retry_count"])

            if application_name == ApplicationEnums.EVENT_LOAD_EXPORTER.value:
                queue_client.insert_to_event_load_queue(
                fhir_event_message, int(configurations["default_value"]["delay_time"])
            )

            else:
                queue_client.insert_to_fhir_parameter_queue(
                fhir_event_message,
            )

    def data_processing_error(self,
                              fhir_event_message: dict,
                              filename,
                              storage_client):

        blob_url = fhir_event_message.get("url", None)
        filepath_id = fhir_event_message.get("filepath_id", None)
        logging.info("Moving %s to failure (filepath_id=%s, error_code=%s)", filename, filepath_id, self.error_code)
        reject_filepath = storage_client.copy_ndjson_to_failure(
            filename = filename, blob_url = blob_url, error_code=self.error_code)

        return reject_filepath, blob_url

    # def normalization_error(self,
    #                         fhir_event_message: dict,
    #                         filename,
    #                         storage_client):

    #     blob_url=fhir_event_message.get("url", None)
    #     reject_filepath = storage_client.copy_ndjson_to_failure(
    #         filename = filename, blob_url = blob_url, error_code=self.error_code)

    #     return reject_filepath, blob_url

    # def transaction_error(self,
    #                     fhir_event_message: dict,
    #                     filename,
    #                     storage_client):
    #     blob_url=fhir_event_message.get("url", None)
    #     reject_filepath = storage_client.copy_ndjson_to_failure(
    #         filename = filename, blob_url = blob_url, error_code=self.error_code)

    #     return reject_filepath, blob_url
