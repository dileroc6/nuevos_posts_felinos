import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from pipeline.utils.logger import get_logger


class ContentGenerator:
    """Generate SEO-oriented blog posts using a custom GPT model."""

    SYSTEM_PROMPT = (
        "Eres un redactor SEO senior que crea artículos con tono humano, "
        "alineados con EEAT, fáciles de escanear y listos para publicar."
    )

    def __init__(self, model: Optional[str] = None, temperature: float = 0.6) -> None:
        self.logger = get_logger(__name__)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY no está configurado.")
        self.client = OpenAI(api_key=api_key)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.1-mycustomspec")
        self.temperature = temperature

    def build_prompt(self, payload: Dict[str, str]) -> str:
        prompt = {
            "keyword_principal": payload.get("keyword", ""),
            "descripcion": payload.get("descripcion", ""),
            "titulo_base": payload.get("titulo", ""),
            "categoria": payload.get("categoria", ""),
            "instrucciones": {
                "tono": "humano, cercano, experto",
                "seo": [
                    "usar variaciones semánticas",
                    "incluir listas y tablas cuando aporten claridad",
                    "usar H2/H3 jerárquicos",
                    "redactar FAQs con respuestas completas",
                    "sugerir prompts de imágenes generativas",
                ],
                "formato_respuesta": "JSON válido con campos especificados",
            },
            "campos_solicitados": {
                "title": "Título optimizado",
                "meta_description": "Máximo 155 caracteres",
                "h1": "Encabezado principal",
                "content_html": "Contenido completo en HTML semántico",
                "faqs": "Lista de 5 objetos con pregunta y respuesta",
                "image_prompts": "Lista de al menos 3 prompts de imagen",
            },
        }
        return json.dumps(prompt, ensure_ascii=False)

    def generate(self, payload: Dict[str, str]) -> Dict[str, Any]:
        user_prompt = self.build_prompt(payload)
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Devuelve **exclusivamente** un JSON válido. "
                            "El JSON debe tener: title, meta_description, h1, content_html, "
                            "faqs (lista de objetos con question y answer) e image_prompts "
                            "(lista de strings)."
                        ),
                    },
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_output_tokens=2000,
            )
        except Exception as exc:
            self.logger.error("Error al llamar a OpenAI: %s", exc)
            raise

        content = self._extract_text(response)
        if not content:
            raise ValueError("La respuesta del modelo está vacía.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            self.logger.error("Respuesta del modelo no es JSON válido: %s", content)
            raise ValueError("El modelo no devolvió JSON válido.") from exc

        self._validate_payload(parsed)
        return parsed

    def _extract_text(self, response: Any) -> str:
        try:
            return response.output[0].content[0].text
        except (AttributeError, IndexError, KeyError):
            self.logger.error("Formato de respuesta inesperado: %s", response)
            raise ValueError("No se pudo extraer texto de la respuesta del modelo.")

    def _validate_payload(self, payload: Dict[str, Any]) -> None:
        required_fields = [
            "title",
            "meta_description",
            "h1",
            "content_html",
            "faqs",
            "image_prompts",
        ]
        missing = [field for field in required_fields if field not in payload]
        if missing:
            raise ValueError(f"La respuesta del modelo no incluye los campos: {missing}")
        if not isinstance(payload.get("faqs"), list) or len(payload["faqs"]) < 5:
            raise ValueError("La respuesta debe incluir al menos 5 FAQs.")
        if not isinstance(payload.get("image_prompts"), list) or not payload["image_prompts"]:
            raise ValueError("Se requieren prompts de imagen.")

    def is_semantic_duplicate(
        self,
        candidate: Dict[str, str],
        index_records: List[Dict[str, str]],
    ) -> bool:
        """Use the language model to assess if content already exists on the same topic."""

        relevant_records = self._select_relevant_index(candidate, index_records)
        if not relevant_records:
            return False

        request_payload = {
            "candidate": {
                "title": candidate.get("titulo", ""),
                "keyword": candidate.get("keyword", ""),
                "description": candidate.get("descripcion", ""),
                "category": candidate.get("categoria", ""),
                "slug": candidate.get("slug", ""),
                "url": candidate.get("url", ""),
            },
            "existing_posts": relevant_records,
            "instrucciones": (
                "Evalúa si el candidato trata el mismo tema o intención que alguna entrada existente. "
                "Responde solo con JSON {\"duplicate\": bool, \"reason\": string, \"match_slug\": string}."
            ),
        }

        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Actúas como analista editorial. Identificas duplicados temáticos "
                            "en una base de contenidos existente."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Devuelve exclusivamente JSON válido con los campos duplicate (bool), "
                            "reason (string) y match_slug (string)."
                        ),
                    },
                    {"role": "user", "content": json.dumps(request_payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_output_tokens=400,
            )
        except Exception as exc:
            self.logger.error("Error evaluando duplicado con OpenAI: %s", exc)
            return False

        raw_text = self._extract_text(response)
        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError:
            self.logger.error("Respuesta de duplicado no es JSON válido: %s", raw_text)
            return False

        is_duplicate = bool(result.get("duplicate"))
        if is_duplicate:
            self.logger.info(
                "El modelo detectó duplicado: %s (coincidencia slug: %s)",
                result.get("reason", "sin motivo"),
                result.get("match_slug", ""),
            )
        return is_duplicate

    def _select_relevant_index(
        self,
        candidate: Dict[str, str],
        index_records: List[Dict[str, str]],
        limit: int = 25,
    ) -> List[Dict[str, str]]:
        keyword = (candidate.get("keyword") or "").strip().lower()
        category = (candidate.get("categoria") or "").strip().lower()

        filtered: List[Dict[str, str]] = []
        for record in index_records:
            record_keyword = (record.get("keyword") or "").strip().lower()
            record_category = (record.get("categoria") or "").strip().lower()
            if keyword and record_keyword and keyword in record_keyword:
                filtered.append(record)
            elif category and record_category and category == record_category:
                filtered.append(record)

        if not filtered:
            filtered = list(index_records)

        trimmed = filtered[:limit]
        return [
            {
                "title": rec.get("titulo", ""),
                "keyword": rec.get("keyword", ""),
                "category": rec.get("categoria", ""),
                "slug": rec.get("slug", ""),
                "url": rec.get("url", ""),
            }
            for rec in trimmed
        ]
