# Standard library imports
import logging
from datetime import datetime

# Third-party imports
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pyfiles.db_handler.queries import Queries
from pyfiles.dependencies.utilityexception import UtilityException


def execute_sql_file(
    core_database_connection, audit_database_connection, file_path, audit_flag, lineage_flag
):
    try:
        with open(file_path, "r") as sql_file:
            sql_script = sql_file.read()
            sql_script = sql_script.replace("env_replication_num", "3")

        for statement in sql_script.split(";"):
            statement = statement.strip()
            table_name = (
                statement.split("(")[0]
                .replace("CREATE TABLE IF NOT EXISTS ", "")
                .replace("`", "")
                .strip()
            )
            if statement:
                logging.info(
                    "Executing execute sql statement function for table %s", table_name
                )
                try:
                    if table_name in [
                        "fhir_lineage",
                        "fhir_audit",
                        "fhir_export_logger",
                        "pipeline_meta_info",
                        "schema_history",
                        "dollar_export_logger",
                        "file_export_logger",
                        "metadata_backup_log"
                    ]:
                        if table_name == "fhir_audit" and audit_flag.lower() == "false":
                            logging.info("Skipping fhir_audit table creation")
                        elif table_name == "fhir_lineage" and lineage_flag.lower() == "false":
                            logging.info("Skipping fhir_lineage table creation")
                        else:
                            execute_sql_statement(
                                audit_database_connection, statement
                            )

                    else:
                        execute_sql_statement(core_database_connection, statement)
                    logging.info("Created table %s", table_name)
                    db_data = {}
                    if "pipeline_meta_info" not in table_name:
                        db_data = fetch_data(
                            "schema_history",
                            "table_name",
                            table_name,
                            audit_database_connection,
                        )
                        insert_query, params = insert_or_update_schema_history(
                            table_name, "success", db_data
                        )
                        execute_sql_statement(
                            audit_database_connection, insert_query, params
                        )
                except Exception as e:
                    insert_query, params = insert_or_update_schema_history(
                        table_name, "failure", db_data
                    )
                    execute_sql_statement(
                        audit_database_connection, insert_query, params
                    )
                    logging.info(
                        "Failed to create table in database %s, exception info %s",
                        table_name,
                        str(e),
                    )

        logging.info("SQL statements executed successfully.")
        db_data = fetch_data(
            "pipeline_meta_info", "property", "meta_tables", audit_database_connection
        )
        insert_query, params = insert_or_update_pipeline_meta_info(
            "meta_tables", "success", db_data, None
        )
        execute_sql_statement(audit_database_connection, insert_query, params)

    except SQLAlchemyError as e:
        logging.info(f"Error: {e}")


def execute_sql_statement(database_connection, statement, params=None):
    try:
        with database_connection.connect() as con:
            if params:
                con.execute(text(statement), params)
            else:
                con.execute(text(statement))
            con.commit()
            logging.debug("SQL statements executed successfully.")

    except SQLAlchemyError as e:
        if "pymysql.err.OperationalError" in e.args[0] and "1050" in e.args[0]:
            logging.info("View/table Already Exists!! Skipping View/Table creation")
        elif "pymysql.err.ProgrammingError" in e.args[0] and "1007" in e.args[0]:
            logging.info("Database Already Exists!! Skipping database creation")
        elif "pymysql.err.ProgrammingError" in e.args[0] and "1064" in e.args[0]:
            logging.info("Database User Already Exists!! Skipping User creation")
        else:
            raise SQLAlchemyError from e
    except Exception as e:
        logging.info(
            "Exception while executing sql statement, exception info %s", str(e)
        )


def insert_or_update_schema_history(
    table_name, status, db_data, description=None
):
    """
    function to insert or update history table
    """
    logging.debug("Updating/creating schema history table for %s", table_name)
    queries = Queries()
    is_update = True
    db_data = db_data if db_data else {}
    params = {
        "id": db_data.get("id", 100),
        "table_name": table_name,
        "created_date": db_data.get("created_date", datetime.now()),
        "created_by": db_data.get("created_by", "hyperion"),
        "updated_date": datetime.now(),
        "version": int(db_data.get("version", 0)) + 1,
        "status": status,
        "description": description if description else db_data.get("description", None),
    }

    if not db_data:
        is_update = False
        params.pop("id")
    insert_query = queries.get_insert_query("schema_history", is_update)
    return insert_query, params


