from __future__ import annotations

import ipaddress
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_env_file(env_path: Path) -> None:
    """Lightweight .env loader without external dependencies."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


class AdminApiError(RuntimeError):
    """Raised when the Project Yuki Admin REST API returns an error."""

    def __init__(self, message: str, status_code: Optional[int] = None, code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class _AdminProxyHandler(urllib.request.ProxyHandler):
    """Connect directly to loopback backends, even with a system-wide proxy."""

    def proxy_open(self, req, proxy, scheme):
        host = urllib.parse.urlsplit(req.full_url).hostname or ""
        if host.rstrip(".").lower() == "localhost":
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and address.is_loopback:
            return None
        return super().proxy_open(req, proxy, scheme)


class AdminApiClient:
    """HTTP client for Project Yuki's `/api/admin/*` endpoints."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        # Load admin-cli/.env or repo root .env if present
        cli_root = Path(__file__).resolve().parents[2]
        load_env_file(cli_root / ".env")
        load_env_file(cli_root.parent / ".env")

        resolved_url = base_url or os.getenv("PJYK_ADMIN_BASE_URL", "http://localhost:8080")
        self.base_url = resolved_url.rstrip("/")
        self.token = token if token is not None else os.getenv("PJYK_ADMIN_TOKEN", "").strip()
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_AdminProxyHandler())

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            filtered = {k: str(v) for k, v in params.items() if v is not None and v != ""}
            if filtered:
                url = f"{url}?{urllib.parse.urlencode(filtered)}"

        headers: Dict[str, str] = {
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = (
                self.token if self.token.startswith("Bearer ") else f"Bearer {self.token}"
            )

        data_bytes: Optional[bytes] = None
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                payload = json.loads(raw)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message") or err_body
                code = err_json.get("code")
            except Exception:
                msg = err_body or str(exc)
                code = None
            raise AdminApiError(
                f"HTTP {exc.code} calling {method} {url}: {msg}",
                status_code=exc.code,
                code=code,
            ) from exc
        except urllib.error.URLError as exc:
            raise AdminApiError(
                f"Failed to connect to {url}: {exc.reason}"
            ) from exc

        if isinstance(payload, dict) and "success" in payload:
            if not payload.get("success"):
                raise AdminApiError(
                    payload.get("message") or f"API call failed: {method} {path}",
                    code=payload.get("code"),
                )
            return payload.get("data")
        return payload

    # --- Anime APIs ---

    def list_animes(
        self,
        review_status: Optional[str] = None,
        year: Optional[int] = None,
        season: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self._request(
            "GET",
            "/api/admin/animes",
            params={
                "reviewStatus": review_status,
                "year": year,
                "season": season,
            },
        ) or []

    def create_anime(
        self,
        title: Optional[Dict[str, Optional[str]]] = None,
        cover_image: Optional[str] = None,
        start_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if cover_image is not None:
            payload["coverImage"] = cover_image
        if start_date is not None:
            payload["startDate"] = start_date
        return self._request("POST", "/api/admin/animes", body=payload)

    def update_anime(
        self,
        anime_id: int,
        title: Optional[Dict[str, Optional[str]]] = None,
        cover_image: Optional[str] = None,
        review_status: Optional[str] = None,
        start_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"animeId": anime_id}
        if title is not None:
            payload["title"] = title
        if cover_image is not None:
            payload["coverImage"] = cover_image
        if review_status is not None:
            payload["reviewStatus"] = review_status
        if start_date is not None:
            payload["startDate"] = start_date
        return self._request("PUT", "/api/admin/animes", body=payload)

    def delete_anime(self, anime_id: int) -> None:
        self._request("DELETE", f"/api/admin/animes/{anime_id}")

    # --- Mapping APIs ---

    def list_unlinked_mappings(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/admin/mappings/unlinked") or []

    def update_mapping_anime(self, mapping_id: int, anime_id: Optional[int]) -> Dict[str, Any]:
        return self._request(
            "PUT",
            "/api/admin/mappings/anime",
            body={"mappingId": mapping_id, "animeId": anime_id},
        )

    def create_mapping(self, platform: str, platform_id: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/api/admin/mappings",
            body={"platform": platform, "platformId": str(platform_id)},
        )

    def delete_mapping(self, mapping_id: int) -> None:
        self._request("DELETE", f"/api/admin/mappings/{mapping_id}")

    # --- Task APIs ---

    def trigger_anime_fetch(
        self,
        year: int,
        season: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> str:
        return self._request(
            "POST",
            "/api/admin/tasks/anime-fetch",
            params={"year": year, "season": season, "platform": platform},
        )

    def trigger_mapping_fetch(
        self,
        year: int,
        season: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> str:
        return self._request(
            "POST",
            "/api/admin/tasks/mapping-fetch",
            params={"year": year, "season": season, "platform": platform},
        )

    def trigger_mapping_link(self) -> str:
        return self._request("POST", "/api/admin/tasks/mapping-link")

    def trigger_metric_recalculation(self) -> str:
        return self._request("POST", "/api/admin/tasks/metric-recalculation")
