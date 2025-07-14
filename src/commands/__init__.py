from .base import (
    BaseCommand,
    CommandResult,
    command_registry,
    create_command_instances,
    register_command,
)
from .create_failover_route_cmd import CreateFailoverRouteCommand  # noqa: F401
from .delete_failover_route_cmd import DeleteFailoverRouteCommand  # noqa: F401
from .hello_cmd import HelloCommand  # noqa: F401
from .help_cmd import HelpCommand  # noqa: F401
from .list_failover_routes_cmd import ListFailoverRoutesCommand  # noqa: F401
from .route_append_cmd import RouteAppendCommand  # noqa: F401
from .route_clear_cmd import RouteClearCommand  # noqa: F401
from .route_list_cmd import RouteListCommand  # noqa: F401
from .route_prepend_cmd import RoutePrependCommand  # noqa: F401
from .oneoff_cmd import OneoffCommand # noqa: F401
from .pwd_cmd import PwdCommand # noqa: F401

# Import command modules to ensure registration
from .set_cmd import SetCommand  # noqa: F401
from .unset_cmd import UnsetCommand  # noqa: F401

__all__ = [
    "OneoffCommand",
    "BaseCommand",
    "CommandResult",
    "register_command",
    "command_registry",
    "create_command_instances",
    "SetCommand",
    "UnsetCommand",
    "HelloCommand",
    "CreateFailoverRouteCommand",
    "RouteAppendCommand",
    "RoutePrependCommand",
    "DeleteFailoverRouteCommand",
    "RouteClearCommand",
    "ListFailoverRoutesCommand",
    "RouteListCommand",
    "HelpCommand",
    "PwdCommand",
]
