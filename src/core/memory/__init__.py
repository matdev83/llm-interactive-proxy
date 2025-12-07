"""ProxyMem - Proxy-based memory layer for LLM agents.

This module provides cross-session context persistence for LLM agents
by capturing session data, generating structured summaries via LLM analysis,
and enriching future requests with relevant historical context.
"""

from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.maintenance import DatabaseMaintenance
from src.core.memory.models import (
    CapturedInteraction,
    FileChange,
    FileEditEvent,
    GitCommitEvent,
    GitOperation,
    SessionData,
    SessionSummary,
    TaskItem,
    TestRun,
    ToolEvent,
)
from src.core.memory.prompt_loader import PromptLoader
from src.core.memory.repository import IMemoryRepository
from src.core.memory.service import MemoryService, SessionMemoryState
from src.core.memory.sqlite_repository import MemoryRepository
from src.core.memory.summary_generator import SummaryGenerator, SummaryValidator
from src.core.memory.tool_event_collector import DeterministicToolEventCollector

__all__ = [
    "CapturedInteraction",
    "ContextInjector",
    "DatabaseMaintenance",
    "DeterministicToolEventCollector",
    "FileChange",
    "FileEditEvent",
    "GitCommitEvent",
    "GitOperation",
    "IMemoryRepository",
    "MemoryConfiguration",
    "MemoryRepository",
    "MemoryService",
    "PromptLoader",
    "SessionCaptureBuffer",
    "SessionData",
    "SessionMemoryState",
    "SessionSummary",
    "SummaryGenerator",
    "SummaryValidator",
    "TaskItem",
    "TestRun",
    "ToolEvent",
]
