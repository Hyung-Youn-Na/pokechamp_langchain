import os
import uuid

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.types import TraceContext

_client = None


def create_callback_handler(
    trace_id: str | None = None,
) -> CallbackHandler:
    tc = TraceContext(trace_id=trace_id or uuid.uuid4().hex)
    return CallbackHandler(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        trace_context=tc,
    )


def get_langfuse_client() -> Langfuse:
    global _client
    if _client is None:
        _client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _client


def init_langfuse():
    client = get_langfuse_client()
    client.auth_check()
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    print(f"[Langfuse] Connected to {host}")
