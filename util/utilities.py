import logging
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

from pyfiles.db_handler.ddl_runner import (
    check_first_run,
    execute_sql_file,
    execute_sql_statement,
    fetch_data,
    insert_or_update_pipeline_meta_info,
)
from pyfiles.db_handler.fhir_server_handler import FhirServerHandler
from pyfiles.db_handler.resource_schema_generator import \
    ResourceSchemaGenerator
from pyfiles.dependencies.dbconnectionpool import DBConnectionPool
# Local imports
from pyfiles.dependencies.handlers import Handlers
from pyfiles.dependencies.prerequisites import Prerequisites
from pyfiles.dependencies.utilityexception import UtilityException

load_dotenv()

excluded_filenames = [
    "link.py",
    "management_link.py",
    "session.py",
    "_connection.py",
    "_internal.py",
    "cbs.py",
    "proactor_events.py",
    "receiver.py",
    "_universal.py",
    "client.py",
    "connectionpool.py",
    "selector_events.py",
    "_link_async.py",
    "_management_link_async.py",
    "_session_async.py",
    "_cbs_async.py",
    "_receiver_async.py",
    "_connection_async.py",
]


class Utilities:
    """
    Utilities class acts as starting point for schema creation and data processing
    """

    def __init__(self):
        Handlers.logging_configuration(excluded_filenames, os.getenv('LOG_LEVEL'))

    def initialize(self, core_connections):
        try:
            project_configurations, core_db_connection_pool, audit_db_connection_pool = (
                Prerequisites.prerequisite_check(core_connections)
            )
            return project_configurations, core_db_connection_pool, audit_db_connection_pool
        except Exception as e:
            raise UtilityException("Initialize function failed") from e

    def check_fhir_server_db_conn(self):
        """
        function invokes the initialize function to check if the FHIR server
        and database are reachable
        """
        try:
            (_, _, _) = self.initialize(True)

        except Exception as e:
            raise UtilityException("FHIR Server connection/ database connection failed") from e

    def create_silver_layer_schema(self):
        """
        function to create database schema
        """
        try:
            (project_configurations,
            core_db_connection, audit_db_connection) = self.initialize(True)

            logging.info("Starting Schema creation app")
            first_run_flag = check_first_run(audit_db_connection)
            fsh = FhirServerHandler(project_configurations)
            resource_list = fsh.get_resource_list()
            resource_list_string = ", ".join(resource_list)

            if project_configurations["schema"]["overwrite_schema"].lower() == "false":
                if os.path.exists(project_configurations["schema"]["destination"]):
                    logging.info("Schema already exists, no need to create tables")
            else:
                logging.info("Reading profile configurations")
                logging.info("Creating resource list")
                logging.info("Successfully fetched resource list from fhir server")

                if not first_run_flag:
                    db_data = fetch_data('pipeline_meta_info', 'property', 'resource_list', audit_db_connection)
                    insert_query, params = insert_or_update_pipeline_meta_info('resource_list','success',db_data, resource_list_string)
                    execute_sql_statement(audit_db_connection, insert_query, params)

                logging.info("Resource list creation complete")

                rsg_obj = ResourceSchemaGenerator(project_configurations["schema"]["resource"],
                                                resource_list,
                                                project_configurations["schema"]["destination"],
                                                project_configurations["schema"]["common_table_schema_path"],
                                    project_configurations["silver_layer"]["replication_number"])

                if not os.path.exists(project_configurations["schema"]["destination"]):
                    rsg_obj.schema_generator()
                elif project_configurations["schema"]["overwrite_schema"].lower() == "true":
                    logging.info("Generating schema in overwrite mode")
                    rsg_obj.schema_generator()

            # database_initialization_flag will be accessible only through config file
            if project_configurations["schema"]["database_initialization_flag"].lower() == "true":
                logging.info("Initializing database tables and related dependencies")
                execute_sql_file(
                core_db_connection,
                audit_db_connection,
                project_configurations["schema"]["destination"],
                project_configurations["default_value"]["is_audit"],
                project_configurations["default_value"]["is_lineage"],
                )
            else:
                logging.info("Schema file creation complete, skipping data tables creation")

            if first_run_flag:
                db_data = fetch_data('pipeline_meta_info', 'property', 'resource_list', audit_db_connection)
                insert_query, params = insert_or_update_pipeline_meta_info('resource_list','success',db_data, resource_list_string)
                execute_sql_statement(audit_db_connection, insert_query, params)

            return True

        except Exception as e:
            logging.exception("Failed to create schema %s", str(e))
            return False

        finally:
            logging.info("DB connection closed.")

    def initialize_core_database(self):
        """
        function to initialize database, mount storage, create core and audit databases
        """
        (project_configurations,
            _, _) = self.initialize(False)

        db_connection = DBConnectionPool(project_configurations).initialize(None)

        logging.info("Creating core database")
        execute_sql_statement(db_connection, f"CREATE DATABASE {project_configurations['silver_layer']['core_database']};")

    def initialize_audit_database(self):
        """
        function to initialize database, mount storage, create core and audit databases
        """
        (project_configurations,
            _, _) = self.initialize(False)

        db_connection = DBConnectionPool(project_configurations).initialize(None)

        logging.info("Creating audit database")
        execute_sql_statement(db_connection, f"CREATE DATABASE {project_configurations['silver_layer']['audit_database']};")


    def initialize_storage_volume(self):
        """
        function to initialize database, mount storage, create core and audit databases
        """
        (project_configurations,
            _, _) = self.initialize(False)

        db_connection = DBConnectionPool(project_configurations).initialize(None)
        storage_volume_name = project_configurations["silver_layer"]["storage_volume"]

        with db_connection.connect() as con:
            result = con.execute(text("SHOW STORAGE VOLUMES;"))
            db_data = pd.DataFrame(result.fetchall(), columns=result.keys())
            for _index, row in db_data.iterrows():
                if row["Storage Volume"] == storage_volume_name.lower():
                    logging.info("Storage volume %s already exists.", storage_volume_name)
                    return

        storage_volume_query = ""
        if project_configurations["initialization"]["cloud_storage"] == "local":
            storage_volume_query = f"""
            CREATE STORAGE VOLUME {storage_volume_name}
            TYPE = S3
            LOCATIONS = ("{project_configurations['local.storage']['locations']}")
            PROPERTIES
            (
                "enabled" = "true",
                "aws.s3.endpoint" = "{project_configurations['local.storage']['endpoint']}",
                "aws.s3.region" = "{project_configurations['local.storage']['region']}",
                "aws.s3.use_aws_sdk_default_behavior" = "false",
                "aws.s3.use_instance_profile" = "false",
                "aws.s3.access_key" = "{project_configurations['local.storage']['access_key_id']}",
                "aws.s3.secret_key" = "{project_configurations['local.storage']['access_key_secret']}",
                "aws.s3.enable_ssl" = "false"
            );"""
        elif project_configurations["initialization"]["cloud_storage"] == "azure":
            if int(project_configurations["azure.storage"]["version"]) == 1:
                storage_volume_query = f"""
                CREATE STORAGE VOLUME {storage_volume_name}
                TYPE = AZBLOB
                LOCATIONS = ("{project_configurations["azure.storage"]["locations"]}")
                PROPERTIES
                (
                    "enabled" = "true",
                    "azure.blob.endpoint" = "{project_configurations["azure.storage"]["end_point"]}",
                    "azure.blob.shared_key" = "{project_configurations["azure.storage"]["access_key"]}"
                );"""
            else:
                storage_volume_query = f"""
                CREATE STORAGE VOLUME {storage_volume_name}
                TYPE = ADLS2
                LOCATIONS = ("{project_configurations["azure.storage"]["locations"]}")
                PROPERTIES (
                    "enabled" = "true",
                    "azure.adls2.endpoint" = "{project_configurations["azure.storage"]["end_point"]}",
                    "azure.adls2.shared_key" = "{project_configurations["azure.storage"]["access_key"]}"
                );"""

        else:
            raise UtilityException(
                f"Unsupported cloud_storage value "
                f"'{project_configurations['initialization']['cloud_storage']}'; "
                f"supported: 'local' or 'azure'."
            )

        logging.info("Creating/running storage volume query")
        execute_sql_statement(db_connection, storage_volume_query)

        logging.info("Setting %s as default storage volume", storage_volume_name)
        execute_sql_statement(db_connection, f"SET {storage_volume_name} AS DEFAULT STORAGE VOLUME;")

        logging.info("Setting Activate roles on login flag to True")
        execute_sql_statement(db_connection, "SET GLOBAL activate_all_roles_on_login = TRUE;")

    def create_superuser(self, username, password):
        (project_configurations,
            _, _) = self.initialize(False)

        db_connection = DBConnectionPool(project_configurations).initialize(None)
        execute_sql_statement(db_connection, f"CREATE USER '{username}' IDENTIFIED BY '{password}';")
        logging.info("Created superuser %s", username)

        while True:
            # get user input to grant roles
            user_input = input(f"Do you want to grant privileges to the superuser '{username}'? (yes/no): ").strip().lower()
            if user_input == 'yes':
                user_grant = input("Enter grant statement to execute").strip().lower()
                execute_sql_statement(db_connection, f"{user_grant};")
                logging.info("Granted roles to superuser %s", username)
            elif user_input == 'no':
                logging.info("Exiting super user grant")
                break

    # CREATE roles, databases, read and write from core and audit
    def create_service_account_user(self):
        (project_configurations,
            _, _) = self.initialize(False)

        # Reading service account user credentials from environment variables
        username = project_configurations["service_account"]["user_name"]
        password = project_configurations["service_account"]["password"]
        db_connection = DBConnectionPool(project_configurations).initialize(None)

        # Creating the user and granting required roles
        execute_sql_statement(db_connection, f"CREATE USER IF NOT EXISTS '{username}' IDENTIFIED BY '{password}';")

        execute_sql_statement(db_connection, f"GRANT ALL ON CATALOG {project_configurations['silver_layer']['catalog']} TO USER {username};")
        execute_sql_statement(db_connection, f"GRANT user_admin TO USER {username};")

        # Creating list of databases to grant access on
        database_list = [
            project_configurations["silver_layer"]["core_database"],
            project_configurations["silver_layer"]["audit_database"],
        ]

        for database in database_list:
            execute_sql_statement(db_connection, f"GRANT SELECT,INSERT,UPDATE,DELETE ON {database}.* TO {username};")

    def create_admin_role(self, admin_role):
        (project_configurations,
            _, _) = self.initialize(False)

        db_connection = DBConnectionPool(project_configurations).initialize(None)
        execute_sql_statement(db_connection, f"CREATE ROLE IF NOT EXISTS {admin_role};")
        execute_sql_statement(db_connection, f"GRANT ALL ON CATALOG {project_configurations['silver_layer']['catalog']} TO ROLE {admin_role};")
        execute_sql_statement(db_connection, f"GRANT user_admin TO ROLE {admin_role};")

    def activate_all_roles(self):
        (project_configurations,
            _, _) = self.initialize(False)
        db_connection = DBConnectionPool(project_configurations).initialize(None)
        execute_sql_statement(db_connection, "SET GLOBAL activate_all_roles_on_login = TRUE;")
