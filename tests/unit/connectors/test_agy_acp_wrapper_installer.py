from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest
from src.connectors.agy_acp_wrapper_installer import install_latest_wrapper


def _archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        package.writestr("go-agy-acp-wrapper.exe", b"wrapper")
        package.writestr("README.md", b"readme")
    return output.getvalue()


@pytest.mark.asyncio
async def test_install_latest_downloads_verifies_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _archive()
    asset_name = "go-agy-acp-wrapper_1.2.3_windows_amd64.zip"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/latest"):
            return httpx.Response(
                200,
                json={
                    "tag_name": "v1.2.3",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": asset_name,
                            "browser_download_url": "https://download.test/wrapper.zip",
                        },
                        {
                            "name": "checksums.txt",
                            "browser_download_url": "https://download.test/checksums.txt",
                        },
                    ],
                },
            )
        if request.url.path.endswith("checksums.txt"):
            digest = hashlib.sha256(archive).hexdigest()
            return httpx.Response(200, text=f"{digest}  {asset_name}\n")
        return httpx.Response(200, content=archive)

    monkeypatch.setattr(
        "src.connectors.agy_acp_wrapper_installer.platform_asset_suffix",
        lambda: "_windows_amd64.zip",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await install_latest_wrapper(client, cache_dir=tmp_path)
        first_calls = len(calls)
        second = await install_latest_wrapper(client, cache_dir=tmp_path)

    assert first == second
    assert Path(first).read_bytes() == b"wrapper"
    assert len(calls) == first_calls + 1  # Only latest metadata is refreshed.


@pytest.mark.asyncio
async def test_install_latest_rejects_bad_checksum_without_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _archive()
    asset_name = "go-agy-acp-wrapper_1.2.3_windows_amd64.zip"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/latest"):
            return httpx.Response(
                200,
                json={
                    "tag_name": "v1.2.3",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": asset_name,
                            "browser_download_url": "https://download.test/wrapper.zip",
                        },
                        {
                            "name": "checksums.txt",
                            "browser_download_url": "https://download.test/checksums.txt",
                        },
                    ],
                },
            )
        if request.url.path.endswith("checksums.txt"):
            return httpx.Response(200, text=f"{'0' * 64}  {asset_name}\n")
        return httpx.Response(200, content=archive)

    monkeypatch.setattr(
        "src.connectors.agy_acp_wrapper_installer.platform_asset_suffix",
        lambda: "_windows_amd64.zip",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            await install_latest_wrapper(client, cache_dir=tmp_path)

    assert not list(tmp_path.glob("*/go-agy-acp-wrapper.exe"))


@pytest.mark.asyncio
async def test_install_latest_uses_cached_binary_offline(tmp_path: Path) -> None:
    cached = tmp_path / "v1.0.0" / "go-agy-acp-wrapper.exe"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cached")

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resolved = await install_latest_wrapper(client, cache_dir=tmp_path)

    assert resolved == str(cached)
