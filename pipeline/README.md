# Pipeline de Publicación Automática

Este proyecto automatiza la generación y publicación de artículos optimizados para SEO a partir de datos almacenados en Google Sheets. El contenido se genera con un GPT personalizado y se publica en WordPress mediante su API REST. El flujo completo se ejecuta manualmente desde GitHub Actions.

## Requisitos previos

- Hoja de cálculo en Google Sheets con:
  - Hoja principal (por ejemplo `contenidos`) con columnas: `Título`, `Keyword Principal`, `Descripción para el GPT`, `Categoría`, `Slug` (o `URL`), `Ejecutar?`. Puedes añadir columnas opcionales como `Post_ID`, `URL` o `Extracto_200` si deseas conservar los resultados.
  - Hoja `indice_contenido` solo para lectura, utilizada únicamente para detectar duplicados (puede usar columna `Slug` o `URL`; el pipeline extrae el slug desde la URL si es necesario).
- Sitio WordPress con la API REST activa.
- Cuenta en OpenAI con acceso al modelo personalizado.

## Credenciales de Google Sheets

1. Entra a [Google Cloud Console](https://console.cloud.google.com/), crea un proyecto y habilita la **Google Sheets API**.
2. Crea una **Service Account** y descarga el archivo JSON de credenciales.
3. Comparte la hoja de cálculo con el correo de la Service Account con permisos de edición.
4. Copia el contenido completo del JSON y guárdalo en un secreto de GitHub llamado `GOOGLE_CREDENTIALS_JSON`.

## Configuración de OpenAI

1. Crea un secreto `OPENAI_API_KEY` con tu clave de OpenAI.
2. Si usas un modelo personalizado, crea un secreto `OPENAI_MODEL` con el spec-key real (por ejemplo `gpt-5.1-mycustomspec`).

## Autenticación en WordPress

Tienes dos opciones:

- **Application Password (recomendado)**
  1. En WordPress, ve a `Usuarios > Perfil` y genera una Application Password.
  2. Crea los secretos `WORDPRESS_USER` y `WORDPRESS_PASSWORD` en GitHub con tus credenciales.
  3. Define el secreto `WORDPRESS_AUTH_METHOD` con el valor `application_password`.

- **JWT Token**
  1. Instala y configura un plugin de JWT en WordPress.
  2. Genera un token y guárdalo en el secreto `WORDPRESS_JWT_TOKEN`.
  3. Define el secreto `WORDPRESS_AUTH_METHOD` con el valor `jwt`.

En ambos casos debes configurar el secreto `WORDPRESS_BASE_URL` con la URL base del sitio (por ejemplo `https://example.com`).

## Variables adicionales

Configura los siguientes secretos para conectar con tu Google Sheet:

- `GOOGLE_SPREADSHEET_ID`: ID de la hoja (lo encuentras en la URL).
- `GOOGLE_MAIN_SHEET_NAME`: nombre de la hoja principal (por defecto `contenidos`).
- `GOOGLE_INDEX_SHEET_NAME`: nombre de la hoja índice (por defecto `indice_contenido`).

## Flujo detallado del pipeline

1. **Carga de entorno**: `pipeline/main.py` carga variables desde secretos o `.env` y prepara el logger.
2. **Inicialización de servicios**: se crea un cliente de Google Sheets, el generador de contenido (`ContentGenerator`) con el modelo personalizado y el cliente de WordPress.
3. **Lectura de hojas**: se obtienen las filas de `contenidos_nuevos` con `Ejecutar? = si` y el índice histórico solo para lectura.
4. **Validación de duplicados**:
  - Se revisa coincidencia exacta por título, keyword o slug/URL contra el índice.
  - Si pasa, se envía una petición adicional al modelo de OpenAI para verificar duplicidad semántica.
5. **Generación de contenido**: si la fila es válida, se construye un prompt enriquecido (SEO, EEAT, FAQs, prompts de imagen) y se solicita al modelo una respuesta estrictamente en JSON.
6. **Publicación en WordPress**: con la respuesta se publica un post vía REST API (Application Password o JWT); el pipeline crea la categoría si es necesario y respeta el slug proporcionado.
7. **Actualización de la hoja principal**: se marca la fila como `hecho` y se escriben `Slug`, `URL`, `Post_ID` y `Extracto_200` (si existen las columnas).
8. **Manejo de errores**: cualquier excepción en la fila se registra, la fila se marca como `error` y el ciclo continúa con la siguiente.

## Ejecución manual del pipeline

1. Sube este repositorio a GitHub.
2. Configura todos los secretos mencionados en `Settings > Secrets and variables > Actions`.
3. En GitHub, ve a la pestaña **Actions**, selecciona **Blog Pipeline** y pulsa **Run workflow**.
4. El workflow instala dependencias y ejecuta `python -m pipeline.main`. Durante la corrida verás logs estructurados que indican:
  - cuántas filas se detectaron con `Ejecutar? = si`;
  - cuándo se detecta un duplicado exacto o semántico y la fila se omite;
  - cuándo se envía la solicitud a OpenAI y la publicación a WordPress;
  - cuándo se marca la fila como `hecho` y se actualizan las columnas `Slug`, `URL`, `Post_ID` y `Extracto_200` (si existen).
  - al final verás un resumen con el total de filas procesadas, omitidas y con error.
5. El script nunca escribe en `indice_contenido`; solo lo usa como referencia. Toda la retroalimentación (ID, URL, extracto) se vuelca en la hoja `contenidos_nuevos` para que la otra automatización continúe usando el índice sin interferencias.

## Desarrollo local

1. Crea un archivo `.env` en la raíz con las mismas variables de entorno que los secretos.
2. Instala dependencias: `pip install -r pipeline/requirements.txt`.
3. Ejecuta `python -m pipeline.main` desde la raíz del repositorio (esto garantiza que Python reconozca el paquete `pipeline`).

## Manejo de errores

- Las filas con duplicados (exactos o detectados semánticamente) se marcan como `duplicado` y se registran en los logs.
- Si ocurre un error al generar contenido o publicar en WordPress, la fila se marca como `error` y el pipeline continúa con la siguiente entrada.
- Si notas `ModuleNotFoundError: No module named 'pipeline'`, ejecuta el script como módulo (`python -m pipeline.main`) o exporta `PYTHONPATH=.` antes de lanzarlo; asegúrate también de que existan los archivos `__init__.py` en `pipeline/`, `pipeline/services/` y `pipeline/utils/`.
