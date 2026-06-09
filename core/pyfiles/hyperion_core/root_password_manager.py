import base64
import datetime
import hashlib
import json
import os
import re
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pymysql.converters import escape_string
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pyfiles.adapters.storage_clients import AzureStorageClient
from pyfiles.hyperion_core.sidecar_init import SidecarInit

load_dotenv()

# The Hyperion Engine (StarRocks-flavored MySQL protocol) supports prepared statements
# only for SELECT in v3.2+; SET PASSWORD does not accept bound parameters. The password
# must therefore be interpolated into the DDL string. We defend with two layers:
#   1. ``_PASSWORD_ALLOWED_RE`` — allowlist on the password's character set, evaluated
#      *before* the string ever reaches SQL. A password that fails this regex is
#      rejected with a clear error rather than escaped-and-passed-through.
#   2. ``pymysql.converters.escape_string`` — applied in the call site as a second-line
#      defense for any character allowed by the regex but with quoting significance.
# Adjust ``_PASSWORD_ALLOWED_RE`` with care: relaxing it weakens the first defense.
_PASSWORD_ALLOWED_RE = re.compile(r'^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:,.<>/?]{8,128}$')

class RootPasswordManager(SidecarInit):
    def __init__(self,
                storage_client,
                logger_config,
                project_configurations):
        self.storage_client = storage_client
        super().__init__(logger_config, project_configurations)


    def pull_password_if_security_file_exists(self):
        blob_client = self.get_security_blob_client()
        key = self.get_encryption_key()

        stored_password = self.read_stored_password(blob_client, key)
        if stored_password is None:
            self.logger.info('Security file not available. Creating encrypted password.')
            self.write_encrypted_password(blob_client, self.project_configurations.get('root_password'), key)
            return self.project_configurations.get('root_password')

        return stored_password

    def get_security_blob_client(self):
        blob_path = "properties/.security"
        return self.storage_client.get_utilities_container_client().get_blob_client(blob_path)

    def get_encryption_key(self):
        salt = self.read_salt_from_properties()
        return self.generate_key_from_salt(salt)

    def read_stored_password(self, blob_client, key):
        if not blob_client.exists():
            return None
        blob_data = blob_client.download_blob().readall()
        data = json.loads(blob_data.decode("utf-8"))
        encrypted = data.get("password")
        return self.decrypt_password(encrypted, key)

    def write_encrypted_password(self, blob_client, password, key):
        encrypted = self.encrypt_password(password, key)
        json_string = json.dumps({"password": encrypted}, indent=4)
        blob_client.upload_blob(json_string, overwrite=True)
        self.logger.debug('Encrypted password written to .security')

    def check_leader_fe_and_get_password(self):
        try:
            hostname = self.get_current_hostname()
            password = self.pull_password_if_security_file_exists()
            engine = self.get_engine()
            if not engine:
                return False

            with engine.connect() as conn:
                result = conn.execute(text("SHOW FRONTENDS")).mappings().all()

            for row in result:
                if row['IP'] == hostname and row['Role'] == 'LEADER':
                    self.logger.info("This FE (%s) is the leader", hostname)
                    return password

            self.logger.debug("This FE (%s) is not the leader", hostname)
            return False

        except SQLAlchemyError as e:
            self.logger.error("Error checking FE role: %s", e)
            return False

    @staticmethod
    def read_salt_from_properties() -> str:
        # Salt is read from the environment so it is never committed to source control.
        # Set ROOT_PASSWORD_MANAGER_SALT to a random hex string (e.g. openssl rand -hex 16).
        # Every deployment should use a unique salt; changing the salt requires re-encrypting
        # the .security blob in Azure Blob Storage.
        salt = os.getenv("ROOT_PASSWORD_MANAGER_SALT")
        if not salt:
            raise ValueError(
                "ROOT_PASSWORD_MANAGER_SALT environment variable is not set; "
                "set it to a random hex string (e.g. openssl rand -hex 16)"
            )
        return salt

    @staticmethod
    def generate_key_from_salt(salt):
        return base64.urlsafe_b64encode(hashlib.sha256(salt.encode()).digest())

    @staticmethod
    def encrypt_password(password, key):
        return Fernet(key).encrypt(password.encode()).decode()

    @staticmethod
    def decrypt_password(token, key):
        return Fernet(key).decrypt(token.encode()).decode()

    def update_root_password(self):
        self.logger.info('Starting root password update process...')
        stored_password = self.check_leader_fe_and_get_password()
        if not isinstance(stored_password, str):
            self.logger.info('This FE is not the leader or password check failed. Skipping update.')
            return

        if stored_password == self.project_configurations.get('root_password'):
            self.logger.info('No password update required')
            return

        self.logger.info('Root password has changed. Proceeding with update.')
        blob_client = self.get_security_blob_client()
        key = self.get_encryption_key()

        self.write_encrypted_password(blob_client, self.project_configurations.get('root_password'), key)

        engine = self.get_engine()
        with engine.connect() as conn:
            new_password = self.project_configurations.get('root_password') or ''
            if not _PASSWORD_ALLOWED_RE.match(new_password):
                # Fail loud rather than risk SQL-injection-shaped input reaching the engine.
                # See _PASSWORD_ALLOWED_RE comment near the top of the module.
                raise ValueError(
                    'root_password contains characters outside the allowlist or has an '
                    'invalid length; refusing to issue SET PASSWORD'
                )
            escaped_password = escape_string(new_password)
            # SET PASSWORD does not accept prepared-statement parameters on the engine;
            # the password is interpolated as a literal. The two preceding defenses
            # (allowlist regex + escape_string) bound the input shape.
            conn.execute(text(f"SET PASSWORD = PASSWORD('{escaped_password}')"))
            self.logger.info('Password has been updated')

