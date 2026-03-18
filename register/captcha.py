"""FunCaptcha cloud solver service (YesCaptcha / CapSolver compatible).

Environment variables:
  CAPTCHA_CLIENT_KEY  — Cloud solver API key (required)
  CAPTCHA_CLOUD_URL   — Cloud solver base URL (default: https://api.yescaptcha.com)
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

DEFAULT_CLOUD_URL = "https://api.yescaptcha.com"


class FunCaptchaService:
    """Cloud-based FunCaptcha (Arkose Labs) solver."""

    def __init__(
        self,
        client_key: str = "",
        cloud_url: str = "",
    ):
        self.client_key = client_key or os.environ.get("CAPTCHA_CLIENT_KEY", "")
        self.cloud_url = (
            cloud_url or os.environ.get("CAPTCHA_CLOUD_URL", "") or DEFAULT_CLOUD_URL
        ).rstrip("/")

    def solve(
        self,
        website_url: str,
        public_key: str,
        subdomain: Optional[str] = None,
        blob_data: Optional[str] = None,
    ) -> Optional[str]:
        """Submit FunCaptcha task and poll for token.

        Args:
            website_url: The page URL where FunCaptcha is loaded.
            public_key: Arkose Labs public key (pk= parameter from iframe src).
            subdomain: Optional custom subdomain (e.g. "client-api.arkoselabs.com").
            blob_data: Optional blob data from the challenge.

        Returns:
            Solved token string, or None on failure.
        """
        if not self.client_key:
            print("[Captcha] CAPTCHA_CLIENT_KEY not set")
            return None

        task_id = self._create_task(website_url, public_key, subdomain, blob_data)
        if not task_id:
            return None
        return self._poll_result(task_id)

    def _create_task(
        self,
        website_url: str,
        public_key: str,
        subdomain: Optional[str],
        blob_data: Optional[str],
    ) -> Optional[str]:
        task: dict = {
            "type": "FunCaptchaTaskProxyless",
            "websiteURL": website_url,
            "websitePublicKey": public_key,
        }
        if subdomain:
            task["funcaptchaApiJSSubdomain"] = subdomain
        if blob_data:
            task["data"] = blob_data

        try:
            r = requests.post(
                f"{self.cloud_url}/createTask",
                json={"clientKey": self.client_key, "task": task},
                timeout=15,
            )
            data = r.json()
            if data.get("errorId") != 0:
                print(f"[Captcha] Create error: {data.get('errorDescription')}")
                return None
            return data.get("taskId")
        except Exception as exc:
            print(f"[Captcha] Create failed: {exc}")
            return None

    def _poll_result(self, task_id: str, max_retries: int = 60) -> Optional[str]:
        time.sleep(5)
        for _ in range(max_retries):
            try:
                r = requests.post(
                    f"{self.cloud_url}/getTaskResult",
                    json={"clientKey": self.client_key, "taskId": task_id},
                    timeout=15,
                )
                data = r.json()
                if data.get("errorId") != 0:
                    print(f"[Captcha] Poll error: {data.get('errorDescription')}")
                    return None
                if data.get("status") == "ready":
                    return (data.get("solution") or {}).get("token")
                if data.get("status") != "processing":
                    return None
            except Exception:
                pass
            time.sleep(3)
        print("[Captcha] Solver timeout")
        return None
