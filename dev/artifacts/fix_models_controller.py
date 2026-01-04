"""Fix for resource leak in models_controller.py

Backend instance created for credential check was never closed,
causing HTTP client resource leaks.
"""

# Read the file
with open("src/core/app/controllers/models_controller.py", encoding="utf-8") as f:
    content = f.read()

# Find and replace the vulnerable pattern
old_pattern = """            # Special case for opencode-zen: verify credentials file existence
            # This backend doesn't require explicit configuration in config file,
            # but relies on the presence of a credentials file.
            if backend_type == "opencode-zen" and not has_credentials:
                try:
                    # Instantiate just to check credential path logic
                    # We need a minimal config here
                    _ = backend_factory.create_backend(backend_type, config)
                    # We can't easily access the private method _get_default_credentials_path
                    # without violating encapsulation, but we can try to check if it's functional
                    # However, create_backend doesn't initialize it fully.

                    # Alternatively, we can manually check the known default path"""

new_pattern = """            # Special case for opencode-zen: verify credentials file existence
            # This backend doesn't require explicit configuration in config file,
            # but relies on the presence of a credentials file.
            if backend_type == "opencode-zen" and not has_credentials:
                temp_backend = None
                try:
                    # Instantiate just to check credential path logic
                    # We need a minimal config here
                    temp_backend = backend_factory.create_backend(backend_type, config)
                    # We can't easily access the private method _get_default_credentials_path
                    # without violating encapsulation, but we can try to check if it's functional
                    # However, create_backend doesn't initialize it fully.

                    # Alternatively, we can manually check the known default path"""

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern)
    print("Pattern found - replaced old with new")

    # Now add the finally block after the exception handler
    # Find the exception handler and add finally block
    exception_handler = """                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Failed to check opencode-zen credentials: {e}")"""

    finally_block = """                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Failed to check opencode-zen credentials: {e}")
                finally:
                    # Clean up temporary backend instance to prevent resource leak
                    if temp_backend is not None:
                        if hasattr(temp_backend, "close"):
                            try:
                                temp_backend.close()
                            except Exception:
                                pass
                        elif hasattr(temp_backend, "aclose"):
                            try:
                                import asyncio
                                loop = asyncio.get_running_loop()
                                asyncio.create_task(temp_backend.aclose())
                            except RuntimeError:
                                pass
                            except Exception:
                                pass"""

    if exception_handler in content:
        content = content.replace(exception_handler, finally_block)
        print("Added finally block for resource cleanup")
    else:
        print("Exception handler pattern not found")

    # Write back
    with open(
        "src/core/app/controllers/models_controller.py", "w", encoding="utf-8"
    ) as f:
        f.write(content)

    print("File updated successfully")
else:
    print("Old pattern not found in file")
