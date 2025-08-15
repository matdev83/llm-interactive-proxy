from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IConfig(ABC):
    """Interface for general configuration management."""
    
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.
        
        Args:
            key: The configuration key
            default: Default value if key not found
            
        Returns:
            The configuration value
        """
    
    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.
        
        Args:
            key: The configuration key
            value: The value to set
        """
    
    @abstractmethod
    def has(self, key: str) -> bool:
        """Check if a configuration key exists.
        
        Args:
            key: The configuration key
            
        Returns:
            True if the key exists
        """
    
    @abstractmethod
    def keys(self) -> list[str]:
        """Get all configuration keys.
        
        Returns:
            List of configuration keys
        """
    
    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.
        
        Returns:
            Configuration as dictionary
        """
    
    @abstractmethod
    def update(self, config: dict[str, Any]) -> None:
        """Update configuration with new values.
        
        Args:
            config: Configuration dictionary to merge
        """


class IBackendConfig(ABC):
    """Interface for backend configuration value objects."""
    
    @property
    @abstractmethod
    def backend_type(self) -> str | None:
        """Get the backend type."""
    
    @property
    @abstractmethod
    def model(self) -> str | None:
        """Get the model name."""
    
    @property
    @abstractmethod
    def api_url(self) -> str | None:
        """Get the API URL."""
    
    @property
    @abstractmethod
    def interactive_mode(self) -> bool:
        """Get the interactive mode flag."""
    
    @property
    @abstractmethod
    def failover_routes(self) -> dict[str, dict[str, Any]]:
        """Get the failover routes configuration."""
    
    @abstractmethod
    def with_backend(self, backend_type: str | None) -> IBackendConfig:
        """Create a new config with updated backend type.
        
        Args:
            backend_type: The new backend type
            
        Returns:
            A new backend config instance
        """
    
    @abstractmethod
    def with_model(self, model: str | None) -> IBackendConfig:
        """Create a new config with updated model.
        
        Args:
            model: The new model name
            
        Returns:
            A new backend config instance
        """
    
    @abstractmethod
    def with_api_url(self, api_url: str | None) -> IBackendConfig:
        """Create a new config with updated API URL.
        
        Args:
            api_url: The new API URL
            
        Returns:
            A new backend config instance
        """
    
    @abstractmethod
    def with_interactive_mode(self, enabled: bool) -> IBackendConfig:
        """Create a new config with updated interactive mode.
        
        Args:
            enabled: Whether interactive mode is enabled
            
        Returns:
            A new backend config instance
        """


class IReasoningConfig(ABC):
    """Interface for reasoning configuration value objects."""
    
    @property
    @abstractmethod
    def reasoning_effort(self) -> str | None:
        """Get the reasoning effort setting."""
    
    @property
    @abstractmethod
    def thinking_budget(self) -> int | None:
        """Get the thinking budget (for Gemini)."""
    
    @property
    @abstractmethod
    def temperature(self) -> float | None:
        """Get the temperature setting."""
    
    @abstractmethod
    def with_reasoning_effort(self, effort: str | None) -> IReasoningConfig:
        """Create a new config with updated reasoning effort.
        
        Args:
            effort: The new reasoning effort setting
            
        Returns:
            A new reasoning config instance
        """
    
    @abstractmethod
    def with_thinking_budget(self, budget: int | None) -> IReasoningConfig:
        """Create a new config with updated thinking budget.
        
        Args:
            budget: The new thinking budget
            
        Returns:
            A new reasoning config instance
        """
    
    @abstractmethod
    def with_temperature(self, temperature: float | None) -> IReasoningConfig:
        """Create a new config with updated temperature.
        
        Args:
            temperature: The new temperature setting
            
        Returns:
            A new reasoning config instance
        """


class ILoopDetectionConfig(ABC):
    """Interface for loop detection configuration value objects."""
    
    @property
    @abstractmethod
    def loop_detection_enabled(self) -> bool:
        """Get whether loop detection is enabled."""
    
    @property
    @abstractmethod
    def tool_loop_detection_enabled(self) -> bool:
        """Get whether tool call loop detection is enabled."""
    
    @property
    @abstractmethod
    def min_pattern_length(self) -> int:
        """Get the minimum pattern length for loop detection."""
    
    @property
    @abstractmethod
    def max_pattern_length(self) -> int:
        """Get the maximum pattern length for loop detection."""
    
    @abstractmethod
    def with_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated loop detection enabled flag.
        
        Args:
            enabled: Whether loop detection should be enabled
            
        Returns:
            A new loop detection config instance
        """
    
    @abstractmethod
    def with_tool_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop detection enabled flag.
        
        Args:
            enabled: Whether tool loop detection should be enabled
            
        Returns:
            A new loop detection config instance
        """
    
    @abstractmethod
    def with_pattern_length_range(self, min_length: int, max_length: int) -> ILoopDetectionConfig:
        """Create a new config with updated pattern length range.
        
        Args:
            min_length: The minimum pattern length
            max_length: The maximum pattern length
            
        Returns:
            A new loop detection config instance
        """
