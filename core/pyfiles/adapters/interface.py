from abc import ABC, abstractmethod


class ServiceBusMessageQueueClient(ABC):
    @abstractmethod
    def get_batch_queue_receiver(self):
        pass

    @abstractmethod
    def get_event_queue_receiver(self):
        pass

    @abstractmethod
    def get_parameter_queue_receiver(self):
        pass

    @abstractmethod
    def get_parameter_queue_sender(self):
        pass

    @abstractmethod
    def get_audit_queue_receiver(self):
        pass

    @abstractmethod
    def get_retry_queue_receiver(self):
        pass

    @abstractmethod
    def receive_messages(self, receiver, max_message_count, max_wait_time):
        pass

    @staticmethod
    @abstractmethod
    def read_message_body(message):
        pass

    @staticmethod
    @abstractmethod
    def complete_message(receiver, queue_name, message):
        pass

    @staticmethod
    @abstractmethod
    def get_ndjson_filepath(message):
        pass

    @staticmethod
    @abstractmethod
    def send_single_message(sender, message):
        pass

    @staticmethod
    @abstractmethod
    def send_scheduled_single_message(sender, message, delay_time):
        pass

    @abstractmethod
    def insert_to_reject_queue(self, message):
        pass

    @abstractmethod
    def insert_to_audit_queue(self, message, table_name):
        pass

    @abstractmethod
    def insert_to_event_load_queue(self, message, delay_time):
        pass

    @abstractmethod
    def insert_to_batch_load_queue(self, message, scheduled, delay_time):
        pass

    @abstractmethod
    def insert_to_fhir_parameter_queue(self, message):
        pass

    @abstractmethod
    def get_context_safe_client(self):
        pass

    @abstractmethod
    def get_context_safe_receiver(self, receiver):
        pass


class FHIRServerClient(ABC):
    @abstractmethod
    def get_fhir_batch_export_url(self, fhir_resource, start_date, end_date):
        pass

    @abstractmethod
    def get_fhir_event_export_url(self, fhir_event_dict):
        pass

    @abstractmethod
    def check_if_update(self, fhir_event_dict):
        pass

    @abstractmethod
    def authentication(self):
        pass

    @abstractmethod
    def fhir_connectivity_check(self):
        pass

    @staticmethod
    @abstractmethod
    def fhir_get_request(session, fhir_url, authorization, timeout):
        pass

class StorageClient(ABC):
    @abstractmethod
    def generate_blob_path(self, fhir_event_message, error_code, application_name, filetype):
        pass

    @abstractmethod
    def get_staging_container_client(self):
        pass

    @abstractmethod
    def get_failure_container_client(self):
        pass

    @abstractmethod
    def get_utilities_container_client(self):
        pass

    @abstractmethod
    def get_metadata_backup_container_client(self):
        pass

    @abstractmethod
    def read(self, blob_url:str, container_client):
        pass

    @abstractmethod
    def delete(self, blob_url, container_client):
        pass

    @abstractmethod
    def upload_json_to_failure(self, json_data, blob_path):
        pass

    @abstractmethod
    def upload_ndjson_to_stage(self, resource_list, filename, folder_name):
        pass

    # @abstractmethod
    # def move_ndjson_to_failure(
    #     self, filename, blob_url, error_code, max_retries=5, sleep_duration=6
    # ):
    #     pass