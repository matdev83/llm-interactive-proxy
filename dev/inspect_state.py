import os
import sys

from src.core.app import application_factory as app_main

# Mirror the test environment used earlier
os.environ.setdefault('OPENROUTER_API_KEY', 'KEY')
os.environ.setdefault('LLM_BACKEND', 'openrouter')

app = app_main.build_app()
print('app.state type:', type(app.state))
print('has _original on state:', hasattr(app.state, '_original'))
if hasattr(app.state, '_original'):
    orig = app.state._original
    print('original state type:', type(orig))
    print('original has openrouter_backend:', hasattr(orig, 'openrouter_backend'))
    if hasattr(orig, 'openrouter_backend'):
        print('original.openrouter_backend type:', type(orig.openrouter_backend))

print('proxy openrouter_backend type:', type(app.state.openrouter_backend))
print('proxy has get_available_models?:', hasattr(app.state.openrouter_backend, 'get_available_models'))
print('proxy dir filtered:', [m for m in dir(app.state.openrouter_backend) if 'list_models' in m or 'get_available_models' in m])

# Try calling get_available_models (may trigger network calls)
try:
    res = app.state.openrouter_backend.get_available_models()
    print('get_available_models() ->', res)
except Exception as e:
    print('get_available_models() raised:', repr(e))

print('initialize_legacy attached?:', hasattr(app.state, 'initialize_legacy'))
print('cleanup_legacy attached?:', hasattr(app.state, 'cleanup_legacy'))

sys.exit(0)
