"""Consulta paginada por ID contractual, inspirada en Posmedia_IA_Codex."""
import re
from .contracts import fold, reference_key
from .network import SourceError, api_rows


def list_documents(contract_id):
    if not re.fullmatch(r'CO1\.PCCNTR\.\d+', contract_id, re.I):
        raise SourceError('La base no contiene un id_contrato válido para buscar documentos en SECOP.')
    result, seen = [], set()
    page_size = 500
    for offset in range(0, 5000, page_size):
        rows = api_rows({'n_mero_de_contrato': contract_id.upper(), '$limit': page_size,
                         '$offset': offset, '$order': 'id_documento'})
        for row in rows:
            if str(row.get('n_mero_de_contrato', '')).upper() != contract_id.upper():
                raise SourceError('SECOP devolvió documentos de otro contrato. Vuelva a consultar.')
            key = str(row.get('id_documento', ''))
            if key not in seen:
                result.append(row)
                seen.add(key)
        if len(rows) < page_size:
            return result
    raise SourceError('El contrato supera 5.000 documentos. Refine la consulta en SECOP.')


def document_url(row):
    value = row.get('url_descarga_documento', '')
    return value.get('url', '') if isinstance(value, dict) else str(value)


def ranked_pdfs(rows, reference):
    candidates = []
    for row in rows:
        name = fold(row.get('nombre_archivo', ''))
        if str(row.get('extensi_n', '')).lower().lstrip('.') != 'pdf':
            continue
        score = 0
        if 'MINUTA' in name or 'CLAUSULADO' in name:
            score += 100
        if 'OBLIGACIONES' in name:
            score += 80
        if reference_key(reference) in reference_key(name):
            score += 20
        if any(x in name for x in ['CUENTA', 'INFORME', 'POLIZA', 'ANTECEDENTE', 'MODIFICACION', 'SOLICITUD', 'ARL']):
            score -= 150
        candidates.append((score, str(row.get('fecha_carga', '')), int(row.get('id_documento') or 0), row))
    candidates.sort(key=lambda x: x[:3], reverse=True)
    return [(score, row) for score, _, _, row in candidates]


def has_modifications(rows):
    return any(any(word in fold(row.get('nombre_archivo', '')) for word in ('MODIFICACION', 'OTROSI', 'ADICION', 'CESION')) for row in rows)