def insert_or_update_pipeline_meta_info(
    property, status, db_data, description=None
):
    """
    function to insert or update pipeline meta info table
    """
    logging.info("Updating pipeline_meta_info table for %s", property)
    queries = Queries()
    is_update = True
    db_data = db_data if db_data else {}
    params = {
        "id": db_data.get("id", 100),
        "property": property,
        "description": description if description else db_data.get("description", None),
        "status": status,
        "created_date": db_data.get("created_date", datetime.now()),
        "created_by": db_data.get("created_by", "hyperion"),
        "updated_date": datetime.now(),
    }
    if not db_data:
        is_update = False
        params.pop("id")
    insert_query = queries.get_insert_query("pipeline_meta_info", is_update)
    return insert_query, params

def insert_dollar_export_logger(
    since_date_time, till_date_time, resource_type, status_url, dollar_export_status, db_data
):
    """
    function to insert or update pipeline meta info table
    """
    logging.info("Updating/inserting data into dollar export logger table for %s", property)
    queries = Queries()
    is_update = True
    db_data = db_data if db_data else {}
    params = {
        "id": db_data.get("id", 100),
        'since_date_time': since_date_time,
        'till_date_time': till_date_time,
        'resource_type': resource_type,
        'status_url': status_url,
        'dollar_export_status': dollar_export_status
    }
    if not db_data:
        is_update = False
        params.pop("id")
    insert_query = queries.get_insert_query("dollar_export_logger", is_update)
    return insert_query, params


def fetch_data(table_name, column_name, search_value, database_connection):
    """
    Function to fetch data based on three parameters
    """
    try:
        schema_history_select = (
            f"SELECT * FROM `{table_name}` WHERE `{column_name}` = '{search_value}'"
        )
        with database_connection.connect() as con:
            result = con.execute(text(schema_history_select))
            db_data = result.mappings().fetchone()
            return db_data if db_data else {}
    except Exception as e:
        logging.exception("Fetch Data function failed!!")
        raise UtilityException("Fetch Data function failed!!") from e

def fetch_data_multiple_rows(table_name, column_name, search_value, database_connection, rows_to_fetch=10):
    """
    Function to fetch data based on three parameters
    """
    try:
        schema_history_select = (
            f"SELECT * FROM `{table_name}` WHERE `{column_name}` = '{search_value}'"
        )
        with database_connection.connect() as con:
            result = con.execute(text(schema_history_select))
            db_data = pd.DataFrame(result.fetchall(), columns=result.keys())
            return db_data
    except Exception as e:
        logging.exception("Fetch Data Multiple Rows function failed!!")
        raise UtilityException("Fetch Data Multiple Rows function failed!!") from e

def check_first_run(database_connection):
    """
    Function runs the show tables command and returns true or false based on if tables exist or not
    """
    try:
        with database_connection.connect() as con:
            logging.info("CHECKING FOR FIRST RUN SETTING")
            result = con.execute(text("SHOW TABLES;"))
            result = result.fetchall()
            existing_tables = {row[0] for row in result}
            return True if existing_tables is not None else False

    except Exception as e:
        logging.error("Error occurred while checking tables: %s", str(e))
        return False

def insert_or_update_dollar_export_logger(
    property, status, db_data, description=None
):
    """
    function to insert or update pipeline meta info table
    """
    logging.info("Updating pipeline_meta_info table for %s", property)
    queries = Queries()
    is_update = True
    db_data = db_data if db_data else {}
    params = {
        "id": db_data.get("id", None),
        "property": property,
        "description": description if description else db_data.get("description", None),
        "status": status,
        "created_date": db_data.get("created_date", datetime.now()),
        "created_by": db_data.get("created_by", "hyperion"),
        "updated_date": datetime.now(),
    }
    if not db_data:
        is_update = False
        params.pop("id")
    insert_query = queries.get_insert_query("pipeline_meta_info", is_update)
    return insert_query, params