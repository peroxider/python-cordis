"""python-cordis: a plugin-driven framework kernel for Python.

Everything is a plugin. This package provides the engine that makes an
application composable from plugins: hooks (on pluggy), a reflective
service container, plugin lifecycle, and config assembly.
"""

from .core.context import Context, inject
from .core.fiber import Fiber
from .core.hook import HookRegistry, hookimpl, hookspec
from .core.config import dump, load, overlay, resolve
from .core.hmr import FileWatcher, PluginReloader, Reloader
from .observability import LifecycleLogger, setup_lifecycle_logging
from .seams.fs import FileSystem, LocalFS, SandboxFS
from .seams.llm import (
    KIND_TOOL_CALL,
    LlmAdapter,
    LlmEvent,
    LlmStream,
    MockProvider,
)
from .seams.pipeline import REJECT, ToolRegistry
from .session import (
    SURFACE_ASSISTANT_MESSAGE,
    SURFACE_TOOL_RESULT,
    SURFACE_USER_MESSAGE,
    Session,
    SessionEvent,
    SessionNotFound,
    SessionStore,
)
from .persistence import (
    JsonlSessionPersistence,
    PersistenceCoordinator,
    SessionPersistence,
    SqliteSessionPersistence,
)
from .agent import NEXT_STEP, NEXT_TURN, Agent, Inbox
from .query import InMemoryQueryEngine, SearchHit, SessionQueryEngine
from .contrib.approval import APPROVE_METHOD, ApprovalPlugin
from .contrib.web_server import (
    ClientRequest,
    ClientResponse,
    EventBus,
    MethodKind,
    RpcErrorCode,
    RpcMessage,
    RpcRegistry,
    RpcResult,
    ServerRequest,
    ServerResponse,
    WebServerPlugin,
    decode_message,
    encode_message,
    plugin as web_server_plugin,
)

__version__ = "0.1.0"

__all__ = [
    "Context",
    "Fiber",
    "HookRegistry",
    "hookimpl",
    "hookspec",
    "inject",
    "dump",
    "load",
    "overlay",
    "resolve",
    "Reloader",
    "PluginReloader",
    "FileWatcher",
    "LifecycleLogger",
    "setup_lifecycle_logging",
    "FileSystem",
    "LocalFS",
    "SandboxFS",
    "LlmAdapter",
    "LlmEvent",
    "LlmStream",
    "MockProvider",
    "KIND_TOOL_CALL",
    "ToolRegistry",
    "REJECT",
    "Session",
    "SessionEvent",
    "SessionStore",
    "SessionNotFound",
    "SURFACE_USER_MESSAGE",
    "SURFACE_ASSISTANT_MESSAGE",
    "SURFACE_TOOL_RESULT",
    "SessionPersistence",
    "JsonlSessionPersistence",
    "SqliteSessionPersistence",
    "PersistenceCoordinator",
    "Agent",
    "Inbox",
    "NEXT_STEP",
    "NEXT_TURN",
    "SessionQueryEngine",
    "InMemoryQueryEngine",
    "SearchHit",
    "ApprovalPlugin",
    "APPROVE_METHOD",
    "__version__",
]
