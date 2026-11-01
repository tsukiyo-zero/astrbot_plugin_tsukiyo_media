"""ComfyUI HTTP 客户端：提交 / 轮询 / 取图 / 上传参考图。"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ...core.errors import BackendError, JobTimeout


class ComfyUIClient:
    """只做四件事：submit / wait / fetch / upload。业务逻辑不放在这里。"""

    def __init__(
        self,
        base_url: str,
        *,
        connect_timeout: float = 10.0,
        job_timeout: float = 180.0,
        poll_interval: float = 1.0,
        client_id: str = "tsukiyo-image",
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        if not self.base_url:
            raise BackendError("ComfyUI 地址为空")
        self.job_timeout = float(job_timeout)
        self.poll_interval = max(0.2, float(poll_interval))
        self.client_id = client_id
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=connect_timeout, read=60.0, write=60.0, pool=connect_timeout),
        )

    # ---------- 生命周期 ----------
    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ComfyUIClient:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    # ---------- 查询 ----------
    async def system_stats(self) -> dict[str, Any]:
        return await self._get_json("/system_stats")

    async def queue_state(self) -> dict[str, Any]:
        return await self._get_json("/queue")

    # ---------- 提交 ----------
    async def submit(self, prompt: dict[str, Any]) -> str:
        payload = {"prompt": prompt, "client_id": self.client_id}
        try:
            resp = await self._client.post("/prompt", json=payload)
        except httpx.HTTPError as exc:
            raise BackendError(f"连接 ComfyUI 失败：{exc}") from exc

        if resp.status_code >= 400:
            detail = self._error_detail(resp)
            raise BackendError(f"ComfyUI 拒绝任务（HTTP {resp.status_code}）：{detail}")

        data = resp.json()
        if data.get("node_errors"):
            raise BackendError(f"ComfyUI 节点校验失败：{self._short(data['node_errors'])}")
        prompt_id = str(data.get("prompt_id") or "")
        if not prompt_id:
            raise BackendError(f"ComfyUI 未返回 prompt_id：{self._short(data)}")
        return prompt_id

    # ---------- 等待 ----------
    async def wait(self, prompt_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        """阻塞到任务结束，返回 outputs。"""
        limit = float(timeout if timeout is not None else self.job_timeout)
        deadline = time.monotonic() + limit
        while True:
            entry = await self._history_entry(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if str(status.get("status_str") or "") == "error":
                    raise BackendError(f"ComfyUI 执行失败：{self._short(status.get('messages'))}")
                outputs = entry.get("outputs") or {}
                if outputs:
                    return outputs
                if status.get("completed"):
                    return outputs
            if time.monotonic() >= deadline:
                raise JobTimeout(f"等待 ComfyUI 出图超时（{limit:.0f}s）")
            await asyncio.sleep(self.poll_interval)

    async def history_entry(self, prompt_id: str) -> dict[str, Any] | None:
        """公开版本，供进度查询使用。"""
        return await self._history_entry(prompt_id)

    async def _history_entry(self, prompt_id: str) -> dict[str, Any] | None:
        try:
            resp = await self._client.get(f"/history/{prompt_id}")
        except httpx.HTTPError as exc:
            raise BackendError(f"查询 ComfyUI 历史失败：{exc}") from exc
        if resp.status_code >= 400:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        return data.get(prompt_id) or None

    # ---------- 取图 ----------
    async def fetch(self, filename: str, *, subfolder: str = "", folder_type: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        try:
            resp = await self._client.get("/view", params=params)
        except httpx.HTTPError as exc:
            raise BackendError(f"下载图片失败：{exc}") from exc
        if resp.status_code >= 400:
            raise BackendError(f"下载图片失败（HTTP {resp.status_code}）：{filename}")
        return resp.content

    # ---------- 上传 ----------
    async def upload_image(self, data: bytes, filename: str, *, subfolder: str = "tsukiyo_media") -> str:
        files = {"image": (filename, data, _guess_mime(filename))}
        form = {"overwrite": "true", "type": "input"}
        if subfolder:
            form["subfolder"] = subfolder
        try:
            resp = await self._client.post("/upload/image", files=files, data=form)
        except httpx.HTTPError as exc:
            raise BackendError(f"上传参考图失败：{exc}") from exc
        if resp.status_code >= 400:
            raise BackendError(f"上传参考图失败（HTTP {resp.status_code}）：{self._error_detail(resp)}")
        payload = resp.json()
        name = str(payload.get("name") or "")
        sub = str(payload.get("subfolder") or "")
        if not name:
            raise BackendError(f"上传参考图未返回文件名：{self._short(payload)}")
        return f"{sub}/{name}" if sub else name

    async def interrupt(self) -> None:
        try:
            await self._client.post("/interrupt")
        except httpx.HTTPError:
            pass

    # ---------- 工具 ----------
    async def _get_json(self, path: str) -> dict[str, Any]:
        try:
            resp = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise BackendError(f"请求 {path} 失败：{exc}") from exc
        if resp.status_code >= 400:
            raise BackendError(f"请求 {path} 失败（HTTP {resp.status_code}）")
        return resp.json()

    @staticmethod
    def _error_detail(resp: httpx.Response) -> str:
        try:
            payload = resp.json()
        except ValueError:
            return resp.text[:300]
        return ComfyUIClient._short(payload)

    @staticmethod
    def _short(value: Any, limit: int = 300) -> str:
        text = str(value)
        return text if len(text) <= limit else text[:limit] + "…"


def _guess_mime(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/png"
