import os
from backends import select_backend, register_backend, openrouter_backend
from backends.base import Backend

class DummyBackend(Backend):
    prefix = "dummy"
    async def chat_completions(self, request, client):
        return {"dummy": True}
    async def list_models(self, client):
        return {"data": []}

def test_select_backend_defaults_to_registered():
    backend, model = select_backend("gpt-3.5")
    assert backend is openrouter_backend
    assert model == "gpt-3.5"

def test_select_backend_with_prefix():
    dummy = DummyBackend()
    register_backend(dummy)
    backend, model = select_backend("dummy:model-x")
    assert backend is dummy
    assert model == "model-x"
