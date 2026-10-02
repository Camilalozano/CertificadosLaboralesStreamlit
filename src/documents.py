"""Consulta paginada por ID contractual, inspirada en Posmedia_IA_Codex."""
import re
from concurrent.futures import ThreadPoolExecutor
from .contracts import fold, reference_key
from .network import SourceError, api_rows, DOCUMENT_DATASETS


def list_documents(contract_id, dataset='dmgg-8hin', process=None):
    if not re.fullmatch(r'CO1\.PCCNTR\.\d+', contract_id, re.I):
        raise SourceError('La base no contiene un id_contrato válido para buscar documentos en SECOP.')
    result, seen = [], set()
    page_size = 500
    for offset in range(0, 5000, page_size):
        query = {'proceso': process} if process else {'n_mero_de_contrato': contract_id.upper()}
        rows = api_rows({**query, '$limit': page_size,
                         '$offset': offset, '$order': 'id_documento'}, dataset=dataset)
        for row in rows:
            owner = str(row.get('n_mero_de_contrato') or '').upper()
            if process and row.get('proceso') != process:
                raise SourceError('SECOP devolvió documentos de otro proceso. Vuelva a consultar.')
            if process and owner and owner != contract_id.upper():
                continue  # Un proceso compartido no autoriza documentos de otro contrato.
            if not process and owner != contract_id.upper():
                raise SourceError('SECOP devolvió documentos de otro contrato. Vuelva a consultar.')
            key = str(row.get('id_documento', ''))
            if key not in seen:
                result.append({**row, '_dataset': dataset,
                               '_asociacion': 'contrato' if owner else 'proceso'})
                seen.add(key)
        if len(rows) < page_size:
            return result
    raise SourceError('El contrato supera 5.000 documentos. Refine la consulta en SECOP.')


def lookup_documents(contract_id):
    """Consulta históricos y documentos precontractuales del proceso vinculado."""
    rows, warnings, seen = [], [], set()
    def collect(process=None):
        with ThreadPoolExecutor(max_workers=5) as pool:
            jobs = [(ds, pool.submit(list_documents, contract_id, ds, process)) for ds in DOCUMENT_DATASETS]
            for dataset, job in jobs:
                try:
                    for row in job.result():
                        key = str(row.get('id_documento') or document_url(row))
                        if key not in seen:
                            rows.append(row)
                            seen.add(key)
                except SourceError as error:
                    warnings.append(f'{DOCUMENT_DATASETS[dataset]}: {error} La consulta puede estar incompleta.')
    # Se valida antes de lanzar consultas para no repetir el mismo error cinco veces.
    if not re.fullmatch(r'CO1\.PCCNTR\.\d+', contract_id, re.I):
        raise SourceError('La base no contiene un id_contrato válido para buscar documentos en SECOP.')
    collect()
    processes = {row.get('proceso') for row in rows
                 if re.fullmatch(r'CO1\.[A-Z]+\.\d+', str(row.get('proceso', '')))}
    if len(processes) == 1:
        collect(processes.pop())
    elif len(processes) > 1:
        warnings.append('Hay varios procesos asociados al contrato. No se añadieron documentos sin ID contractual; cargue el soporte correcto.')
    return rows, warnings


def document_url(row):
    value = row.get('url_descarga_documento', '')
    return value.get('url', '') if isinstance(value, dict) else str(value)


def expected_source(year):
    return 'estudio_previo' if year >= 2026 else 'minuta'


def source_label(year):
    return 'estudios previos' if year >= 2026 else 'minuta o clausulado'


def document_kind(name):
    # Evaluar el nombre del PDF, no la carpeta contenedora de un ZIP.
    name = re.split(r'[/\\]', str(name))[-1]
    name = re.sub(r'[^A-Z0-9]+', ' ', fold(name)).strip()
    if re.search(r'\b(?:ESTUDIOS?(?: Y DOCUMENTOS?)? PREVIOS?|DOCUMENTOS? PREVIOS?|EP)\b', name):
        return 'estudio_previo'
    if 'MINUTA' in name or 'CLAUSULADO' in name:
        return 'minuta'
    return None


def ranked_sources(rows, reference, year):
    candidates = []
    for row in rows:
        name = fold(row.get('nombre_archivo', ''))
        extension = str(row.get('extensi_n', '')).lower().lstrip('.')
        if extension not in {'pdf', 'zip'}:
            continue
        if extension == 'pdf':
            score = 100 if document_kind(name) == expected_source(year) else -200
        else:
            # Los contenedores pueden tener nombres genéricos; sus PDF se filtran después.
            score = 80
            if 'PREVIO' in name or re.search(r'CARPETA[ _-]*1\b', name):
                score += 30
        if reference_key(reference) in reference_key(name):
            score += 20
        if any(x in name for x in ['CUENTA', 'INFORME', 'POLIZA', 'ANTECEDENTE', 'MODIFICACION', 'SOLICITUD', 'ARL', 'CESION', 'OTROSI', 'ADICION', 'IDONEIDAD', 'EXPERIENCIA']):
            score -= 300
        candidates.append((score, str(row.get('fecha_carga', '')), str(row.get('id_documento') or ''), row))
    candidates.sort(key=lambda x: x[:3], reverse=True)
    return [(score, row) for score, _, _, row in candidates]


def ranked_pdfs(rows, reference):
    """Compatibilidad con el orden de selección de minutas anterior a 2026."""
    return [(score, row) for score, row in ranked_sources(rows, reference, 2025)
            if str(row.get('extensi_n', '')).lower().lstrip('.') == 'pdf']


def has_modifications(rows):
    return any(any(word in fold(row.get('nombre_archivo', '')) for word in ('MODIFICACION', 'OTROSI', 'ADICION', 'CESION')) for row in rows)