def run_password_job(logger):
    project_configurations = {
            "azure.cloud_storage":
            {
                "connection_string": os.getenv('AZURE_STORAGE_ACCOUNT_CONNECTION_STRING'),
                "utilities_container": os.getenv('AZURE_STORAGE_CONTAINER_UTILITY'),
            },
            "query_server": os.getenv('SILVER_LAYER_QUERY_SERVER'),
            "username": os.getenv('SILVER_LAYER_ROOT_USERNAME'),
            "root_password": os.getenv('SILVER_LAYER_ROOT_PASSWORD')
    }

    if os.getenv('CLOUD_STORAGE') == 'azure':
        storage_client = AzureStorageClient(project_configurations)
    else:
        logger.error("Unsupported CLOUD_STORAGE backend")
        return

    manager = RootPasswordManager(storage_client, logger, project_configurations)
    manager.update_root_password()


if __name__ == "__main__":
    logger = None
    try:
        log_path = os.getenv("FE_LOG_PATH")
        if not log_path:
            raise ValueError("FE_LOG_PATH environment variable is not set")

        cron_expression = os.getenv("ROOT_PASSWORD_MANAGER_CRON_EXPRESSION")
        if not cron_expression:
            raise ValueError("ROOT_PASSWORD_MANAGER_CRON_EXPRESSION environment variable is not set")

        logger = RootPasswordManager.setup_logger(
            name='root_password_manager_logger',
            filename=f'{log_path}/root_password_manager.log',
            level=os.getenv('LOG_LEVEL', 'DEBUG'),
            rotate=True
        )

        scheduler = BackgroundScheduler(timezone=datetime.UTC)
        scheduler.add_job(
            run_password_job,
            CronTrigger.from_crontab(cron_expression),
            id="update_root_password",
            misfire_grace_time=None,
            args=[logger]
        )
        logger.info("Root password manager cron job sidecar started.")
        scheduler.start()

        while True:
            time.sleep(1)
    except Exception as e:
        if logger:
            logger.exception(e)
        else:
            sys.stderr.write(f"Failed to initialize: {e}\n")
