from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


class KieAPIError(RuntimeError):
    """An API response or task result indicates an error."""


class KieClient:
    _BASE_URL = "https://api.kie.ai"
    _CREATE_TASK_PATH = "/api/v1/jobs/createTask"
    _TASK_INFO_PATH = "/api/v1/jobs/recordInfo"
    _UPLOAD_BASE_URL = "https://kieai.redpandaai.co"
    _UPLOAD_PATH = "/api/file-stream-upload"
    _MAX_IMAGE_BYTES = 20 * 1024 * 1024
    _IMAGE_MIME_TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }

    def __init__(self, api_key: str, request_timeout: float = 60.0) -> None:
        if not api_key.strip():
            raise ValueError("Kie.ai API key must not be empty.")
        self._api_key = api_key
        self._request_timeout = request_timeout

    def create_task(self, model: str, input_data: Mapping[str, Any]) -> str:
        response = self._request_json(
            self._CREATE_TASK_PATH,
            method="POST",
            body={"model": model, "input": dict(input_data)},
        )
        data = response.get("data")
        task_id = data.get("taskId") if isinstance(data, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise KieAPIError("Kie.ai create-task response did not include data.taskId.")
        return task_id

    def upload_image(self, image_path: Path) -> str:
        if not image_path.is_file():
            raise ValueError(f"Image path is not a file: {image_path}")

        return self.upload_image_bytes(image_path.name, image_path.read_bytes())

    def upload_image_bytes(self, file_name: str, file_bytes: bytes) -> str:
        mime_type = self._IMAGE_MIME_TYPES.get(Path(file_name).suffix.lower())
        if mime_type is None:
            raise ValueError(f"Unsupported image type for upload: {file_name}")

        if len(file_bytes) > self._MAX_IMAGE_BYTES:
            raise ValueError(f"Image exceeds Kie.ai's 20 MB upload limit: {file_name}")

        boundary = f"----KieVideoUpload{time.time_ns():x}"
        safe_name = Path(file_name).name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="uploadPath"\r\n\r\n'
                "images/user-uploads\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
            + file_bytes
            + f"\r\n--{boundary}--\r\n".encode("ascii")
        )
        request = urllib.request.Request(
            f"{self._UPLOAD_BASE_URL}{self._UPLOAD_PATH}",
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as error:
            raw_body = error.read()
            message = self._error_message(raw_body) or error.reason
            raise KieAPIError(f"Kie.ai upload returned HTTP {error.code}: {message}") from error

        payload = self._parse_json_response(raw_body, "upload")
        if str(payload.get("code")) != "200":
            message = self._error_message(raw_body) or "Unknown upload error."
            raise KieAPIError(f"Kie.ai upload error (code {payload.get('code')}): {message}")
        data = payload.get("data")
        download_url = data.get("downloadUrl") if isinstance(data, dict) else None
        if not isinstance(download_url, str) or not download_url:
            raise KieAPIError("Kie.ai upload response did not include data.downloadUrl.")
        return download_url

    def wait_for_completion(
        self,
        task_id: str,
        *,
        poll_interval: float = 3.0,
        poll_timeout: float = 900.0,
        on_state: Callable[[str], None] | None = None,
    ) -> str:
        if poll_interval <= 0:
            raise ValueError("Poll interval must be greater than zero.")
        if poll_timeout <= 0:
            raise ValueError("Poll timeout must be greater than zero.")

        deadline = time.monotonic() + poll_timeout
        delay = poll_interval
        last_state: str | None = None
        while True:
            response = self._request_json(
                self._TASK_INFO_PATH,
                method="GET",
                query={"taskId": task_id},
            )
            data = response.get("data")
            if not isinstance(data, dict):
                raise KieAPIError("Kie.ai task response did not include a data object.")

            state = data.get("state")
            if not isinstance(state, str):
                raise KieAPIError("Kie.ai task response did not include a state.")
            if state != last_state and on_state is not None:
                on_state(state)
            last_state = state

            if state == "success":
                return self._extract_result_url(data)
            if state == "fail":
                fail_code = data.get("failCode")
                fail_message = data.get("failMsg") or "Video generation failed."
                code_text = f" (code {fail_code})" if fail_code else ""
                raise KieAPIError(f"{fail_message}{code_text}")
            if state not in {"waiting", "queuing", "generating"}:
                raise KieAPIError(f"Kie.ai returned an unknown task state: {state!r}.")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for Kie.ai task {task_id}.")
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, 30.0)

    def download_video(self, url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
                with destination.open("xb") as output:
                    shutil.copyfileobj(response, output)
        except FileExistsError:
            raise FileExistsError(f"Refusing to overwrite existing file: {destination}") from None
        return destination

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._BASE_URL}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        headers = {"Authorization": f"Bearer {self._api_key}"}
        request_body = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            request_body = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=request_body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
                raw_body = response.read()
        except urllib.error.HTTPError as error:
            raw_body = error.read()
            message = self._error_message(raw_body) or error.reason
            raise KieAPIError(f"Kie.ai returned HTTP {error.code}: {message}") from error

        payload = self._parse_json_response(raw_body, "API")

        code = payload.get("code")
        if str(code) != "200":
            message = self._error_message(raw_body) or "Unknown API error."
            raise KieAPIError(f"Kie.ai API error (code {code}): {message}")
        return payload

    @staticmethod
    def _parse_json_response(raw_body: bytes, source: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise KieAPIError(f"Kie.ai returned a response that was not valid JSON ({source}).") from error
        if not isinstance(payload, dict):
            raise KieAPIError(f"Kie.ai returned an unexpected JSON response ({source}).")
        return payload

    @staticmethod
    def _error_message(raw_body: bytes) -> str | None:
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if isinstance(payload, dict):
            message = payload.get("msg") or payload.get("message")
            return message if isinstance(message, str) else None
        return None

    @staticmethod
    def _extract_result_url(data: Mapping[str, Any]) -> str:
        result = data.get("response")
        if not isinstance(result, dict):
            result_json = data.get("resultJson")
            if isinstance(result_json, str):
                try:
                    result = json.loads(result_json)
                except json.JSONDecodeError as error:
                    raise KieAPIError("Kie.ai returned invalid resultJson for the completed task.") from error

        urls = result.get("resultUrls") if isinstance(result, dict) else None
        if not isinstance(urls, list) or not urls or not isinstance(urls[0], str):
            raise KieAPIError("Completed Kie.ai task did not include a video result URL.")
        return urls[0]
