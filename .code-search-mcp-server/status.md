src/connectors/gemini_oauth_personal.py [lines 98–126]
98 | class GeminiOAuthPersonalConnector(GeminiBackend):
99 |     """Connector that uses access_token from gemini-cli oauth_creds.json file.
100 | 
101 |     This is a specialized Gemini connector that reads the access_token
102 |     from the gemini-cli generated oauth_creds.json file and uses it as the API key.
103 |     It handles token refresh automatically when the token expires.
104 |     """
105 | 
106 |     _project_id: str | None = None
107 | 
108 |     backend_type: str = "gemini-cli-oauth-personal"
109 | 
110 |     def __init__(
111 |         self,
112 |         client: httpx.AsyncClient,
113 |         config: AppConfig,
114 |         translation_service: TranslationService,
115 |     ) -> None:
116 |         super().__init__(
117 |             client, config, translation_service
118 |         )  # Pass translation_service to super
119 |         self.name = "gemini-cli-oauth-personal"
120 |         self.is_functional = False
121 |         self._oauth_credentials: dict[str, Any] | None = None
122 |         self._credentials_path: Path | None = None
123 |         self._last_modified: float = 0
124 |         self._refresh_token: str | None = None
125 |         self._token_refresh_lock = asyncio.Lock()
126 |         self.translation_service = translation_service
---
src/connectors/gemini_oauth_personal.py [lines 219–266]
219 |     async def _load_oauth_credentials(self) -> bool:
220 |         """Load OAuth credentials from oauth_creds.json file."""
221 |         try:
222 |             # Use custom path if provided, otherwise default to ~/.gemini
223 |             if self.gemini_cli_oauth_path:
224 |                 creds_path = Path(self.gemini_cli_oauth_path) / "oauth_creds.json"
225 |             else:
226 |                 home_dir = Path.home()
227 |                 creds_path = home_dir / ".gemini" / "oauth_creds.json"
228 |             self._credentials_path = creds_path
229 | 
230 |             if not creds_path.exists():
231 |                 logger.warning(f"Gemini OAuth credentials not found at {creds_path}")
232 |                 return False
233 | 
234 |             # Check if file has been modified since last load
235 |             try:
236 |                 current_modified = creds_path.stat().st_mtime
237 |                 if current_modified == self._last_modified and self._oauth_credentials:
238 |                     # File hasn't changed and credentials are in memory, no need to reload
239 |                     logger.debug(
240 |                         "Gemini OAuth credentials file not modified, using cached."
241 |                     )
242 |                     return True
243 |                 self._last_modified = current_modified
244 |             except OSError:
245 |                 # If cannot get file stats, proceed with reading
246 |                 pass
247 | 
248 |             with open(creds_path, encoding="utf-8") as f:
249 |                 credentials = json.load(f)
250 | 
251 |             # Validate essential fields
252 |             if "access_token" not in credentials:
253 |                 logger.warning(
254 |                     "Malformed Gemini OAuth credentials: missing access_token"
255 |                 )
256 |                 return False
257 | 
258 |             self._oauth_credentials = credentials
259 |             logger.info("Successfully loaded Gemini OAuth credentials.")
260 |             return True
261 |         except json.JSONDecodeError as e:
262 |             logger.error(f"Error decoding Gemini OAuth credentials JSON: {e}")
263 |             return False
264 |         except Exception as e:
265 |             logger.error(f"Error loading Gemini OAuth credentials: {e}")
266 |             return False
---
src/connectors/gemini_oauth_personal.py [lines 170–204]
170 |     async def _refresh_token_if_needed(self) -> bool:
171 |         """Ensure we have a valid access token; reload from CLI cache if expired.
172 | 
173 |         We intentionally avoid embedding OAuth client credentials. The official
174 |         gemini CLI persists credentials to ~/.gemini/oauth_creds.json and refreshes
175 |         them itself. Here we re-load that file if our token is stale.
176 |         """
177 |         if not self._is_token_expired():
178 |             return True
179 | 
180 |         async with self._token_refresh_lock:
181 |             if not self._is_token_expired():
182 |                 return True
183 | 
184 |             logger.info(
185 |                 "Access token expired or near expiry; reloading CLI credentials..."
186 |             )
187 | 
188 |             # Attempt to reload the credentials file; the CLI should refresh it
189 |             reloaded = await self._load_oauth_credentials()
190 |             if not reloaded:
191 |                 logger.warning(
192 |                     "Failed to reload Gemini OAuth credentials from ~/.gemini."
193 |                 )
194 |                 return False
195 | 
196 |             # After reload, consider token valid if not expired
197 |             if self._is_token_expired():
198 |                 logger.warning(
199 |                     "Reloaded credentials are still expired. Please run 'gemini auth' to refresh."
200 |                 )
201 |                 return False
202 | 
203 |             return True
204 | 
---
src/connectors/gemini_oauth_personal.py [lines 445–503]
445 |         agent: str | None = None,
446 |         gemini_api_base_url: str | None = None,
447 |         **kwargs: Any,
448 |     ) -> ResponseEnvelope | StreamingResponseEnvelope:
449 |         """Handle chat completions using Google Code Assist API.
450 | 
451 |         This method uses the Code Assist API (https://cloudcode-pa.googleapis.com)
452 |         which is the correct endpoint for oauth-personal authentication,
453 |         while maintaining OpenAI-compatible interface and response format.
454 |         """
455 |         # Perform health check on first use (includes token refresh)
456 |         await self._ensure_healthy()
457 | 
458 |         try:
459 |             # Use the effective model (strip gemini-cli-oauth-personal: prefix if present)
460 |             model_name = effective_model
461 |             if model_name.startswith("gemini-cli-oauth-personal:"):
462 |                 model_name = model_name[
463 |                     25:
464 |                 ]  # Remove "gemini-cli-oauth-personal:" prefix
465 | 
466 |             # Fix the model name stripping bug
467 |             if model_name.startswith("gemini-cli-oauth-personal:"):
468 |                 model_name = model_name[
469 |                     27:
470 |                 ]  # Remove "gemini-cli-oauth-personal:" prefix
471 | 
472 |             # Check if streaming is requested
473 |             is_streaming = getattr(request_data, "stream", False)
474 | 
475 |             if is_streaming:
476 |                 return await self._chat_completions_code_assist_streaming(
477 |                     request_data=request_data,
478 |                     processed_messages=processed_messages,
479 |                     effective_model=model_name,
480 |                     **kwargs,
481 |                 )
482 |             else:
483 |                 return await self._chat_completions_code_assist(
484 |                     request_data=request_data,
485 |                     processed_messages=processed_messages,
486 |                     effective_model=model_name,
487 |                     **kwargs,
488 |                 )
489 |         except HTTPException:
490 |             # Re-raise HTTP exceptions directly
491 |             raise
492 |         except (AuthenticationError, BackendError):
493 |             # Re-raise domain exceptions
494 |             raise
495 |         except Exception as e:
496 |             # Convert other exceptions to BackendError
497 |             logger.error(f"Error in Gemini OAuth Personal chat_completions: {e}")
498 |             raise BackendError(
499 |                 message=f"Gemini OAuth Personal chat completion failed: {e!s}"
500 |             ) from e
---
src/connectors/gemini_cloud_project.py [lines 166–196]
166 | class GeminiCloudProjectConnector(GeminiBackend):
167 |     """Connector that uses OAuth authentication with user-specified GCP project.
168 | 
169 |     This connector requires a valid Google Cloud Project ID and uses OAuth2
170 |     authentication to access Gemini Code Assist API with standard/enterprise tier features.
171 |     All usage is billed to the specified GCP project.
172 |     """
173 | 
174 |     backend_type: str = "gemini-cli-cloud-project"
175 | 
176 |     def __init__(
177 |         self,
178 |         client: httpx.AsyncClient,
179 |         config: AppConfig,
180 |         translation_service: TranslationService,
181 |         **kwargs: Any,
182 |     ) -> None:  # Modified
183 |         super().__init__(client, config, translation_service)
184 |         self.translation_service = translation_service
185 |         self.name = "gemini-cli-cloud-project"
186 |         self.is_functional = False
187 |         self._oauth_credentials: dict[str, Any] | None = None
188 |         self._credentials_path: Path | None = None
189 |         self._last_modified: float = 0
190 |         self._refresh_token: str | None = None
191 |         self._token_refresh_lock = asyncio.Lock()
192 | 
193 |         # GCP Project ID is REQUIRED for this backend (CLI uses GOOGLE_CLOUD_PROJECT)
194 |         self.gcp_project_id = (
195 |             kwargs.get("gcp_project_id")
196 |             or os.getenv("GOOGLE_CLOUD_PROJECT")
---
src/connectors/gemini_cloud_project.py [lines 360–401]
360 |     async def _load_oauth_credentials(self) -> bool:
361 |         """Load OAuth credentials from oauth_creds.json file."""
362 |         try:
363 |             if self.credentials_path:
364 |                 creds_path = Path(self.credentials_path)
365 |                 if creds_path.is_dir():
366 |                     creds_path = creds_path / "oauth_creds.json"
367 |             else:
368 |                 home_dir = Path.home()
369 |                 creds_path = home_dir / ".gemini" / "oauth_creds.json"
370 | 
371 |             self._credentials_path = creds_path
372 | 
373 |             if not creds_path.exists():
374 |                 logger.warning(f"OAuth credentials not found at {creds_path}")
375 |                 return False
376 | 
377 |             try:
378 |                 current_modified = creds_path.stat().st_mtime
379 |                 if current_modified == self._last_modified and self._oauth_credentials:
380 |                     logger.debug("OAuth credentials file not modified, using cached.")
381 |                     return True
382 |                 self._last_modified = current_modified
383 |             except OSError:
384 |                 pass
385 | 
386 |             with open(creds_path, encoding="utf-8") as f:
387 |                 credentials = json.load(f)
388 | 
389 |             if "access_token" not in credentials:
390 |                 logger.warning("Malformed OAuth credentials: missing access_token")
391 |                 return False
392 | 
393 |             self._oauth_credentials = credentials
394 |             logger.info("Successfully loaded OAuth credentials.")
395 |             return True
396 |         except json.JSONDecodeError as e:
397 |             logger.error(f"Error decoding OAuth credentials JSON: {e}")
398 |             return False
399 |         except Exception as e:
400 |             logger.error(f"Error loading OAuth credentials: {e}")
401 |             return False
---
src/connectors/gemini_cloud_project.py [lines 283–340]
283 |     async def _refresh_token_if_needed(self) -> bool:
284 |         """Refresh the access token if it's expired or close to expiring."""
285 |         if not self._is_token_expired():
286 |             return True
287 | 
288 |         async with self._token_refresh_lock:
289 |             if not self._is_token_expired():
290 |                 return True
291 | 
292 |             logger.info("Access token expired or near expiry, attempting to refresh...")
293 | 
294 |             if not self._oauth_credentials:
295 |                 logger.warning("No OAuth credentials available for refresh.")
296 |                 return False
297 | 
298 |             try:
299 |                 creds_dict = dict(self._oauth_credentials)
300 |                 if "expiry_date" in creds_dict:
301 |                     creds_dict["expiry"] = creds_dict.pop("expiry_date") / 1000
302 | 
303 |                 credentials = google.oauth2.credentials.Credentials(
304 |                     token=creds_dict.get("access_token"),
305 |                     refresh_token=creds_dict.get("refresh_token"),
306 |                     token_uri="https://oauth2.googleapis.com/token",
307 |                     client_id=_load_gemini_oauth_client_config()[0],
308 |                     client_secret=_load_gemini_oauth_client_config()[1],
309 |                     scopes=_load_gemini_oauth_client_config()[2],
310 |                 )
311 | 
312 |                 request = google.auth.transport.requests.Request()
313 |                 credentials.refresh(request)
314 | 
315 |                 new_credentials = {
316 |                     "access_token": credentials.token,
317 |                     "refresh_token": credentials.refresh_token,
318 |                     "token_type": "Bearer",
319 |                     "expiry_date": (
320 |                         int(credentials.expiry.timestamp() * 1000)
321 |                         if credentials.expiry
322 |                         else int(time.time() * 1000 + 3600 * 1000)
323 |                     ),
324 |                 }
325 | 
326 |                 self._oauth_credentials.update(new_credentials)
327 |                 await self._save_oauth_credentials(self._oauth_credentials)
328 | 
329 |                 logger.info(
330 |                     "Successfully refreshed OAuth token for GCP project access."
331 |                 )
332 |                 return True
333 | 
334 |             except RefreshError as e:
335 |                 logger.error(f"Google Auth token refresh error: {e}")
336 |                 return False
337 |             except Exception as e:
338 |                 logger.error(f"Unexpected error during token refresh: {e}")
339 |                 return False
340 | 
---
src/connectors/gemini_cloud_project.py [lines 559–610]
559 |     async def chat_completions(  # type: ignore[override]
560 |         self,
561 |         request_data: DomainModel | InternalDTO | dict[str, Any],
562 |         processed_messages: list[Any],
563 |         effective_model: str,
564 |         identity: Any = None,
565 |         openrouter_api_base_url: str | None = None,
566 |         openrouter_headers_provider: Any = None,
567 |         key_name: str | None = None,
568 |         api_key: str | None = None,
569 |         project: str | None = None,
570 |         agent: str | None = None,
571 |         gemini_api_base_url: str | None = None,
572 |         **kwargs: Any,
573 |     ) -> ResponseEnvelope | StreamingResponseEnvelope:
574 |         """Handle chat completions using Google Code Assist API with user's GCP project."""
575 |         await self._ensure_healthy()
576 | 
577 |         try:
578 |             # Use the effective model (strip prefix if present)
579 |             model_name = effective_model
580 |             if model_name.startswith("gemini-cli-cloud-project:"):
581 |                 model_name = model_name[25:]  # Remove prefix
582 | 
583 |             # Check if streaming is requested
584 |             is_streaming = getattr(request_data, "stream", False)
585 | 
586 |             if is_streaming:
587 |                 return await self._chat_completions_streaming(
588 |                     request_data=request_data,
589 |                     processed_messages=processed_messages,
590 |                     effective_model=model_name,
591 |                     **kwargs,
592 |                 )
593 |             else:
594 |                 return await self._chat_completions_standard(
595 |                     request_data=request_data,
596 |                     processed_messages=processed_messages,
597 |                     effective_model=model_name,
598 |                     **kwargs,
599 |                 )
600 |         except HTTPException:
601 |             raise
602 |         except (AuthenticationError, BackendError):
603 |             raise
604 |         except Exception as e:
605 |             logger.error(f"Error in Gemini Cloud Project chat_completions: {e}")
606 |             raise BackendError(
607 |                 message=f"Gemini Cloud Project chat completion failed: {e!s}"
608 |             ) from e
609 | 
610 |     async def _chat_completions_standard(
---
src/connectors/gemini_cloud_project.py [lines 403–434]
403 |     async def initialize(self, **kwargs: Any) -> None:
404 |         """Initialize backend by loading credentials and validating project."""
405 |         logger.info(
406 |             f"Initializing Gemini Cloud Project backend with project: {self.gcp_project_id}"
407 |         )
408 | 
409 |         # Ensure we have a project ID
410 |         if not self.gcp_project_id:
411 |             logger.error("GCP Project ID is required for cloud-project backend")
412 |             self.is_functional = False
413 |             return
414 | 
415 |         # Set the API base URL for Google Code Assist API
416 |         self.gemini_api_base_url = kwargs.get(
417 |             "gemini_api_base_url", CODE_ASSIST_ENDPOINT
418 |         )
419 | 
420 |         # Using Google ADC; no need to load personal OAuth creds. Validate by making API calls below
421 | 
422 |         # Validate the project during initialization
423 |         try:
424 |             await self._validate_project_access()
425 |             await self._ensure_models_loaded()
426 |             self.is_functional = True
427 |             logger.info(
428 |                 f"Gemini Cloud Project backend initialized with {len(self.available_models)} models "
429 |                 f"for project: {self.gcp_project_id}"
430 |             )
431 |         except Exception as e:
432 |             logger.error(f"Failed to validate project or load models: {e}")
433 |             self.is_functional = False
434 | 
---
src/connectors/gemini_cloud_project.py [lines 166–172]
166 | class GeminiCloudProjectConnector(GeminiBackend):
167 |     """Connector that uses OAuth authentication with user-specified GCP project.
168 | 
169 |     This connector requires a valid Google Cloud Project ID and uses OAuth2
170 |     authentication to access Gemini Code Assist API with standard/enterprise tier features.
171 |     All usage is billed to the specified GCP project.
172 |     """
---
src/connectors/gemini_oauth_personal.py [lines 98–104]
98 | class GeminiOAuthPersonalConnector(GeminiBackend):
99 |     """Connector that uses access_token from gemini-cli oauth_creds.json file.
100 | 
101 |     This is a specialized Gemini connector that reads the access_token
102 |     from the gemini-cli generated oauth_creds.json file and uses it as the API key.
103 |     It handles token refresh automatically when the token expires.
104 |     """
