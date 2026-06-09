
import ast
import json
import logging
import math
import os
import sys
import uuid
from datetime import datetime
from urllib.parse import quote_plus

from pyfiles.dependencies.data_processing_error import PrerequisiteError
from pyfiles.dependencies.enum import HyperionDBConnectionEnums


class Handlers:
    """Python Class containing handler functions"""

    def __init__(self):
        pass

    @staticmethod
    def logging_configuration(excluded_filenames: list, log_level_str: str,
                            log_file: str = None, max_bytes: int = 10485760,
                            backup_count: int = 10):
        """
        Initialize logging configurations with custom filters and optional file rotation.

        Args:
            excluded_filenames: List of filenames to exclude from logging
            log_level_str: Log level as string (INFO, DEBUG, ERROR, etc.)
            log_file: Path to log file. If None, only console logging is used.
            max_bytes: Maximum size of log file before rotation (default: 10MB)
            backup_count: Number of backup files to keep (default: 5)
        """
        try:
            from logging.handlers import RotatingFileHandler

            logger = logging.getLogger()

            # Clear existing handlers to prevent accumulation
            if logger.handlers:
                for handler in logger.handlers[:]:
                    try:
                        handler.close()
                    except Exception:
                        logging.warning("Failed to close logging handler: %s", handler)
                    logger.removeHandler(handler)

            # Convert string to logging level, default to INFO if None or invalid
            log_level = getattr(logging, (log_level_str or 'INFO').upper(), logging.INFO)

            # Create custom filter class
            class FilenameFilter(logging.Filter):
                def __init__(self, excluded_files):
                    super().__init__()
                    self.excluded_files = set(excluded_files) if excluded_files else set()

                def filter(self, record):
                    return record.filename not in self.excluded_files

            # Create handlers list
            new_handlers = [logging.StreamHandler()]  # Console output

            # Add rotating file handler if log_file is specified
            if log_file:
                # Ensure log directory exists
                log_dir = os.path.dirname(log_file)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir, exist_ok=True)

                file_handler = RotatingFileHandler(
                    filename=log_file,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding='utf-8'
                )
                new_handlers.append(file_handler)

            # Configure logging
            logging.basicConfig(
                level=log_level,
                format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
                handlers=new_handlers,
                force=True  # Reconfigure if already configured
            )

            # Apply filter to all handlers
            filename_filter = FilenameFilter(excluded_filenames)
            for handler in logging.getLogger().handlers:
                handler.addFilter(filename_filter)

            logging.info("Logging configured at %s level", (log_level_str or 'INFO').upper())
            if log_file:
                logging.info("Log file: %s (max: %.1f MB, backups: %s)", log_file, max_bytes/1024/1024, backup_count)

        except Exception as err:
            sys.stderr.write(f"CRITICAL: Logging configuration failed - {err}\n")
            raise PrerequisiteError("Logging configuration failed") from err

    @staticmethod
    def get_silver_layer_connection_parameters(configurations, database):
        """Return the engine connection parameters string for the requested database."""
        username = quote_plus(configurations['silver_layer']['username'])
        password = quote_plus(configurations['silver_layer']['password'])
        if database == HyperionDBConnectionEnums.CORE_DB_CONNECTION.value:
            return (
                f"{username}:{password}@"
                f"{configurations['silver_layer']['query_server']}/{configurations['silver_layer']['catalog']}."
                f"{configurations['silver_layer']['core_database']}"
            )
        if database == HyperionDBConnectionEnums.AUDIT_DB_CONNECTION.value:
            return (
                    f"{username}:{password}@"
                    f"{configurations['silver_layer']['query_server']}/{configurations['silver_layer']['catalog']}."
                    f"{configurations['silver_layer']['audit_database']}"
                )

    @staticmethod
    def get_schema_file(schema_file):
        try:
            with open(schema_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logging.error("Schema file not found: %s", schema_file)
            raise
        except json.JSONDecodeError:
            logging.error("Invalid JSON in schema file: %s", schema_file)
            raise
        except Exception:
            logging.exception("Failed to read schema file: %s", schema_file)
            raise

    @staticmethod
    def json_reader(file_name: str) -> dict:
        """Load a JSON schema file, raising :class:`PrerequisiteError` on failure."""
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                fhir_schema_json = json.load(file)
            return fhir_schema_json

        except Exception as err:
            logging.exception("Failed to read json file: %s", file_name)
            raise PrerequisiteError(f"Failed to read json file: {file_name}") from err

    @staticmethod
    def fill_values(data, data_type):
        """
        Function checks the data type and fills default values if needed
        """
        if data:
            if data_type == "ARRAY<INTEGER>":
                for _, array_value in enumerate(data):
                    data[_] = None if math.isnan(array_value) else int(array_value)
            elif data_type == "ARRAY<ARRAY<INTEGER>>":
                for outer, arrays in enumerate(data):
                    for inner, array_value in enumerate(arrays):
                        data[outer][inner] = (
                            None if math.isnan(array_value) else int(array_value)
                        )

        return data

    @staticmethod
    def create_exporter_parameter_message(
        resource_type: str,
        start_time: datetime,
        end_time: datetime,
        page_number: int,
        fhir_url: str,
        retry_count: int,
        retry_message: bool
    ):
        """
        function to create message to write to service bus
        """
        try:
            return {
                "resource_type": resource_type,
                "start_time": start_time,
                "end_time": end_time,
                "request_time": str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
                "folder_name": (
                    end_time
                    .replace(":", "")
                    .replace("-", "")
                ),
                "page_number": page_number,
                "fhir_url": fhir_url,
                "retry_count": retry_count,
                "retry_message":retry_message
            }
        except Exception:
            logging.exception(
                "Failed to create exporter parameter message for resource_type=%s",
                resource_type)
            raise

    @staticmethod
    def convert_empty_strings_to_null(obj):
        if isinstance(obj, dict):
            return {k: Handlers.convert_empty_strings_to_null(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [Handlers.convert_empty_strings_to_null(elem) for elem in obj]
        if obj == "":
            return None
        return obj

    @staticmethod
    def get_lineage_message(audit_message: list|dict,
                            is_insert: bool|None,
                            retry_count: int|None,
                            error_code:str|None,
                            reject_location:str|None):
        """
        function to create lineage message from audit to write to service bus
        """
        required_keys = ["filepath_id"]
        if isinstance(audit_message, list):
            for message in audit_message:
                filtered_message = {k: message.get(k) for k in required_keys}
                break
        else:
            filtered_message = {k: audit_message.get(k) for k in required_keys}

        filtered_message['is_inserted'] = is_insert
        filtered_message['retry_count'] = retry_count
        filtered_message['error_code'] = error_code
        filtered_message['reject_location'] = reject_location
        return filtered_message


    @staticmethod
    def is_insert_flag(message: list|dict, is_insert: bool):
        required_keys = ["filepath_id"]
        if isinstance(message, list):
            for mes in message:
                filtered = {k: mes.get(k) for k in required_keys}
                filtered['is_inserted'] = is_insert
                return filtered

        else:
            filtered_message = {k: message.get(k) for k in required_keys}
            filtered_message['is_inserted'] = is_insert
            return filtered_message


    @staticmethod
    def add_retry_count(message: list|dict, retry_count):
        if isinstance(message, list):
            for mes in message:
                mes['retry_count'] = retry_count
        else:
            message['retry_count'] = retry_count

        return message

    @staticmethod
    def add_error_code(message: list|dict, error_code):
        if isinstance(message, list):
            for mes in message:
                mes['error_code'] = error_code
        else:
            message['error_code'] = error_code

        return message

    @staticmethod
    def add_reject_location(message: list|dict, reject_location):
        if isinstance(message, list):
            for mes in message:
                mes['reject_location'] = reject_location
        else:
            message['reject_location'] = reject_location

        return message

    @staticmethod
    def extract_identifier_source(identifier_str, default_source):
        try:
            identifier_dict = ast.literal_eval(f"{identifier_str}")
            source = None

            if isinstance(identifier_dict, list):
                for element in identifier_dict:
                    if 'source' in element.get("system", '').lower():
                        source = element.get("value", None)
                        break

            if isinstance(identifier_dict, dict):
                if 'source' in identifier_dict.get("system", '').lower():
                    source = identifier_dict.get("value", None)

            if source:
                return source
            return default_source
        except (ValueError, SyntaxError):
            return None

    @staticmethod
    def generate_batch_filepath_id(blob_url: str) -> str:
        """Generate filepath_id for batch loads (one per file)."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, blob_url))

    @staticmethod
    def generate_event_filepath_id(fhir_id: str, version_id: str) -> str:
        """Generate filepath_id for event loads (one per resource)."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(fhir_id) + str(version_id)))

    @staticmethod
    def run_time_check(configurations):
        """
        Function to check if the function needs to be executed or not
        """
        time_interval = int(configurations["fhir_exporter"]["time_interval"])
        current_time = datetime.now()
        current_time_mins = current_time.minute
        return (
            int(current_time_mins) % time_interval == 0
            or int(current_time_mins) % time_interval == time_interval - 1
        )
