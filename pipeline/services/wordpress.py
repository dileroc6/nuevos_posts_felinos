import os
from typing import Any, Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

from pipeline.utils.logger import get_logger


class WordPressClient:
    """Wrapper for interacting with the WordPress REST API."""

    def __init__(
        self,
        base_url: str,
        user: Optional[str] = None,
        password: Optional[str] = None,
        jwt_token: Optional[str] = None,
        default_status: str = "publish",
    ) -> None:
        if not base_url:
            raise ValueError("WORDPRESS_BASE_URL no está configurado.")

        self.logger = get_logger(__name__)
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.default_status = default_status
        self.category_cache: Dict[str, int] = {}

        auth_method = os.getenv("WORDPRESS_AUTH_METHOD", "application_password").lower()
        if auth_method == "jwt":
            if not jwt_token:
                raise ValueError("Se requiere WORDPRESS_JWT_TOKEN para autenticación JWT.")
            self.session.headers.update({"Authorization": f"Bearer {jwt_token}"})
        else:
            if not user or not password:
                raise ValueError(
                    "Se requieren WORDPRESS_USER y WORDPRESS_PASSWORD para autenticación básica."
                )
            self.session.auth = HTTPBasicAuth(user, password)

    def publish_post(
        self,
        title: str,
        content_html: str,
        meta_description: Optional[str],
        category_name: Optional[str],
        slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": title,
            "content": content_html,
            "status": self.default_status,
        }
        if meta_description:
            payload["excerpt"] = meta_description[:300]
        if slug:
            payload["slug"] = slug.strip()

        if category_name:
            category_id = self._ensure_category(category_name)
            if category_id:
                payload["categories"] = [category_id]

        response = self.session.post(
            f"{self.base_url}/wp-json/wp/v2/posts",
            json=payload,
            timeout=30,
        )
        if response.status_code >= 400:
            self.logger.error(
                "Error publicando en WordPress (%s): %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()
        data = response.json()
        self.logger.info("Artículo publicado en WordPress con ID %s", data.get("id"))
        return data

    def _ensure_category(self, category_name: str) -> Optional[int]:
        normalized = category_name.strip().lower()
        if normalized in self.category_cache:
            return self.category_cache[normalized]

        category_id = self._find_category(normalized)
        if category_id:
            self.category_cache[normalized] = category_id
            return category_id

        category_id = self._create_category(category_name)
        if category_id:
            self.category_cache[normalized] = category_id
        return category_id

    def _find_category(self, normalized_name: str) -> Optional[int]:
        params = {"search": normalized_name, "per_page": 1}
        response = self.session.get(
            f"{self.base_url}/wp-json/wp/v2/categories",
            params=params,
            timeout=30,
        )
        if response.status_code >= 400:
            self.logger.error(
                "Error buscando categoría '%s': %s",
                normalized_name,
                response.text,
            )
            return None
        items = response.json()
        if not items:
            return None
        return items[0].get("id")

    def _create_category(self, category_name: str) -> Optional[int]:
        payload = {"name": category_name.strip()}
        response = self.session.post(
            f"{self.base_url}/wp-json/wp/v2/categories",
            json=payload,
            timeout=30,
        )
        if response.status_code >= 400:
            self.logger.error(
                "Error creando categoría '%s': %s",
                category_name,
                response.text,
            )
            return None
        data = response.json()
        return data.get("id")
