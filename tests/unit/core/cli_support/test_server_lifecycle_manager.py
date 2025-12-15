import asyncio
import socket
from unittest.mock import MagicMock, patch

import pytest
from src.core.cli_support.server_lifecycle_manager import ServerLifecycleManager
from src.core.config.app_config import AppConfig


class TestServerLifecycleManager:
    @pytest.fixture
    def manager(self):
        return ServerLifecycleManager()

    @pytest.fixture
    def mock_config(self):
        config = MagicMock(spec=AppConfig)
        config.host = "127.0.0.1"
        config.port = 8000
        config.anthropic_port = None
        config.logging = MagicMock()
        config.logging.log_file = None
        config.logging.use_colors = True
        return config

    def test_is_port_in_use_true(self, manager):
        """Test is_port_in_use returns True when connection succeeds."""
        with (
            patch("socket.getaddrinfo") as mock_getaddrinfo,
            patch("socket.socket") as mock_socket_cls,
        ):

            mock_addr_info = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8000))
            ]
            mock_getaddrinfo.return_value = mock_addr_info

            mock_socket = MagicMock()
            mock_socket_cls.return_value.__enter__.return_value = mock_socket
            mock_socket.connect_ex.return_value = 0  # Success

            assert manager.is_port_in_use("127.0.0.1", 8000) is True

    def test_is_port_in_use_false(self, manager):
        """Test is_port_in_use returns False when connection fails."""
        with (
            patch("socket.getaddrinfo") as mock_getaddrinfo,
            patch("socket.socket") as mock_socket_cls,
        ):

            mock_addr_info = [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 8000))
            ]
            mock_getaddrinfo.return_value = mock_addr_info

            mock_socket = MagicMock()
            mock_socket_cls.return_value.__enter__.return_value = mock_socket
            mock_socket.connect_ex.return_value = 1  # Failure

            assert manager.is_port_in_use("127.0.0.1", 8000) is False

    def test_is_port_in_use_gaierror(self, manager):
        """Test getsocketaddrinfo error handling."""
        with patch("socket.getaddrinfo", side_effect=socket.gaierror):
            assert manager.is_port_in_use("invalid-host", 8000) is False

    def test_is_port_in_use_true_for_wildcard_host(self, manager):
        """Port checks should work even when host is 0.0.0.0."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.bind(("0.0.0.0", 0))
            server_socket.listen(1)
            port = server_socket.getsockname()[1]

            assert manager.is_port_in_use("0.0.0.0", port) is True

    def test_daemonize_unix(self, manager):
        """Test daemonization logic on Unix-like systems."""
        with (
            patch("os.name", "posix"),
            patch("os.fork", side_effect=[1, 0], create=True),
            patch("sys.exit") as mock_exit,
            patch("os.setsid", create=True) as mock_setsid,
            patch("os.umask", create=True) as mock_umask,
            patch("os.chdir") as mock_chdir,
        ):

            # First fork returns > 0 (parent) -> exit
            manager._daemonize()
            mock_exit.assert_called_with(0)

            # Reset checks for second path
            mock_exit.reset_mock()

            # Full flow: first fork=0, setsid, umask, second fork=0
            with patch("os.fork", side_effect=[0, 0], create=True):
                manager._daemonize()
                mock_chdir.assert_called_with("/")
                mock_setsid.assert_called()
                mock_umask.assert_called_with(0)
                mock_exit.assert_not_called()

    def test_handle_daemon_mode_not_requested(self, manager, mock_config):
        """Test returns False when daemon mode not requested."""
        args = MagicMock()
        args.daemon = False
        assert manager.handle_daemon_mode(args, mock_config) is False

    def test_handle_daemon_mode_missing_log_file(self, manager, mock_config):
        """Test exits when log file missing for daemon mode."""
        args = MagicMock()
        args.daemon = True
        mock_config.logging.log_file = None

        with pytest.raises(SystemExit) as exc:
            manager.handle_daemon_mode(args, mock_config)
        assert "must be specified" in str(exc.value)

    def test_handle_daemon_mode_windows(self, manager, mock_config):
        """Test Windows daemon mode implementation."""
        args = MagicMock()
        args.daemon = True
        mock_config.logging.log_file = "proxy.log"

        with (
            patch("os.name", "nt"),
            patch("sys.argv", ["script.py", "--daemon", "--other"]),
            patch("sys.executable", "python.exe"),
            patch("subprocess.Popen") as mock_popen,
            patch("time.sleep"),
            patch("sys.exit") as mock_exit,
        ):

            assert manager.handle_daemon_mode(args, mock_config) is True

            # Check command construction
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == "python.exe"
            assert "-m" in call_args
            assert "src.core.cli" in call_args
            assert "--daemon" not in call_args
            assert "--other" in call_args

            mock_exit.assert_called_with(0)

    def test_check_ports_available(self, manager, mock_config):
        """Test check_ports passes when ports are available."""
        with patch.object(manager, "is_port_in_use", return_value=False):
            manager.check_ports(mock_config)

    def test_check_ports_main_in_use(self, manager, mock_config):
        """Test check_ports raises SystemExit when main port is in use."""
        with (
            patch.object(manager, "is_port_in_use", side_effect=[True]),
            pytest.raises(SystemExit),
        ):
            manager.check_ports(mock_config)

    def test_check_ports_anthropic_in_use(self, manager, mock_config):
        """Test check_ports raises SystemExit when Anthropic port is in use."""
        mock_config.anthropic_port = 8001
        with (
            patch.object(manager, "is_port_in_use", side_effect=[False, True]),
            pytest.raises(SystemExit),
        ):
            manager.check_ports(mock_config)

    @pytest.mark.asyncio
    async def test_start_servers(self, manager, mock_config):
        """Test starting servers."""
        app = MagicMock()
        mock_config.anthropic_port = None

        with patch("uvicorn.Server") as mock_server_cls:
            mock_server_instance = MagicMock()
            mock_server_cls.return_value = mock_server_instance
            mock_server_instance.serve.return_value = asyncio.Future()
            mock_server_instance.serve.return_value.set_result(None)

            await manager.start_servers(app, mock_config)

            mock_server_cls.assert_called_once()
            # Verify config
            config_call = mock_server_cls.call_args[0][0]  # uvicorn.Config
            assert config_call.app == app
            assert config_call.host == mock_config.host
            assert config_call.port == mock_config.port

    @pytest.mark.asyncio
    async def test_start_servers_with_anthropic(self, manager, mock_config):
        """Test starting servers with Anthropic enabled."""
        app = MagicMock()
        mock_config.anthropic_port = 8001

        with (
            patch("uvicorn.Server") as mock_server_cls,
            patch(
                "src.core.cli_support.server_lifecycle_manager.create_anthropic_app_async"
            ) as mock_create_anthropic,
        ):

            mock_create_anthropic.return_value = MagicMock()

            mock_server_instance = MagicMock()
            mock_server_cls.return_value = mock_server_instance
            mock_server_instance.serve.return_value = asyncio.Future()
            mock_server_instance.serve.return_value.set_result(None)

            await manager.start_servers(app, mock_config)

            assert mock_server_cls.call_count == 2
            mock_create_anthropic.assert_called_once_with(mock_config, built_app=app)
