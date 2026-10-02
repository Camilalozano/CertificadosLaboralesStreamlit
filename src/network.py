"""Descargas acotadas, sin incluir credenciales o rutas PAR en los errores."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

ORACLE_HOST = 'objectstorage.us-ashburn-1.oraclecloud.com'
DOCUMENT_HOST = 'community.secop.gov.co'
MAX_CSV_BYTES = 50 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024


class SourceError(ValueError):
    """Mensaje que puede mostrarse al usuario."""


def allowed_url(url, host, path=None):
    try:
        p = urlparse(str(url).strip())
        return (p.scheme == 'https' and p.hostname == host and p.port in (None, 443)
                and not p.username and not p.password and (path is None or p.path == path))
    except ValueError:
        return False


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl, urlparse(req.full_url).hostname):
            raise SourceError('La fuente redirigió a una dirección no permitida.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_url(url, limit, label, headers=None):
    opener = build_opener(SameHostRedirect())
    request = Request(url, headers={'User-Agent': 'CertificadosATENEA/1.0', **(headers or {})})
    for attempt in range(3):
        try:
            with opener.open(request, timeout=35) as response:
                declared = response.headers.get('Content-Length', '')
                if declared and int(declared) > limit:
                    raise SourceError(f'{label}: el archivo supera el tamaño permitido.')
                content = response.read(limit + 1)
            if not content or len(content) > limit:
                raise SourceError(f'{label}: respuesta vacía o demasiado grande.')
            return content
        except SourceError:
            raise
        except HTTPError as e:
            if e.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise SourceError(f'{label}: no fue posible descargar la fuente (HTTP {e.code}).') from None
        except (URLError, OSError, TimeoutError, ValueError):
            if attempt == 2:
                raise SourceError(f'{label}: error de conexión. Intente nuevamente.') from None
        time.sleep(0.5 * (attempt + 1))


def download_oracle(url):
    if not allowed_url(url, ORACLE_HOST) or '/p/' not in urlparse(url).path:
        raise SourceError('Configure una ruta PAR HTTPS válida de Oracle Object Storage.')
    return read_url(url.strip(), MAX_CSV_BYTES, 'Base Oracle')


def api_rows(params):
    endpoint = 'https://www.datos.gov.co/resource/dmgg-8hin.json'
    data = read_url(endpoint + '?' + urlencode(params), 8 * 1024 * 1024, 'Documentos SECOP')
    try:
        rows = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise SourceError('SECOP devolvió una respuesta incompatible.') from None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SourceError('SECOP devolvió una respuesta incompatible.')
    return rows


def download_pdf(url):
    if not allowed_url(url, DOCUMENT_HOST, '/Public/Archive/RetrieveFile/Index'):
        raise SourceError('El documento no tiene una URL de descarga válida de SECOP II.')
    data = read_url(url, MAX_PDF_BYTES, 'Documento SECOP', {'Referer': 'https://community.secop.gov.co/'})
    if not data.lstrip().startswith(b'%PDF'):
        raise SourceError('SECOP no devolvió un archivo PDF legible.')
    return data
