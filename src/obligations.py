"""Extrae solamente la sección de obligaciones específicas con página de origen.

Adaptación del enfoque de Posmedia a minutas y estudios previos.
No usa un modelo generativo ni completa obligaciones ausentes.
"""
import io
import re
import unicodedata
from dataclasses import dataclass
from pypdf import PdfReader
from .network import MAX_PDF_BYTES, SourceError


@dataclass
class Extraction:
    obligations: list[dict]
    section: str
    pages: list[str]
    warnings: list[str]


def pdf_pages(data):
    if len(data) > MAX_PDF_BYTES:
        raise SourceError('El PDF supera 20 MB.')
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(''):
            raise SourceError('El PDF está protegido por contraseña.')
        if len(reader.pages) > 150:
            raise SourceError('El PDF supera 150 páginas.')
        pages = [page.extract_text() or '' for page in reader.pages]
    except SourceError:
        raise
    except Exception:
        raise SourceError('No se pudo leer el PDF. Cargue una copia legible.') from None
    if sum(len(re.sub(r'\s+', '', p)) for p in pages) < 100:
        raise SourceError('El PDF es una imagen o no tiene texto legible. Cargue una versión con OCR o transcriba las obligaciones.')
    return pages


def folded_offsets(value):
    chars, offsets = [], []
    for i, char in enumerate(value):
        normalized = ''.join(c for c in unicodedata.normalize('NFKD', char) if not unicodedata.combining(c)).upper()
        chars.append(normalized)
        offsets.extend([i] * len(normalized))
    return ''.join(chars), offsets


def clean(value):
    value = re.sub(r'\[\[PAGE:\d+\]\]', '', value)
    return re.sub(r'\s+', ' ', value.replace('\u00ad', '')).strip()


def extract(data):
    pages = pdf_pages(data)
    page_texts = []
    for n, page in enumerate(pages, 1):
        # Retirar el folio aislado en los bordes, sin tocar la numeración de obligaciones.
        page = re.sub(rf'\A\s*{n}\s*\n|\n\s*{n}\s*\Z', '', page)
        page = re.sub(r'(?im)^\s*(?:Página\s+\d+\s+de\s+\d+|www\.agenciaatenea[^\n]*|Cr\.?\s*10[^\n]*|Carrera\s+10[^\n]*|PBX\s*:[^\n]*|atencionalciudadano@agenciaatenea\.gov\.co[^\n]*|Información:\s*Línea\s*195[^\n]*)\s*$', '', page)
        page_texts.append(f'[[PAGE:{n}]]\n{page}')
    joined = '\n'.join(page_texts)
    normalized, offsets = folded_offsets(joined)
    heading = re.compile(r'OBLIGACIONES\s+ESPECIFICAS(?:\s+DEL\s+CONTRATISTA)?\s*[:.\-]?')
    sections = []
    for start in heading.finditer(normalized):
        tail = normalized[start.end():]
        # Excluir obligaciones específicas de la Agencia u otros sujetos.
        if re.match(r'\s*(?:DE\s+(?:LA|LAS|LOS)|DEL\s+(?!CONTRATISTA\b))', tail):
            continue
        # Una cláusula distinta cierra la sección, nunca se añade a la última obligación.
        ends = [m.start() for pattern in [r'\bCLAUSULA\s+(?:PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA|SEPTIMA|OCTAVA|NOVENA|DECIMA|[IVX]+)\b\s*[:.\-–—]',
                r'\bOBLIGACIONES\s+(?:ESPECIFICAS\s+)?DE\s+(?:LA\s+CONTRATANTE|LA\s+AGENCIA|LA\s+ENTIDAD)',
                r'\b(?:C|D)\)\s+OBLIGACIONES', r'\bPARAGRAFO\s*[:.\-]',
                r'(?m)^\s*(?:(?:\d+(?:\.\d+)*[.)]?|[A-Z][.)])\s+)?(?:MODALIDAD\s+DE\s+SELECCION|VALOR\s+(?:DEL|ESTIMADO)|FORMA\s+DE\s+PAGO|ANALISIS\s+(?:DEL|DE)|GARANTIAS|PRODUCTOS\s+ESPERADOS|PLAZO\s+DE\s+EJECUCION)\b']
                if (m := re.search(pattern, tail))]
        end = start.end() + (min(ends) if ends else min(len(tail), 35000))
        begin_orig = offsets[start.end()] if start.end() < len(offsets) else len(joined)
        end_orig = offsets[end] if end < len(offsets) else len(joined)
        section = joined[begin_orig:end_orig]
        markers = list(re.finditer(r'(?<![\d\w])(\d{1,2})[.)]\s+(?=[A-ZÁÉÍÓÚÜÑ])', section))
        selected = []
        expected = 1
        for marker in markers:
            if int(marker.group(1)) == expected:
                selected.append(marker)
                expected += 1
        if not selected:
            continue
        warnings = []
        if not ends:
            warnings.append('No se identificó el cierre de la sección. Revise el final de la última obligación.')
        obligations = []
        for i, marker in enumerate(selected):
            stop = selected[i+1].start() if i+1 < len(selected) else len(section)
            value = clean(section[marker.end():stop])
            if not value:
                continue
            prior = list(re.finditer(r'\[\[PAGE:(\d+)\]\]', joined[:begin_orig+marker.start()]))
            obligations.append({'numero': int(marker.group(1)), 'texto': value,
                                'pagina': int(prior[-1].group(1)) if prior else 1})
        if any(re.search(r'(?:^|\s)\d{1,2}[.)]\s+[A-ZÁÉÍÓÚÑ]', o['texto']) for o in obligations):
            warnings.append('La numeración contiene saltos o subapartados. Compare la extracción con el PDF.')
        sections.append(Extraction(obligations, clean(section), pages, warnings))
    if not sections:
        raise SourceError('No se localizó una sección numerada de obligaciones específicas del contratista. Seleccione el soporte correspondiente al año o transcriba el texto del documento.')
    result = max(sections, key=lambda s: len(s.obligations))
    if len(sections) > 1:
        result.warnings.append('El PDF contiene varias secciones candidatas. Verifique cuál corresponde al contratista.')
    return result
