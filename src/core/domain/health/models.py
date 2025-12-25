from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional

class EndpointHealthSummary(BaseModel):
    total_endpoints: int
    healthy_endpoints: int
    unhealthy_endpoints: int

class EndpointBackendInfo(BaseModel):
    api_url: str
    backend_type: str
    is_endpoint_healthy: bool

class EndpointHealthStateInfo(BaseModel):
    api_url: str
    is_healthy: bool
    ping_check_success: bool
    http_check_success: bool
    last_ping_check_timestamp: Optional[str] = None
    last_http_check_timestamp: Optional[str] = None
    last_successful_ping_timestamp: Optional[str] = None
    last_successful_http_timestamp: Optional[str] = None
    consecutive_ping_failures: int
    consecutive_http_failures: int
    last_ping_latency_ms: Optional[float] = None
    last_http_latency_ms: Optional[float] = None
    last_http_status_code: Optional[int] = None
    last_ping_error: Optional[str] = None
    last_http_error: Optional[str] = None
    backends_using_url: list[str]

class HealthInfo(BaseModel):
    enabled: bool
    note: Optional[str] = None
    endpoints: list[EndpointHealthStateInfo] = Field(default_factory=list)
    backends: list[EndpointBackendInfo] = Field(default_factory=list)
    summary: Optional[EndpointHealthSummary] = None
    error: Optional[str] = None

class SystemHealthInfo(BaseModel):
    service_provider_present: bool
    IRequestProcessor_resolvable: Optional[bool] = None
    IRequestProcessor_error: Optional[str] = None
    ChatController_resolvable: Optional[bool] = None
    ChatController_error: Optional[str] = None
    endpoint_health: Optional[HealthInfo] = None
    registered_descriptors: list[str] = Field(default_factory=list)
    descriptor_error: Optional[str] = None
    error: Optional[str] = None
