import os
from typing import Dict, List

from pipeline.services.content_generator import ContentGenerator
from pipeline.services.google_sheet import GoogleSheetClient
from pipeline.services.wordpress import WordPressClient
from pipeline.utils.helpers import build_post_url, load_environment
from pipeline.utils.logger import get_logger


def orchestrate() -> None:
    load_environment()
    logger = get_logger(__name__)

    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise ValueError("GOOGLE_SPREADSHEET_ID no está configurado.")

    main_sheet = os.getenv("GOOGLE_MAIN_SHEET_NAME", "contenidos")
    index_sheet = os.getenv("GOOGLE_INDEX_SHEET_NAME", "indice_contenido")

    wordpress_base_url = os.getenv("WORDPRESS_BASE_URL")
    wordpress_user = os.getenv("WORDPRESS_USER")
    wordpress_password = os.getenv("WORDPRESS_PASSWORD")
    wordpress_jwt = os.getenv("WORDPRESS_JWT_TOKEN")

    google_client = GoogleSheetClient(spreadsheet_id, main_sheet, index_sheet)
    content_generator = ContentGenerator()
    wordpress_client = WordPressClient(
        base_url=wordpress_base_url,
        user=wordpress_user,
        password=wordpress_password,
        jwt_token=wordpress_jwt,
    )

    rows = google_client.get_rows_to_process()
    if not rows:
        logger.info("No hay filas con estado 'si'.")
        return

    index_records = google_client.get_index_records()

    for row in rows:
        row_number = row["row_number"]
        title = row.get("titulo", "")
        keyword = row.get("keyword", "")
        slug = row.get("slug", "")
        logger.info("Procesando fila %s: %s", row_number, title)

        try:
            if google_client.is_duplicate(title, keyword, slug, index_records):
                logger.info(
                    "Fila %s omitida: duplicado exacto detectado (título/keyword/slug).",
                    row_number,
                )
                google_client.log_duplicate(row_number)
                continue

            if content_generator.is_semantic_duplicate(row, index_records):
                logger.info(
                    "Fila %s omitida: duplicado semántico detectado por OpenAI.",
                    row_number,
                )
                google_client.log_duplicate(row_number)
                continue

            logger.info("Fila %s sin duplicados, generando contenido con OpenAI.", row_number)
            content_payload = content_generator.generate(row)
            logger.info("Contenido generado para fila %s, publicando en WordPress.", row_number)
            post_response = wordpress_client.publish_post(
                title=content_payload.get("title", title),
                content_html=content_payload.get("content_html", ""),
                meta_description=content_payload.get("meta_description"),
                category_name=row.get("categoria") or content_payload.get("categoria"),
                slug=slug,
            )
            post_id = post_response.get("id")
            logger.info("Fila %s publicada con ID %s", row_number, post_id)

            response_slug = post_response.get("slug") or slug
            post_url = post_response.get("link") or build_post_url(wordpress_client.base_url, response_slug or "")
            post_id_str = str(post_id) if post_id is not None else ""
            excerpt = (content_payload.get("meta_description") or "")[:200]

            google_client.mark_status(row_number, "hecho")
            logger.info("Fila %s marcada como 'hecho'. Actualizando columnas auxiliares.", row_number)
            google_client.update_main_row(
                row_number,
                {
                    "slug": response_slug or "",
                    "url": post_url,
                    "post_id": post_id_str,
                    "excerpt": excerpt,
                },
            )
            logger.info("Fila %s actualizada con slug=%s, post_id=%s", row_number, response_slug, post_id_str)

            index_entry: Dict[str, str] = {
                "titulo": content_payload.get("title", title),
                "keyword": keyword,
                "categoria": row.get("categoria", ""),
                "slug": response_slug or "",
                "url": post_url,
                "post_id": post_id_str,
                "excerpt": excerpt,
            }
            index_records.append(index_entry)

        except Exception as exc:
            logger.exception("Error procesando fila %s: %s", row_number, exc)
            google_client.mark_status(row_number, "error")
            continue


if __name__ == "__main__":
    orchestrate()
