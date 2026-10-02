"""Preparación auditable del certificado y control de salida desactualizada."""
import hashlib
import json
from datetime import datetime, timezone
from .documents import list_documents, ranked_pdfs, document_url, has_modifications
from .network import download_pdf, SourceError
from .obligations import extract


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def prepare(contract):
    rows = list_documents(contract.fields['id_contrato'])
    warnings = []
    if has_modifications(rows):
        warnings.append('SECOP contiene documentos de modificación. Revise si cambiaron las obligaciones, el plazo o el contratista. La extracción corresponde al documento seleccionado.')
    result = {'documents': rows, 'warnings': warnings, 'extraction': None, 'pdf': b'', 'document': None}
    if not rows:
        warnings.append('No hay documentos en la fuente desde 2025 para este contrato. Puede cargar su minuta o transcribir las obligaciones.')
        return result
    attempted = set()
    # El ranking solo prioriza documentos vinculados al ID contractual exacto.
    for score, row in ranked_pdfs(rows, contract.fields['referencia']):
        if score < 80 or len(attempted) >= 3:
            continue
        url = document_url(row)
        if url in attempted:
            continue
        attempted.add(url)
        try:
            pdf = download_pdf(url)
            extraction = extract(pdf)
            result.update(extraction=extraction, pdf=pdf, document=row)
            warnings.extend(extraction.warnings)
            return result
        except SourceError:
            continue
    warnings.append('No se extrajeron obligaciones automáticamente. Seleccione un PDF del contrato o cargue una minuta legible.')
    return result


def audit(contract, catalog_sha, fields, obligations, original_items, source, source_sha, source_url, issued_on, signer, role):
    originals = {item['texto']: item.get('pagina') for item in original_items}
    return {
        'generado_en': datetime.now(timezone.utc).isoformat(),
        'version_app': '1.0.0', 'base_sha256': catalog_sha, 'fila_csv': contract.row_number,
        'id_contrato': contract.fields['id_contrato'], 'datos_originales': contract.fields,
        'datos_certificado': fields,
        'campos_editados': [k for k in fields if fields[k] != contract.fields.get(k, '')],
        'fuente_obligaciones': {'archivo': source, 'sha256': source_sha, 'url_secop': source_url},
        'obligaciones_originales': original_items,
        'obligaciones_certificado': [{'texto': o, 'pagina': originals.get(o),
                                      'origen': 'PDF' if o in originals else 'Edición manual'} for o in obligations],
        'fecha_documento': str(issued_on), 'firmante': signer, 'cargo': role,
        'estado': 'Borrador para revisión y firma',
    }
