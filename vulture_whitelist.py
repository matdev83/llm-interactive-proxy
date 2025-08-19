"""
Whitelist for vulture to ignore intentionally unused variables
These are false positives that are intentionally unused
"""

# Import the modules to make the variables known to vulture
from src.core.app import middleware_config
from src.core.common import logging_utils
from src.core.domain import streaming_response_processor

# Reference the variables to prevent vulture from marking them as unused
# Part of context manager protocol - required by Python
logging_utils.LoggingContext.__exit__.__code__.co_varnames

# Part of function signature for TODO implementation
middleware_config.register_custom_middleware.__code__.co_varnames

# Part of constructor signature for no-op implementation
streaming_response_processor.LoopDetectionProcessor.__init__.__code__.co_varnames