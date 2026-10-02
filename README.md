# Certificaciones laborales y contractuales · ATENEA

Aplicativo Streamlit para buscar contratos por número o palabras del objeto, recuperar su minuta desde SECOP II, extraer las obligaciones específicas y descargar un certificado editable en Word.

## Uso

1. Ingresa una referencia completa, un número corto o palabras del objeto y pulsa **Buscar contrato**.
2. Si hay varias coincidencias, selecciona la referencia, el contratista y el ID correctos. Los duplicados se muestran por separado. Al seleccionar el contrato aparecen sus observaciones y la tabla de modificación reportada.
3. Pulsa **Obtener obligaciones de SECOP**. La aplicación consulta los documentos asociados al `id_contrato` exacto y prioriza minutas y clausulados.
4. Revisa los datos, el documento elegido y las obligaciones con su página de origen. Puedes seleccionar otro PDF, cargar una minuta o transcribir obligaciones. Las correcciones quedan en la trazabilidad.
5. Pulsa **Generar certificado Word** y después **Descargar certificado Word**. También puedes descargar la trazabilidad JSON y el PDF consultado.

El formato conserva la estructura del generador original de ATENEA. La salida es un borrador para revisión y firma. No se presupone cédula de ciudadanía para todos los proveedores ni se incorpora automáticamente el nombre de un firmante.

## Desplegar en Streamlit Community Cloud

- Repositorio: `Camilalozano/CertificadosLaboralesStreamlit`
- Rama: `main`
- Archivo principal: `app.py`
- Versión recomendada de Python: **3.12**

En **Advanced settings → Secrets**, configura:

```toml
ORACLE_PAR_URL = "PEGA_AQUI_LA_RUTA_PAR_DEL_CSV_MAESTRO"
FIRMANTE = ""
CARGO_FIRMANTE = "Subgerencia de Gestión Administrativa"
```

Utiliza el enlace PAR suministrado por Camila al objeto `analisis_contratacion/gold_exports/tabla_maestra_completa/tabla_maestra_completa.csv`. El código no publica el token PAR ni copia el CSV a GitHub. En el entorno local de trabajo ya está configurado en `.streamlit/secrets.toml`, excluido del repositorio. Debes trasladarlo al panel de secretos al desplegar.

Si vence el PAR, actualiza el secreto o ingresa una nueva ruta en el panel lateral. También puedes cargar temporalmente un CSV con las mismas columnas. El cache de la base dura una hora y el botón **Actualizar base** lo invalida.

Documentación oficial: [despliegue y secretos en Streamlit](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

## Ejecutar localmente

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
# Copiar .streamlit/secrets.toml.example a .streamlit/secrets.toml y completar el PAR
python -m streamlit run app.py
```

La configuración también admite `ORACLE_PAR_URL`, `FIRMANTE` y `CARGO_FIRMANTE` como variables de entorno. El secreto de Streamlit tiene prioridad cuando existe.

## Fuentes y alcance

- **Base Oracle:** referencia contractual, ID SECOP, objeto, contratista, identificación, valor, fechas, plazo, estado y URL del proceso. Se leen como texto para preservar identificadores y ceros iniciales.
- **Observaciones y modificación:** antes de obtener las obligaciones, se muestra una alerta con el texto completo de `observaciones_inferido` y una tabla con `tipo_modificacion`, `identificador_modificacion (modificaciones)`, `estado_modificacion (modificaciones)` y `fecha_de_aprobacion (modificaciones)`. Si no hay observaciones se informa su ausencia; los campos vacíos de la tabla muestran **Sin información**. Los valores corresponden a la fila seleccionada, no a un historial completo. Son información de consulta en pantalla y no se agregan al certificado Word.
- **Documentos SECOP:** [Archivos Descarga Desde 2025, dmgg-8hin](https://www.datos.gov.co/Estad-sticas-Nacionales/SECOP-II-Archivos-Descarga-Desde-2025/dmgg-8hin). API: `https://www.datos.gov.co/resource/dmgg-8hin.json`. Consulta paginada con `n_mero_de_contrato = id_contrato`.
- Las obligaciones no son una columna de esta fuente: se extraen del texto de los PDF descargados. La aplicación conserva el documento, su hash SHA-256 y la página de cada obligación.
- Los contratos anteriores a 2025 pueden no tener documentos en este conjunto. Se permite cargar una minuta alternativa. No se consulta automáticamente un conjunto histórico diferente.
- La extracción reconoce secciones numeradas de **obligaciones específicas** en minutas de prestación de servicios. No genera contenido ni usa un LLM. Si el documento es una imagen, requiere OCR previo o transcripción manual. PDF máximo: 20 MB y 150 páginas.
- Las modificaciones se señalan para revisión. La aplicación no consolida automáticamente otrosíes, cesiones, suspensiones ni versiones de las obligaciones. El valor y las fechas vienen de la base maestra y las obligaciones del PDF elegido, que puede corresponder al contrato inicial.
- Plazo contractual y fechas reportadas no equivalen a una certificación automática del tiempo efectivamente trabajado.
- Si la duración es solo un número sin unidad, se muestra **unidad por confirmar**. No se sustituyen valores por columnas inferidas ni se asumen días o meses. El campo puede corregirse contra la minuta antes de descargar.
- Cada cambio en la selección, fuente, campos, obligaciones o datos de expedición invalida la descarga previa y exige generar de nuevo.
- Formato disponible: **DOCX**. No requiere Microsoft Word o LibreOffice en el servidor. No incluye firma electrónica ni expedición automática.

## Código de referencia

- [Generador original de certificados](https://github.com/Camilalozano/GeneracionCertificadosLaborales/blob/main/generador_masivo_certificadoslaborales.py), blob `01351cf4641b7ff5f6d3da81f9f603169da774a6`: estructura del Word, campos contractuales, pie institucional y aviso de revisión.
- [Posmedia_IA_Codex](https://github.com/Camilalozano/Posmedia_IA_Codex), revisión `7f8674ac8750e171520d7681901abe09aca5e00d`: patrón de consulta, descarga SECOP, revisión editable, evidencia y trazabilidad. Se adaptó la extracción de obligaciones IES a minutas de contratistas.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

Las pruebas usan datos sintéticos y no necesitan Oracle ni documentos personales. Cubren búsqueda, ambigüedad, identificadores, valor monetario, fechas, documentos de otro contrato, paginación, límites de destino, sección de obligaciones, generación Word y flujo de Streamlit.

Los archivos de consulta y pruebas reales se mantienen fuera del repositorio, al igual que los certificados generados y el PAR.

## Estructura

```text
app.py                    Interfaz de búsqueda, revisión y descarga
src/contracts.py          Lectura CSV y selección del contrato
src/network.py            Conexiones y límites de descarga
src/documents.py          Consulta y selección de PDF en SECOP
src/obligations.py        Extracción de obligaciones y páginas
src/certificate.py        Generación Word en memoria
src/workflow.py           Preparación y trazabilidad
tests/                    Pruebas unitarias y de interfaz
```
