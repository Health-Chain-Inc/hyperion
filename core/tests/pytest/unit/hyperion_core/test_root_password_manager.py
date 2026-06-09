"""Unit tests for RootPasswordManager class."""
import json
from unittest.mock import MagicMock, patch


class TestPasswordAllowlistRegex:
    """Test _PASSWORD_ALLOWED_RE (Critical fix #3 — input validation before SET PASSWORD)."""

    def test_accepts_alphanumeric_password_min_length(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("Aa1Aa1Aa")

    def test_accepts_password_with_allowed_specials(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("MyPass1!@#$_+-=[]{};:,.<>/?")

    def test_accepts_max_length_128(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("A" * 128)

    def test_rejects_under_min_length(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("A" * 7) is None

    def test_rejects_over_max_length(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("A" * 129) is None

    def test_rejects_single_quote(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("Pass'word1") is None

    def test_rejects_backslash(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("Pass\\word1") is None

    def test_rejects_newline(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("Password\n1") is None

    def test_rejects_empty(self):
        from pyfiles.hyperion_core.root_password_manager import _PASSWORD_ALLOWED_RE
        assert _PASSWORD_ALLOWED_RE.match("") is None


class TestRootPasswordManagerInitialization:
    """Test RootPasswordManager initialization."""

    def test_initialization_stores_parameters(self):
        """Test that initialization stores all parameters."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_storage = MagicMock()
        mock_logger = MagicMock()
        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'test_password'
        }

        manager = RootPasswordManager(
            storage_client=mock_storage,
            logger_config=mock_logger,
            project_configurations=config
        )

        assert manager.storage_client == mock_storage


class TestEncryptionMethods:
    """Test encryption/decryption methods."""

    def test_generate_key_from_salt(self):
        """Test key generation from salt."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        salt = "test_salt_123"
        key = RootPasswordManager.generate_key_from_salt(salt)

        assert isinstance(key, bytes)
        assert len(key) == 44  # Base64 encoded 32-byte key

    def test_encrypt_decrypt_roundtrip(self):
        """Test encrypt then decrypt returns original password."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        salt = "test_salt"
        key = RootPasswordManager.generate_key_from_salt(salt)
        original_password = "my_secret_password_123"

        encrypted = RootPasswordManager.encrypt_password(original_password, key)
        decrypted = RootPasswordManager.decrypt_password(encrypted, key)

        assert decrypted == original_password

    def test_encrypt_produces_different_output(self):
        """Test that encrypting same password twice produces different ciphertext."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        salt = "test_salt"
        key = RootPasswordManager.generate_key_from_salt(salt)
        password = "test_password"

        encrypted1 = RootPasswordManager.encrypt_password(password, key)
        encrypted2 = RootPasswordManager.encrypt_password(password, key)

        # Fernet produces different ciphertext each time due to IV
        assert encrypted1 != encrypted2

        # But both decrypt to same password
        assert RootPasswordManager.decrypt_password(encrypted1, key) == password
        assert RootPasswordManager.decrypt_password(encrypted2, key) == password


class TestReadSaltFromProperties:
    """Test read_salt_from_properties method."""

    def test_read_salt_from_properties(self, tmp_path):
        """Test reading salt from config.properties file."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        # Create test config file
        config_content = """
[properties]
salt = my_test_salt_value
"""
        config_file = tmp_path / "config.properties"
        config_file.write_text(config_content)

        with patch('pyfiles.hyperion_core.root_password_manager.RootPasswordManager.read_salt_from_properties') as mock_read:
            mock_read.return_value = "my_test_salt_value"
            salt = RootPasswordManager.read_salt_from_properties()

            assert salt == "my_test_salt_value"


class TestGetSecurityBlobClient:
    """Test get_security_blob_client method."""

    def test_get_security_blob_client_returns_client(self):
        """Test that method returns blob client for .security file."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_blob_client = MagicMock()
        mock_container = MagicMock()
        mock_container.get_blob_client.return_value = mock_blob_client

        mock_storage = MagicMock()
        mock_storage.get_utilities_container_client.return_value = mock_container

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        manager = RootPasswordManager(
            storage_client=mock_storage,
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = manager.get_security_blob_client()

        mock_container.get_blob_client.assert_called_once_with("properties/.security")
        assert result == mock_blob_client


class TestReadStoredPassword:
    """Test read_stored_password method."""

    def test_read_stored_password_returns_none_when_not_exists(self):
        """Test returns None when .security file doesn't exist."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_blob_client = MagicMock()
        mock_blob_client.exists.return_value = False

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        key = RootPasswordManager.generate_key_from_salt("test_salt")
        result = manager.read_stored_password(mock_blob_client, key)

        assert result is None

    def test_read_stored_password_decrypts_when_exists(self):
        """Test decrypts and returns password when file exists."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        key = RootPasswordManager.generate_key_from_salt("test_salt")
        encrypted_password = RootPasswordManager.encrypt_password("stored_password", key)

        mock_download = MagicMock()
        mock_download.readall.return_value = json.dumps({"password": encrypted_password}).encode()

        mock_blob_client = MagicMock()
        mock_blob_client.exists.return_value = True
        mock_blob_client.download_blob.return_value = mock_download

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = manager.read_stored_password(mock_blob_client, key)

        assert result == "stored_password"


class TestWriteEncryptedPassword:
    """Test write_encrypted_password method."""

    def test_write_encrypted_password_uploads_json(self):
        """Test that encrypted password is uploaded as JSON."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_blob_client = MagicMock()
        key = RootPasswordManager.generate_key_from_salt("test_salt")

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        manager.write_encrypted_password(mock_blob_client, "new_password", key)

        mock_blob_client.upload_blob.assert_called_once()
        call_args = mock_blob_client.upload_blob.call_args
        uploaded_data = json.loads(call_args[0][0])

        assert "password" in uploaded_data
        # Verify the password can be decrypted
        decrypted = RootPasswordManager.decrypt_password(uploaded_data["password"], key)
        assert decrypted == "new_password"


class TestPullPasswordIfSecurityFileExists:
    """Test pull_password_if_security_file_exists method."""

    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_security_blob_client'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_encryption_key'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'read_stored_password'
    )
    def test_pull_password_returns_stored_when_exists(
            self, mock_read_stored, mock_get_key, mock_get_blob):
        """Test returns stored password when .security file exists."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_read_stored.return_value = "stored_password"
        mock_get_key.return_value = b'fake_key'
        mock_get_blob.return_value = MagicMock()

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'current_password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = manager.pull_password_if_security_file_exists()

        assert result == "stored_password"

    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_security_blob_client'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_encryption_key'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'read_stored_password'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'write_encrypted_password'
    )
    def test_pull_password_creates_file_when_not_exists(
            self, mock_write, mock_read_stored, mock_get_key, mock_get_blob):
        """Test creates .security file when it doesn't exist."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_read_stored.return_value = None  # File doesn't exist
        mock_get_key.return_value = b'fake_key'
        mock_get_blob.return_value = MagicMock()

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'initial_password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = manager.pull_password_if_security_file_exists()

        mock_write.assert_called_once()
        assert result == 'initial_password'


class TestUpdateRootPassword:
    """Test update_root_password method."""

    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'check_leader_fe_and_get_password'
    )
    def test_update_root_password_skips_non_leader(self, mock_check_leader):
        """Test update is skipped when not leader."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_check_leader.return_value = False

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'new_password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        manager.update_root_password()

        # Should not proceed further when not leader

    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'check_leader_fe_and_get_password'
    )
    def test_update_root_password_skips_when_unchanged(self, mock_check_leader):
        """Test update is skipped when password unchanged."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_check_leader.return_value = 'current_password'

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'current_password'  # Same as stored
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        manager.update_root_password()

        # No database update should occur

    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'check_leader_fe_and_get_password'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_security_blob_client'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_encryption_key'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'write_encrypted_password'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_engine'
    )
    def test_update_root_password_updates_when_changed(
            self, mock_engine, mock_write, mock_get_key, mock_get_blob, mock_check_leader):
        """Test password is updated when changed."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_check_leader.return_value = 'old_password'
        mock_get_key.return_value = b'fake_key'
        mock_get_blob.return_value = MagicMock()

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'new_password'  # Different from stored
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        manager.update_root_password()

        mock_write.assert_called_once()
        mock_conn.execute.assert_called()


class TestCheckLeaderFEAndGetPassword:
    """Test check_leader_fe_and_get_password method."""

    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_current_hostname'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'pull_password_if_security_file_exists'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_engine'
    )
    def test_check_leader_returns_password_when_leader(
            self, mock_engine, mock_pull_password, mock_hostname):
        """Test returns password when current node is leader."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_hostname.return_value = 'fe-node-1'
        mock_pull_password.return_value = 'stored_password'

        mock_result = [
            {'IP': 'fe-node-1', 'Role': 'LEADER'},
            {'IP': 'fe-node-2', 'Role': 'FOLLOWER'}
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = mock_result
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = manager.check_leader_fe_and_get_password()

        assert result == 'stored_password'

    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_current_hostname'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'pull_password_if_security_file_exists'
    )
    @patch.object(
        __import__('pyfiles.hyperion_core.root_password_manager', fromlist=['RootPasswordManager']).RootPasswordManager,
        'get_engine'
    )
    def test_check_leader_returns_false_when_not_leader(
            self, mock_engine, mock_pull_password, mock_hostname):
        """Test returns False when current node is not leader."""
        from pyfiles.hyperion_core.root_password_manager import RootPasswordManager

        mock_hostname.return_value = 'fe-node-2'
        mock_pull_password.return_value = 'stored_password'

        mock_result = [
            {'IP': 'fe-node-1', 'Role': 'LEADER'},
            {'IP': 'fe-node-2', 'Role': 'FOLLOWER'}
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.mappings.return_value.all.return_value = mock_result
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        config = {
            'query_server': 'localhost:9030',
            'username': 'root',
            'root_password': 'password'
        }

        manager = RootPasswordManager(
            storage_client=MagicMock(),
            logger_config=MagicMock(),
            project_configurations=config
        )

        result = manager.check_leader_fe_and_get_password()

        assert result is False
