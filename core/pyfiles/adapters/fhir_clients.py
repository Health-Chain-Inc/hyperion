import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pyfiles.adapters.interface import FHIRServerClient
from pyfiles.dependencies.data_processing_error import PrerequisiteError
from pyfiles.dependencies.resource_manager import ResourceManager


class AzureFHIRClient(FHIRServerClient):
    def __init__(self, project_configurations):
        self.project_configurations = project_configurations
        self.session = requests.Session()

        # Configure connection pooling with retries
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(
            pool_connections=5,
            pool_maxsize=10,
            max_retries=retry_strategy
        )
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

        # Register with ResourceManager for cleanup on shutdown
        ResourceManager().register(
            f"fhir_client_{id(self)}",
            self,
            self.close
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the HTTP session to release resources."""
        if self.session:
            self.session.close()
            self.session = None

    def get_fhir_batch_export_url(self, fhir_resource, start_date, end_date):
        """Get the FHIR Batch Export URL"""
        # pylint: disable=line-too-long
        return f"{self.project_configurations['azure.fhir']['server_url']}/{fhir_resource}?_lastUpdated=ge{start_date}&_lastUpdated=le{end_date}&_count={int(self.project_configurations['FHIR']['ndjson_file_size'])}"
        # pylint: enable=line-too-long

    def get_fhir_event_export_url(self, fhir_event_dict):
        """
        function to return fhir resource type and fhir url
        """
        return fhir_event_dict.get("subject", "").split("/")[
            -2
        ], "https://" + fhir_event_dict.get("subject", "")

    def check_if_update(self, fhir_event_dict):
        """
        function to check if event is an update
        """
        if 'Update' in fhir_event_dict.get("eventType", ""):
            return True

        return False

    def authentication(self):
        """Handle FHIR authentication and return headers"""
        body = {
            "client_id": self.project_configurations["azure.fhir"]["client_id"],
            "client_secret": self.project_configurations["azure.fhir"]["client_secret"],
            "scope": self.project_configurations["azure.fhir"]["scope"],
            "grant_type": self.project_configurations["azure.fhir"]["grant_type"],
        }
        token_url = self.project_configurations["azure.fhir"]["token_url"]

        response = self.session.post(
            token_url,
            data=body,
            headers={"Accept": "*/*", "Connection": "keep-alive"}
        )

        if response.status_code != 200:
            raise PrerequisiteError(f"Failed to get OAuth token (HTTP {response.status_code})")

        token = response.json().get("access_token")
        return {
            "Accept": "application/fhir+json",
            "Prefer": "respond-async",
            "Authorization": f"Bearer {token}"
        }

    def fhir_connectivity_check(self):
        """Check FHIR server connectivity. Raises ``PrerequisiteError`` on failure."""
        try:
            headers = self.authentication()
            response = self.session.get(
                self.project_configurations["azure.fhir"]["server_url"],
                headers=headers
            )

            if response.status_code == 200:
                logging.info("FHIR Server connection successful")
                return True

            logging.error("FHIR Server connection failed with status code: %s", response.status_code)
            raise PrerequisiteError(
                f"Azure FHIR connectivity check failed with status {response.status_code}"
            )
        except PrerequisiteError:
            raise
        except Exception as err:
            logging.exception("Azure FHIR connectivity check failed")
            raise PrerequisiteError("Azure FHIR connectivity check failed") from err

    @staticmethod
    def fhir_get_request(session, fhir_url, authorization, timeout):
        return session.get(
            fhir_url,
            headers=authorization,
            timeout=timeout
        )


class HapiFhirClient(FHIRServerClient):
    """FHIR client for HAPI FHIR servers (local development).

    No authentication; plain HTTP REST against the HAPI base URL configured
    via ``[local.fhir] server_url`` in config.ini. Local mode runs only the
    CORE_DATA_INGESTER application; methods used only by event-load and
    batch-load exporters log a warning and return ``None``.
    """

    def __init__(self, project_configurations):
        self.project_configurations = project_configurations
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            pool_connections=5,
            pool_maxsize=10,
            max_retries=retry_strategy,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        ResourceManager().register(
            f"hapi_fhir_client_{id(self)}",
            self,
            self.close,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if self.session:
            self.session.close()
            self.session = None

    def get_fhir_batch_export_url(self, fhir_resource, start_date, end_date):
        return (
            f"{self.project_configurations['local.fhir']['server_url']}"
            f"/{fhir_resource}"
            f"?_lastUpdated=ge{start_date}"
            f"&_lastUpdated=le{end_date}"
            f"&_count={int(self.project_configurations['FHIR']['ndjson_file_size'])}"
        )

    def get_fhir_event_export_url(self, fhir_event_dict):
        logging.warning("HapiFhirClient.get_fhir_event_export_url called in local mode; not supported")
        return None, None

    def check_if_update(self, fhir_event_dict):
        return False

    def authentication(self):
        return {"Accept": "application/fhir+json"}

    def fhir_connectivity_check(self):
        """Check HAPI FHIR connectivity. Raises ``PrerequisiteError`` on failure."""
        try:
            response = self.session.get(
                f"{self.project_configurations['local.fhir']['server_url']}/metadata",
                headers=self.authentication(),
                timeout=10,
            )
            if response.status_code == 200:
                logging.info("HAPI FHIR connection successful")
                return True
            logging.error("HAPI FHIR connection failed with status code: %s", response.status_code)
            raise PrerequisiteError(
                f"HAPI FHIR connectivity check failed with status {response.status_code}"
            )
        except PrerequisiteError:
            raise
        except Exception as err:
            logging.exception("HAPI FHIR connectivity check failed")
            raise PrerequisiteError("HAPI FHIR connectivity check failed") from err

    @staticmethod
    def fhir_get_request(session, fhir_url, authorization, timeout):
        return session.get(
            fhir_url,
            headers=authorization or {"Accept": "application/fhir+json"},
            timeout=timeout,
        )

    def iter_resources(self, fhir_resource, start_date, end_date, timeout=30):
        """Iterate individual FHIR resources for a resource type and time window.

        Yields one resource dict per Bundle entry. Follows ``link.next`` for pagination.
        Local-mode helper; not part of the FHIRServerClient interface.
        """
        url = self.get_fhir_batch_export_url(fhir_resource, start_date, end_date)
        headers = self.authentication()
        while url:
            response = self.session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            bundle = response.json()
            for entry in bundle.get("entry", []) or []:
                resource = entry.get("resource")
                if resource is not None:
                    yield resource
            next_url = None
            for link in bundle.get("link", []) or []:
                if link.get("relation") == "next":
                    next_url = link.get("url")
                    break
            url = next_url
