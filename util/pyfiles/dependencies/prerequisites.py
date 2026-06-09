import configparser
import logging
import os

from dotenv import load_dotenv

from pyfiles.dependencies.dbconnectionpool import DBConnectionPool
from pyfiles.dependencies.handlers import Handlers
from pyfiles.dependencies.utilityexception import UtilityException

load_dotenv()


class Prerequisites:
    def __init__(self):
        """
        Prerequisites class to run all necessary checks before data processing
        """

    @staticmethod
    def configurations():
        return Prerequisites.substitute_env_variables()

    @staticmethod
    def substitute_env_variables():
        logging.debug('Getting config file ready')
        config = configparser.ConfigParser()
        config.read('config.ini')
        for section in config.sections():
            for key in config[section]:
                value = config[section][key]
                if value.startswith('${') and value.endswith('}'):
                    env_var = value[2:-1]
                    # Default to "" not None: configparser on Python 3.13+
                    # rejects None values (TypeError: option values must be strings).
                    config[section][key] = os.getenv(env_var, "")

        logging.info('Config file ready to use')
        return config

    @staticmethod
    def prerequisite_check(core_connections):
        """function to check if all settings are valid"""
        try:
            logging.info("Prerequisites check running")
            project_configurations = Prerequisites.configurations()
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
                "connectionpool.py"
            ]
        except Exception as e:
            logging.exception('Terminating execution, environment variables initialization failed')
            raise UtilityException("Environment Variables Initialization Failed") from e

        try:
            Handlers.logging_configuration(excluded_filenames, os.getenv('LOG_LEVEL'))
            logging.debug("Logging check done")
            logging.debug('Checking FHIR Server connection')
            Handlers.fhir_connectivity_check(project_configurations)
            logging.info("Database initialization/ check complete")
        except Exception as e:
            logging.exception('Terminating execution, fhir server connection failed')
            raise UtilityException("FHIR Server connectivity check failed") from e

        try:
            core_db_connection = None
            audit_db_connection = None
            if core_connections:
                core_db_connection = DBConnectionPool(project_configurations).initialize("core")
                audit_db_connection = DBConnectionPool(project_configurations).initialize("audit")
            logging.info("Database check complete")
        except Exception as e:
            logging.exception('Terminating execution, database connectivity check failed.')
            raise UtilityException("Database connectivity check failed") from e

        return project_configurations, core_db_connection, audit_db_connection
