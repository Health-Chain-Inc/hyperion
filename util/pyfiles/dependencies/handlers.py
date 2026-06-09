# Standard library imports
import json
import logging
import sys
import requests
from sqlalchemy import text
from datetime import datetime
from dateutil import parser as datetime_parser

# Third-party imports
from dotenv import load_dotenv
load_dotenv()

class Handlers:
    """Python Class containing handler functions"""

    def __init__(self):
        pass

    @staticmethod
    def logging_configuration(excluded_filenames: list, log_level_str):
        """
        function to initialize logging configurations
        """
        try:
            # Default to INFO when env var is unset or unrecognized;
            # getattr(logging, None, ...) raises TypeError on Python 3.
            level_name = (log_level_str or "INFO").upper()
            log_level = getattr(logging, level_name, logging.INFO)

            logging.basicConfig(
                level=log_level,
                format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
                handlers=[logging.StreamHandler()],
            )

            handler = logging.getLogger().handlers[0]
            handler.addFilter(lambda record: record.filename not in excluded_filenames)
        except Exception:
            logging.exception("Logging configuration failed")
            sys.exit()

    @staticmethod
    def get_azure_fhir_token(configurations):
        """Generate bearer token"""
        body = {
            "client_id": configurations['azure.fhir']['client_id'],
            "client_secret": configurations['azure.fhir']['client_secret'],
            "scope": configurations['azure.fhir']['scope'],
            "grant_type": configurations['azure.fhir']['grant_type'],
        }
        header = {"Accept": "*/*", "Connection": "keep-alive"}
        tokenurl = configurations['azure.fhir']['token_url']
        timeout = int(configurations['azure.fhir']['timeout_seconds'])
        try:
            response = requests.post(tokenurl, data=body, headers=header, timeout=timeout)

            if response.status_code == 200:
                response_json = response.json()
                return response_json.get("access_token")

            logging.error("Failed to get token, status code: %s", response.status_code)
            raise Exception(f"Failed to get token: {response.text}")

        except Exception as e:
            logging.error("Error getting FHIR token: %s", str(e))
            raise

    @staticmethod
    def azure_fhir_header(configurations):
        """generate FHIR header"""
        token = Handlers.get_azure_fhir_token(configurations)
        header = {
            "Accept": "application/fhir+json",
            "Prefer": "respond-async",
            "Authorization": "Bearer " + token,
        }
        return header

    @staticmethod
    def local_fhir_connectivity_check(configurations):
        """Check HAPI FHIR server connectivity for local deployments"""
        try:
            server_url = configurations["local.fhir"]["server_url"]
            timeout = int(configurations["local.fhir"]["timeout_seconds"])
            response = requests.get(
                f"{server_url}/metadata",
                headers={"Accept": "application/fhir+json"},
                timeout=timeout
            )
            if response.status_code == 200:
                logging.info("HAPI FHIR Server connection successful")
                return
            logging.error("HAPI FHIR Server connection failed with status: %s", response.status_code)
            sys.exit()
        except Exception as e:
            logging.error("HAPI FHIR connectivity check failed: %s", str(e))
            sys.exit()

    @staticmethod
    def fhir_connectivity_check(configurations):
        deployment_type = configurations["initialization"]["deployment_type"]
        if deployment_type == "local":
            Handlers.local_fhir_connectivity_check(configurations)
        elif configurations["initialization"]["fhir_service"] == "azure":
            try:
                fhir_header = Handlers.azure_fhir_header(configurations)
                timeout = int(configurations["azure.fhir"]["timeout_seconds"])
                response = requests.get(
                    configurations['azure.fhir']['server_url'],
                    headers=fhir_header,
                    timeout=timeout
                )
                if response.status_code == 200:
                    logging.info("FHIR Server connection successful")
                    return "Success"
                logging.error(f"FHIR Server connection unsuccessful, status: {response.status_code}")
                sys.exit()
            except Exception as e:
                logging.error(f"FHIR Server connection unsuccessful: {str(e)}")
                sys.exit()
        else:
            logging.error(
                "Unsupported fhir_service '%s'; supported: 'azure' (with deployment_type=azure) or deployment_type=local",
                configurations["initialization"]["fhir_service"],
            )
            sys.exit()

    @staticmethod
    def get_silver_layer_core_connection_parameters(configurations):
        """Returns starrocks parameters"""
        return (
            f"{configurations['silver_layer']['username']}:{configurations['silver_layer']['password']}@"
            f"{configurations['silver_layer']['query_server']}/{configurations['silver_layer']['catalog']}."
            f"{configurations['silver_layer']['core_database']}"
        )

    @staticmethod
    def get_silver_layer_audit_connection_parameters(configurations):
        """Returns starrocks parameters"""
        return (
            f"{configurations['silver_layer']['username']}:{configurations['silver_layer']['password']}@"
            f"{configurations['silver_layer']['query_server']}/{configurations['silver_layer']['catalog']}."
            f"{configurations['silver_layer']['audit_database']}"
        )

    @staticmethod
    def get_database_connection_parameters(configurations, db_name):
        """Returns starrocks parameters"""
        if db_name:
            return (
                f"{configurations['silver_layer']['username']}:{configurations['silver_layer']['password']}@"
                f"{configurations['silver_layer']['query_server']}/{configurations['silver_layer']['catalog']}."
                f"{db_name}"
            )
        return (
                f"{configurations['silver_layer']['username']}:{configurations['silver_layer']['password']}@"
                f"{configurations['silver_layer']['query_server']}"
            )

    @staticmethod
    def get_database_parameters(configurations):
        """Returns starrocks parameters"""
        return {
            "database": configurations['silver_layer']['database'],
            "user": configurations['silver_layer']['username'],
            "password": configurations['silver_layer']['password'],
            "host": configurations['silver_layer']['query_server'],
            "port": configurations['silver_layer']['port']
        }

    @staticmethod
    def get_resource_fhir_url(fhir_event_dict: dict) -> str:
        return "https://" + fhir_event_dict.get("subject", None)

    @staticmethod
    def get_configuration_file(resource_name):
        with open(f"configurations/{resource_name}.json", "r") as file:
            return json.load(file)

    @staticmethod
    def json_reader(file_name: str) -> dict:
        """
        schema generator
        """
        try:
            logging.info("Reading schema file")
            logging.info("FileName %s", file_name)
            with open(file_name, "r", encoding="utf-8") as file:
                fhir_schema_json = json.load(file)
            return fhir_schema_json

        except Exception as e:
            logging.error("Failed to read json file")
            logging.error(str(e))
            return None

    @staticmethod
    def get_last_export_time(audit_db_connection, start_date, resource_type) -> datetime:
        """
        function to fetch last sync date time
        """
        max_sync_date = None
        last_sync_date_sql = f"SELECT MAX(till_date_time) FROM dollar_export_logger where resource_type = '{resource_type}'"
        with audit_db_connection.connect() as con:
            result = con.execute(text(last_sync_date_sql))
            max_sync_date = result.fetchone()[0]


        if not max_sync_date:
            logging.info("SYNC PROCESS INVOKED FOR THE FIRST TIME")
            max_sync_date = datetime_parser.parse(
                start_date
            )
        return max_sync_date