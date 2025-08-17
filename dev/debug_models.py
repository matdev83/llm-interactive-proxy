import os

# Ensure src is importable
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from src.connectors.openrouter import OpenRouterBackend
from src.core.app import application_factory as app_main

response = {"data": [{"id": "m1"}, {"id": "m2"}]}

with patch.object(OpenRouterBackend, 'list_models', new=AsyncMock(return_value=response)) as mock_list:
    os.environ['OPENROUTER_API_KEY'] = 'KEY'
    os.environ['LLM_BACKEND'] = 'openrouter'
    app = app_main.build_app()
    print('Built app, about to enter TestClient')
    with TestClient(app) as client:
        print('In TestClient context')
        ob = client.app.state.openrouter_backend
        print('openrouter_backend type:', type(ob))
        print('has list_models on object?:', hasattr(ob, 'list_models'))
        try:
            models = ob.get_available_models()
            print('get_available_models returned:', models)
        except Exception as e:
            print('get_available_models raised:', repr(e))
    print('Exited TestClient')
    print('mock_list.called =', mock_list.called)
