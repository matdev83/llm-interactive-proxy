"""
Recreate just the _schedule_credentials_reload method with proper formatting
"""


def _schedule_credentials_reload(self) -> str:
    """Return the source code for the fixed _schedule_credentials_reload method"""
    return '''    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload of credentials."""
        async def _schedule_locked() -> None:
            async with self._reload_lock:
                pending = self._pending_reload_task
                if pending is not None and not pending.done():
                    return

                async def reload_task() -> None:
                    try:
                        logger.debug("Reloading Anthropic OAuth credentials due to file change")
                        loaded = await self._load_oauth_credentials(force_reload=True)
                        if loaded:
                            if self._oauth_credentials is not None:
                                res = self._validate_credentials_structure(
                                    self._oauth_credentials
                                )
                                if res:
                                    self._recover()
                                else:
                                    self._degrade(res.errors)
                            else:
                                self._degrade(
                                    ["Failed to load credentials despite successful file read"]
                                )
                        else:
                            self._degrade(["Failed to reload credentials from file"])
                    except Exception as e:
                        if logger.isEnabledFor(logging.ERROR):
                            logger.error(
                                "Error during Anthropic OAuth credentials reload: %s",
                                e,
                                exc_info=True,
                            )
                        self._degrade([f"Credentials reload failed: {e}"])

                def _clear(_: Any) -> None:
                    self._pending_reload_task = None

                if target_loop is current_loop:
                    task = target_loop.create_task(reload_task())
                    task.add_done_callback(_clear)
                    self._pending_reload_task = task
                    return

                try:
                    future = asyncio.run_coroutine_threadsafe(reload_task(), target_loop)
                    future.add_done_callback(_clear)
                    self._pending_reload_task = future
                except RuntimeError as exc:
                    logger.warning(
                        "Failed to schedule Anthropic OAuth credentials reload: %s", exc
                    )

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        target_loop = None
        if current_loop and current_loop.is_running():
            target_loop = current_loop
        elif self._event_loop and self._event_loop.is_running():
            target_loop = self._event_loop

        if target_loop is None or target_loop.is_closed():
            logger.warning(
                "Cannot schedule Anthropic OAuth credentials reload: no running event loop available."
            )
            return

        if target_loop is not self._event_loop:
            self._event_loop = target_loop

        asyncio.run_coroutine_threadsafe(_schedule_locked(), target_loop)
'''
