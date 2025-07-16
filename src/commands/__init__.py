from .base import (
    BaseCommand,
    CommandResult,
    command_registry,
    create_command_instances,
    register_command,
)
from .create_failover_route_cmd import CreateFailoverRouteCommand
from .delete_failover_route_cmd import DeleteFailoverRouteCommand
from .hello_cmd import HelloCommand
from .help_cmd import HelpCommand
from .list_failover_routes_cmd import ListFailoverRoutesCommand
from .oneoff_cmd import OneoffCommand
from .pwd_cmd import PwdCommand
from .route_append_cmd import RouteAppendCommand
from .route_clear_cmd import RouteClearCommand
from .route_list_cmd import RouteListCommand
from .route_prepend_cmd import RoutePrependCommand

# Import command modules to ensure registration
from .set_cmd import SetCommand
from .unset_cmd import UnsetCommand

__all__ = [
    "BaseCommand",
    "CommandResult",
    "CreateFailoverRouteCommand",
    "DeleteFailoverRouteCommand",
    "HelloCommand",
    "HelpCommand",
    "ListFailoverRoutesCommand",
    "OneoffCommand",
    "PwdCommand",
    "RouteAppendCommand",
    "RouteClearCommand",
    "RouteListCommand",
    "RoutePrependCommand",
    "SetCommand",
    "UnsetCommand",
    "command_registry",
    "create_command_instances",
    "register_command",
]
