
import logging
import sys

from utilities import Utilities


def initialize_storage_volume():
    """
    Method to initialize the database
    """
    try:
        utilities_obj = Utilities()
        utilities_obj.initialize_storage_volume()
    except Exception as e:
        logging.exception('%s', str(e))

def initialize_core_database():
    """
    Method to initialize the database
    """
    try:
        utilities_obj = Utilities()
        utilities_obj.initialize_core_database()
    except Exception as e:
        logging.exception('%s', str(e))

def initialize_audit_database():
    """
    Method to initialize the database
    """
    try:
        utilities_obj = Utilities()
        utilities_obj.initialize_audit_database()
    except Exception as e:
        logging.exception('%s', str(e))

def initialize_tables():
    """
    Method to initialize schema and create required tables
    """
    try:
        utilities_obj = Utilities()
        status = utilities_obj.create_silver_layer_schema()
        if status:
            return 'Successfully initialized schema!'
        return 'Failed to initialize schema!'
    except Exception as e:
        logging.exception('%s',str(e))

def fhir_server_and_db_check():
    try:
        utilities_obj = Utilities()
        utilities_obj.check_fhir_server_db_conn()
        logging.info("FHIR server and database check complete")
    except Exception as e:
        logging.exception('%s',str(e))

def create_admin_role(admin_role):
    try:
        utilities_obj = Utilities()
        utilities_obj.create_admin_role(admin_role)
        logging.info("Admin role created")
    except Exception as e:
        logging.exception('%s',str(e))

def create_superuser(username, password):
    try:
        utilities_obj = Utilities()
        utilities_obj.create_superuser(username, password)
        logging.info("Superuser '%s' created successfully", username)
    except Exception as e:
        logging.exception('%s',str(e))

def create_service_account_user():
    try:
        utilities_obj = Utilities()
        utilities_obj.create_service_account_user()
        logging.info("Service account user created successfully")
    except Exception as e:
        logging.exception('%s',str(e))

def activate_all_roles():
    try:
        utilities_obj = Utilities()
        utilities_obj.activate_all_roles()
        logging.info("All privileges in the system are activated for all users upon login")
    except Exception as e:
        logging.exception('%s',str(e))

def run_prerequisite_check():
    print("Running prerequisite check...")
    try:
        utilities_obj = Utilities()
        utilities_obj.check_fhir_server_db_conn()
        print("Prerequisite check complete.")
    except Exception as e:
        logging.exception("Prerequisite check failed: %s", str(e))
        sys.exit(1)


def run_bootstrap():
    """
    Non-interactive bootstrap sequence — what the Docker image runs by default.

    Provisions a fresh engine end-to-end: storage volume, core + audit databases,
    FHIR resource tables, the service-account user that hyperion-core will use
    at runtime, and activates roles on login.

    Idempotent: every step uses IF NOT EXISTS / existence checks, so re-running
    against an already-bootstrapped engine is safe.

    Admin role and superuser creation are intentionally NOT part of bootstrap
    — they need operator input and live in the interactive menu only.

    Bypasses the swallow-exception wrappers (initialize_storage_volume etc.)
    so that any failure exits non-zero — required for the parent compose's
    `depends_on: condition: service_completed_successfully` gate.
    """
    print("Running bootstrap sequence...")
    try:
        utilities_obj = Utilities()
        utilities_obj.check_fhir_server_db_conn()
        utilities_obj.initialize_storage_volume()
        utilities_obj.initialize_core_database()
        utilities_obj.initialize_audit_database()
        utilities_obj.create_silver_layer_schema()
        utilities_obj.create_service_account_user()
        utilities_obj.activate_all_roles()
        print("Bootstrap complete.")
    except SystemExit as e:
        # A library call somewhere reached for sys.exit (legacy pattern).
        # Re-raise with non-zero so docker-compose's
        # service_completed_successfully gate fails fast.
        code = e.code if isinstance(e.code, int) and e.code != 0 else 1
        logging.error("Bootstrap aborted via sys.exit; forcing non-zero exit (code=%s)", code)
        sys.exit(code)
    except Exception:
        logging.exception("Bootstrap failed")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        choice = sys.argv[1]
        if choice == "bootstrap":
            run_bootstrap()
        elif choice == "1":
            fhir_server_and_db_check()
        elif choice == "2":
            initialize_storage_volume()
        elif choice == "3":
            print("log check")
            activate_all_roles()
        elif choice == "4":
            admin_role_name = input("Enter admin role name: ").strip()
            create_admin_role(admin_role_name)
        elif choice == "5":
            username = input("Enter superuser username: ").strip()
            password = input("Enter superuser password: ").strip()
            create_superuser(username, password)
        elif choice == "6":
            create_service_account_user()
        elif choice == "7":
            initialize_core_database()
        elif choice == "8":
            initialize_audit_database()
        elif choice == "9":
            initialize_tables()
        else:
            logging.info("Invalid choice. Please try again.")

    else:
        run_prerequisite_check()

        while True:
            print("\nChoose an operation to perform:")
            print("1. Fhir Server and Database Check")
            print("2. Initialize Storage Volume")
            print("3. Activate all roles")
            print("4. Create admin role")
            print("5. Create superuser")
            print("6. Create service account user")
            print("7. Initialize Core Database")
            print("8. Initialize Audit Database")
            print("9. Create Database Tables")
            print("10. Exit!")

            choice = input("Enter your choice (1-10): ").strip()

            if choice == "1":
                fhir_server_and_db_check()
            elif choice == "2":
                initialize_storage_volume()
            elif choice == "3":
                activate_all_roles()
            elif choice == "4":
                admin_role_name = input("Enter admin role name: ").strip()
                create_admin_role(admin_role_name)
            elif choice == "5":
                username = input("Enter superuser username: ").strip()
                password = input("Enter superuser password: ").strip()
                create_superuser(username, password)
            elif choice == "6":
                create_service_account_user()
            elif choice == "7":
                initialize_core_database()
            elif choice == "8":
                initialize_audit_database()
            elif choice == "9":
                initialize_tables()
            elif choice == "10":
                logging.info("Exiting...")
                break
            else:
                logging.info("Invalid choice. Please try again.")
