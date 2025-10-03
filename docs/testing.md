# Running Tests Locally

This project relies on several pytest plugins (``pytest-asyncio`` and ``pytest-xdist``) that are only declared inside the ``dev`` optional dependency group in ``pyproject.toml``. The default ``pip install -e .`` command does **not** install those extras, so the pytest configuration defined in ``[tool.pytest.ini_options]`` ends up passing ``--asyncio-mode`` and ``-n`` arguments without the plugins that provide them. As a result ``pytest`` aborts with an "unrecognized arguments" error before running any tests.

To make sure the required plugins are present:

1. Create a virtual environment (the path or tooling does not matter, it just needs to be active when installing packages).
2. Install the project together with the development extras:
   ```bash
   python -m pip install -e .[dev]
   ```
   Installing the ``dev`` extra pulls in ``pytest``, ``pytest-asyncio``, ``pytest-xdist`` and the other tools that the test suite expects.
3. Once the installation finishes, run the test suite:
   ```bash
   python -m pytest
   ```

If you are running inside a non-Windows container, make sure the commands use the Python interpreter from the virtual environment you created (for example ``.venv/bin/python``). The project documentation previously referenced a Windows-specific interpreter path (``.venv/Scripts/python.exe``); the cross-platform ``python`` entry point from the active environment works everywhere and still satisfies local developer workflows on Windows.

Following the steps above allows the test suite to execute in an automated container without hitting missing dependency errors.
