"""
    File to hold Fhir server related endpoint methods
"""

import logging
from datetime import datetime, timedelta

import requests

from pyfiles.db_handler.ddl_runner import (execute_sql_statement,
                                           insert_dollar_export_logger)
from pyfiles.dependencies.handlers import Handlers
from pyfiles.dependencies.utilityexception import UtilityException


class FhirServerHandler:
    """
    Class holds all endpoints related to fhir server
    """

    def __init__(self, configurations):
        self.configurations = configurations
        deployment_type = configurations["initialization"]["deployment_type"]
        if deployment_type == "local":
            self.fhir_url = self.configurations["local.fhir"]["server_url"]
        elif configurations["initialization"]["fhir_service"] == "azure":
            self.fhir_url = self.configurations["azure.fhir"]["server_url"]
        else:
            raise UtilityException(
                f"Unsupported fhir_service "
                f"'{configurations['initialization']['fhir_service']}'; "
                f"supported: 'azure' (with deployment_type=azure) or deployment_type=local"
            )

    def get_meta_data(self):
        """
        Function to get meta data from fhir server
        """
        deployment_type = self.configurations["initialization"]["deployment_type"]
        if deployment_type == "local":
            timeout = int(self.configurations["local.fhir"]["timeout_seconds"])
            response = requests.get(
                f"{self.fhir_url}/metadata",
                headers={"Accept": "application/fhir+json"},
                timeout=timeout
            )
            if response.status_code == 200:
                return response.json()

        elif self.configurations["initialization"]["fhir_service"] == "azure":
            fhir_header = Handlers.azure_fhir_header(self.configurations)
            metadata_url = f"{self.fhir_url}/metadata"
            timeout = int(self.configurations["azure.fhir"]["timeout_seconds"])

            response = requests.get(metadata_url, headers=fhir_header, timeout=timeout)
            if response.status_code == 200:
                response = response.json()
                return response

    def get_resource_list(self):
        """
        function creates the resources list to initialize the database tables
        """
        metadata = self.get_meta_data()
        resource_info = metadata.get("rest", [{}])[0].get("resource", [])
        resource_list = []
        if resource_info:
            resource_list = []
            resource_list = [resource.get("type") for resource in resource_info]
        else:
            logging.info("Meta data not initialized correctly")
        logging.info(resource_list)
        return resource_list

    def dollar_exporter(self, params):
        """
        function to invoke dollar export
        """
        try:
            dollar_export_response = None
            if self.configurations["initialization"]["fhir_service"] == "azure":

                fhir_header = Handlers.azure_fhir_header(self.configurations)

                export_url = f"{self.fhir_url}/$export"

                dollar_export_response = requests.get(
                    export_url,
                    headers=fhir_header,
                    params=params,
                    timeout=int(self.configurations["azure.fhir"]["timeout_seconds"]),
                )

                if dollar_export_response.status_code == 202:
                    return dollar_export_response.headers.get('Content-Location'), "in-progress"

                else:
                    logging.info("Dollar export invocation failed. Status Code: {response.status_code}")
                    return "Dollar export invocation failed.", "error"

        except Exception as e:
            logging.exception("Dollar exporter failed")
            raise UtilityException("Dollar exporter failed") from e

    def dollar_export_invoker(self, audit_db_connection, dollar_export_resources, start_date, end_date, interval):
        """
        function to invoke dollar export for bul loads
        """
        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
            end_date = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
            number_of_catchup_cycles = (end_date - start_date).days // interval
            number_of_cycles = 0
            current_end_date = start_date + timedelta(days=interval)
            while(number_of_cycles != number_of_catchup_cycles):
                for resource_type in dollar_export_resources:
                    print(type(start_date))
                    params = {
                        "_container":"cont-fhir-ndjson-stage",
                        "_type":f"{resource_type}",
                        "_till":f"{end_date.strftime('%Y-%m-%dT%H:%M:%S')}",
                        "_since":f"{start_date.strftime('%Y-%m-%dT%H:%M:%S')}",
                    }
                    content_location, dollar_export_status = FhirServerHandler.dollar_exporter(self, params)
                    logging.debug(f"{resource_type} -- {content_location}")
                    query, params = insert_dollar_export_logger(start_date, current_end_date, resource_type, content_location, dollar_export_status, None)
                    execute_sql_statement(audit_db_connection, query, params)
                start_date = current_end_date
                current_end_date = current_end_date + timedelta(days=interval)
                number_of_cycles = number_of_cycles + 1

        except Exception as e:
            logging.exception("Dollar export invoker Failed")
            raise UtilityException("Dollar export invoker Failed") from e

    def dollar_exporter_status(self, status_url):
        """
        function to check dollar export status
        """
        try:
            dollar_export_status_response = None
            if self.configurations["initialization"]["fhir_service"] == "azure":

                fhir_header = Handlers.azure_fhir_header(self.configurations)

                dollar_export_status_response = requests.get(
                    status_url,
                    headers=fhir_header,
                    params=status_url,
                    timeout=int(self.configurations["azure.fhir"]["timeout_seconds"]),
                )

                if dollar_export_status_response.status_code == 202:
                    return "in-progress"

                if dollar_export_status_response.status_code == 200:
                    return "complete"

            else:
                return "error"

        except Exception as e:
            logging.exception("Dollar exporter status check failed")
            raise UtilityException("Dollar exporter status check failed") from e