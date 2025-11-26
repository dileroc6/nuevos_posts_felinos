from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Sequence, Tuple

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from pipeline.utils.helpers import extract_slug, load_google_credentials, sanitize_status
from pipeline.utils.logger import get_logger

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetClient:
    """Wrapper around Google Sheets API for reading and updating pipeline data."""

    HEADER_TITULO = "título"
    HEADER_KEYWORD = "keyword principal"
    HEADER_DESCRIPCION = "descripción para el gpt"
    HEADER_CATEGORIA = "categoría"
    HEADER_EJECUTAR = "ejecutar?"
    HEADER_SLUG = "slug"

    HEADER_ALIASES = {
        HEADER_TITULO: {"título", "titulo"},
        HEADER_KEYWORD: {"keyword principal", "keyword_principal"},
        HEADER_DESCRIPCION: {
            "descripción para el gpt",
            "descripcion para el gpt",
            "descripcion",
            "descripción",
        },
        HEADER_CATEGORIA: {"categoría", "categoria"},
        HEADER_EJECUTAR: {"ejecutar?", "ejecutar", "status", "estado"},
        HEADER_SLUG: {"slug", "url"},
    }

    ADDITIONAL_ALIASES = {
        "slug": {"slug", "url"},
        "url": {"url", "link"},
        "post_id": {"post_id", "post id", "id", "postid"},
        "excerpt": {"extracto", "extracto_200", "extracto 200", "resumen", "excerpt"},
    }

    SHEET_MAIN = "main"
    SHEET_INDEX = "index"

    def __init__(
        self,
        spreadsheet_id: str,
        main_sheet_name: str,
        index_sheet_name: str,
    ) -> None:
        self.logger = get_logger(__name__)
        self.spreadsheet_id = spreadsheet_id
        self.main_sheet_name = main_sheet_name
        self.index_sheet_name = index_sheet_name
        self._service = self._build_service()

        self._main_header_indices: Dict[str, int] = {}
        self._main_header_aliases: Dict[str, str] = {}
        self._main_header_length: int = 0
        self._main_normalized_header: Dict[str, int] = {}

        self._index_header_indices: Dict[str, int] = {}
        self._index_header_aliases: Dict[str, str] = {}
        self._index_header_length: int = 0
        self._index_normalized_header: Dict[str, int] = {}

    def _build_service(self):
        credentials_info = load_google_credentials()
        credentials = Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def _fetch_sheet_values(self, sheet_name: str) -> Optional[List[List[str]]]:
        range_name = f"{sheet_name}!A:Z"
        try:
            response = (
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=range_name)
                .execute()
            )
        except HttpError as exc:
            self.logger.error("No se pudo leer la hoja %s: %s", sheet_name, exc)
            return None
        return response.get("values", [])

    def _resolve_header_indices(
        self,
        normalized_header: Dict[str, int],
    ) -> Tuple[Dict[str, int], Dict[str, str]]:
        resolved: Dict[str, int] = {}
        alias_used: Dict[str, str] = {}
        for canonical, aliases in self.HEADER_ALIASES.items():
            for alias in aliases:
                normalized_alias = alias.strip().lower()
                if normalized_alias in normalized_header:
                    resolved[canonical] = normalized_header[normalized_alias]
                    alias_used[canonical] = normalized_alias
                    break
        return resolved, alias_used

    def _record_headers(
        self,
        header_row: Sequence[str],
        indices: Dict[str, int],
        aliases: Dict[str, str],
        sheet_type: str,
        normalized_map: Dict[str, int],
    ) -> None:
        length = len(header_row)
        if sheet_type == self.SHEET_MAIN:
            self._main_header_length = length
            self._main_header_indices = indices
            self._main_header_aliases = aliases
            self._main_normalized_header = normalized_map
        else:
            self._index_header_length = length
            self._index_header_indices = indices
            self._index_header_aliases = aliases
            self._index_normalized_header = normalized_map

    def _parse_rows(
        self,
        raw_rows: Sequence[Sequence[str]],
        sheet_type: str,
    ) -> List[Dict[str, str]]:
        if not raw_rows:
            self._record_headers([], {}, {}, sheet_type, {})
            return []

        header_row = raw_rows[0]
        normalized = {value.strip().lower(): idx for idx, value in enumerate(header_row)}
        resolved_indices, alias_used = self._resolve_header_indices(normalized)
        self._record_headers(header_row, resolved_indices, alias_used, sheet_type, normalized)

        parsed_rows: List[Dict[str, str]] = []
        for row_idx, row in enumerate(raw_rows[1:], start=2):
            parsed_row = {
                "row_number": row_idx,
                "titulo": self._safe_get(row, resolved_indices, self.HEADER_TITULO),
                "keyword": self._safe_get(row, resolved_indices, self.HEADER_KEYWORD),
                "descripcion": self._safe_get(row, resolved_indices, self.HEADER_DESCRIPCION),
                "categoria": self._safe_get(row, resolved_indices, self.HEADER_CATEGORIA),
                "ejecutar": self._safe_get(row, resolved_indices, self.HEADER_EJECUTAR),
            }

            slug_raw = self._safe_get(row, resolved_indices, self.HEADER_SLUG)
            parsed_row["slug_raw"] = slug_raw
            parsed_row["slug"] = extract_slug(slug_raw)

            url_value = self._get_value_by_normalized(row, normalized, "url")
            parsed_row["url"] = self._derive_url(url_value) or self._derive_url(slug_raw)

            parsed_rows.append(parsed_row)

        return parsed_rows

    def _safe_get(
        self,
        row: Sequence[str],
        header_index: Dict[str, int],
        header_name: str,
    ) -> str:
        idx = header_index.get(header_name)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    def _get_value_by_normalized(
        self,
        row: Sequence[str],
        normalized_map: Dict[str, int],
        key: str,
    ) -> str:
        idx = normalized_map.get(key)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    def _derive_url(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        value = raw_value.strip()
        if value.lower().startswith("http://") or value.lower().startswith("https://"):
            return value
        return ""

    def get_rows_to_process(self) -> List[Dict[str, str]]:
        raw_rows = self._fetch_sheet_values(self.main_sheet_name)
        if not raw_rows:
            return []

        parsed_rows = self._parse_rows(raw_rows, self.SHEET_MAIN)
        filtered = [row for row in parsed_rows if sanitize_status(row.get("ejecutar")) == "si"]
        self.logger.info("Encontradas %s filas para procesar", len(filtered))
        return filtered

    def get_index_records(self) -> List[Dict[str, str]]:
        raw_rows = self._fetch_sheet_values(self.index_sheet_name)
        if not raw_rows:
            return []

        parsed_rows = self._parse_rows(raw_rows, self.SHEET_INDEX)
        return parsed_rows

    def is_duplicate(
        self,
        title: str,
        keyword: str,
        slug: str,
        index_records: List[Dict[str, str]],
    ) -> bool:
        title_normalized = (title or "").strip().lower()
        keyword_normalized = (keyword or "").strip().lower()
        slug_normalized = extract_slug(slug)
        for record in index_records:
            recorded_title = (record.get("titulo") or "").strip().lower()
            recorded_keyword = (record.get("keyword") or "").strip().lower()
            recorded_slug = record.get("slug") or extract_slug(record.get("url", ""))
            if slug_normalized and recorded_slug and recorded_slug == slug_normalized:
                return True
            if recorded_title and recorded_title == title_normalized:
                return True
            if keyword_normalized and recorded_keyword and recorded_keyword == keyword_normalized:
                return True
        return False

    def mark_status(self, row_number: int, status: str) -> None:
        ejecutar_idx = self._main_header_indices.get(self.HEADER_EJECUTAR, 4)
        column_letter = self._column_letter(ejecutar_idx)
        range_name = f"{self.main_sheet_name}!{column_letter}{row_number}"
        self._update_values(range_name, [[status]])

    def log_duplicate(self, row_number: int) -> None:
        self.logger.info("Fila %s marcada como duplicado", row_number)
        self.mark_status(row_number, "duplicado")

    def update_main_row(self, row_number: int, data: Dict[str, str]) -> None:
        if not data:
            return

        if not self._main_header_indices:
            raw_rows = self._fetch_sheet_values(self.main_sheet_name) or []
            self._parse_rows(raw_rows, self.SHEET_MAIN)

        if not self._main_header_indices:
            self.logger.warning(
                "No se pudo actualizar la hoja principal: no se detectaron encabezados."
            )
            return

        updates = []
        for key, value in data.items():
            idx = self._get_main_column_index(key)
            if idx is None:
                self.logger.debug("Columna no encontrada para '%s', se omite actualización", key)
                continue
            column_letter = self._column_letter(idx)
            updates.append(
                {
                    "range": f"{self.main_sheet_name}!{column_letter}{row_number}",
                    "values": [[value or ""]],
                }
            )

        if not updates:
            return

        self.logger.info(
            "Actualizando fila %s en %s con columnas: %s",
            row_number,
            self.main_sheet_name,
            ", ".join(
                f"{item['range'].split('!')[-1]}={item['values'][0][0]}" for item in updates
            ),
        )

        body = {"valueInputOption": "RAW", "data": updates}
        try:
            (
                self._service.spreadsheets()
                .values()
                .batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
                .execute()
            )
        except HttpError as exc:
            self.logger.error("Error actualizando fila %s: %s", row_number, exc)

    def _update_values(self, range_name: str, values: List[List[str]]) -> None:
        body = {"values": values}
        try:
            (
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    body=body,
                )
                .execute()
            )
        except HttpError as exc:
            self.logger.error("Error actualizando rango %s: %s", range_name, exc)

    def _append_values(self, range_name: str, values: List[List[str]]) -> None:
        body = {"values": values}
        try:
            (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body=body,
                )
                .execute()
            )
        except HttpError as exc:
            self.logger.error("Error agregando valores al rango %s: %s", range_name, exc)

    def batch_mark_status(self, updates: List[Tuple[int, str]]) -> None:
        for chunk in self._batched_updates(updates, size=50):
            data = []
            for row, status in chunk:
                ejecutar_idx = self._main_header_indices.get(self.HEADER_EJECUTAR, 4)
                column_letter = self._column_letter(ejecutar_idx)
                data.append(
                    {
                        "range": f"{self.main_sheet_name}!{column_letter}{row}",
                        "values": [[status]],
                    }
                )
            body = {"valueInputOption": "RAW", "data": data}
            try:
                (
                    self._service.spreadsheets()
                    .values()
                    .batchUpdate(spreadsheetId=self.spreadsheet_id, body=body)
                    .execute()
                )
            except HttpError as exc:
                self.logger.error("Error en batchUpdate: %s", exc)

    def _batched_updates(self, items: List[Tuple[int, str]], size: int):
        iterator = iter(items)
        while True:
            chunk = list(itertools.islice(iterator, size))
            if not chunk:
                break
            yield chunk

    def _column_letter(self, index: int) -> str:
        if index < 0:
            return "A"
        result = ""
        current = index + 1
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            result = chr(65 + remainder) + result
        return result or "A"

    def _get_main_column_index(self, key: str) -> Optional[int]:
        normalized_key = (key or "").strip().lower()
        if not normalized_key:
            return None

        if not self._main_normalized_header:
            raw_rows = self._fetch_sheet_values(self.main_sheet_name) or []
            self._parse_rows(raw_rows, self.SHEET_MAIN)

        if not self._main_normalized_header:
            return None

        candidates = {normalized_key}

        header_aliases = self.HEADER_ALIASES.get(normalized_key)
        if not header_aliases:
            header_aliases = self.HEADER_ALIASES.get(key)
        if header_aliases:
            candidates.update(alias.strip().lower() for alias in header_aliases)

        additional = self.ADDITIONAL_ALIASES.get(normalized_key)
        if additional:
            candidates.update(alias.strip().lower() for alias in additional)

        for candidate in candidates:
            idx = self._main_normalized_header.get(candidate)
            if idx is not None:
                return idx
        return None
