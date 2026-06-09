import configparser
import logging
import os

from dotenv import load_dotenv

from pyfiles.adapters.fhir_clients import AzureFHIRClient, HapiFhirClient
from pyfiles.dependencies.data_processing_error import PrerequisiteError
from pyfiles.dependencies.db_connection_pool import DBConnectionPool
from pyfiles.dependencies.enum import (ApplicationEnums,
                                       HyperionDBConnectionEnums)
from pyfiles.dependencies.handlers import Handlers

load_dotenv()

class Prerequisites:
    def __init__(self):
        """
        Prerequisites class to run all necessary checks before data processing
        """

    @staticmethod
    def configurations():
        """
        Function
        """
        return Prerequisites.substitute_env_variables()

    @staticmethod
    def substitute_env_variables():
        """
        Function
        """
        logging.debug("Getting config file ready")
        config = configparser.ConfigParser()
        config.read("config.ini")
        for section in config.sections():
            for key in config[section]:
                value = config[section][key]
                if value.startswith("${") and value.endswith("}"):
                    env_var = value[2:-1]
                    # Default to "" not None: configparser rejects None values
                    # with TypeError("option values must be strings").
                    config[section][key] = os.getenv(env_var, "")
                    logging.debug("Initializing section %s, key %s complete", section, key)

        logging.info("Config file ready to use")

        return config

    @staticmethod
    def prerequisite_check():
        """function to check if all settings are valid"""
        try:
            logging.info("Prerequisites check running")

            excluded_filenames = [
                "link.py",
                "management_link.py",
                "session.py",
                "_connection.py",
                "_internal.py",
                "cbs.py",
                "proactor_events.py",
                "receiver.py",
                "_pyamqp_transport.py",
                "connectionpool.py",
                "_universal.py",
                "client.py",
                "selector_events.py",
                "_link_async.py",
                "_management_link_async.py",
                "_session_async.py",
                "_cbs_async.py",
                "_receiver_async.py",
                "_connection_async.py",
                "configprovider.py",
                "endpoint.py",
                "loaders.py",
                "hooks.py",
                "utils.py",
                "parsers.py",
                "httpsession.py",
                "auth.py",
                "regions.py",
                "awsrequest.py",
                "retryhandler.py",
                "httpchecksum.py",
                "__init__.py"
            ]
            # Handlers.logging_configuration(excluded_filenames, os.getenv('LOG_LEVEL'))
            Handlers.logging_configuration(
                        excluded_filenames, 
                        os.getenv('LOG_LEVEL'),
                        log_file=f'logs/{os.getenv("APPLICATION_NAME")}.log'
            )

            if os.getenv('APPLICATION_NAME') in (ApplicationEnums.ADMIN_GRANT_MANAGER.value, ApplicationEnums.ROOT_PASSWORD_MANAGER.value):
                return None, None, None, None, None, None

            project_configurations = Prerequisites.configurations()

            core_db_conn_pool = None
            audit_db_conn_pool = None

            if project_configurations['application']['name'] == ApplicationEnums.CORE_DATA_INGESTER.value:
                core_db_conn_pool = DBConnectionPool(project_configurations, HyperionDBConnectionEnums.CORE_DB_CONNECTION.value)
            elif project_configurations['application']['name'] == ApplicationEnums.SCHEDULER.value:
                audit_db_conn_pool = DBConnectionPool(project_configurations, HyperionDBConnectionEnums.AUDIT_DB_CONNECTION.value)

            cloud_storage = project_configurations["initialization"]["cloud_storage"]
            fhir_service = project_configurations["initialization"]["fhir_service"]
            servicebus = project_configurations["initialization"]["servicebus"]

            if fhir_service == "azure":
                fhir_client = AzureFHIRClient(project_configurations)
                fhir_client.fhir_connectivity_check()
            elif fhir_service == "local":
                fhir_client = HapiFhirClient(project_configurations)
                fhir_client.fhir_connectivity_check()
            else:
                logging.warning("fhir_service=%s is not 'azure' or 'local'; skipping connectivity check", fhir_service)

            logging.info("Prerequisites check complete")
            return (
                project_configurations,
                core_db_conn_pool,
                audit_db_conn_pool,
                cloud_storage,
                fhir_service,
                servicebus,
            )
        except PrerequisiteError:
            # Already a typed prerequisite failure — let it propagate to main.py
            raise
        except Exception as err:
            logging.exception("Prerequisites check failed: %s", err)
            raise PrerequisiteError("Prerequisites check failed") from err
