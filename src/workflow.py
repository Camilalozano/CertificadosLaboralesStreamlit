"""Preparación auditable del certificado y control de salida desactualizada."""
import hashlib
import json
from datetime import datetime, timezone
from .contracts import contract_year
from .documents import lookup_documents, ranked_sources, document_url, has_modifications, source_label
from .archives import source_pdfs
from .network import SourceError
from .obligations import extract


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def extract_document(row, year):
    failures = []
    for pdf, document in source_pdfs(row, year):
        try:
            extraction = extract(pdf)
            if document.get('_candidatos_zip', 0) > 1:
                extraction.warnings.append('El ZIP contiene varios PDF del tipo requerido. Verifique que el PDF elegido corresponde al contratista y cargue otro si es necesario.')
            return {'extraction': extraction, 'pdf': pdf, 'document': document}
        except SourceError as error:
            failures.append(str(error))
    raise SourceError(failures[-1] if failures else 'No se encontró un PDF legible con obligaciones específicas.')


def prepare(contract, year=None):
    year = year if year is not None else contract_year(contract)[0]
    if year is None:
        raise SourceError('Confirme el año del contrato para aplicar la regla documental.')
    rows, warnings = lookup_documents(contract.fields['id_contrato'])
    if has_modifications(rows):
        warnings.append('SECOP contiene documentos de modificación. Revise si cambiaron las obligaciones, el plazo o el contratista. La extracción corresponde al documento seleccionado.')
    result = {'documents': rows, 'warnings': warnings, 'extraction': None, 'pdf': b'', 'document': None}
    if not rows:
        warnings.append(f'No se encontraron documentos para este contrato en las fuentes consultadas. Puede cargar {source_label(year)} o transcribir sus obligaciones.')
        return result
    attempted = set()
    # El ranking solo prioriza documentos vinculados al ID contractual exacto.
    failures = []
    for score, row in ranked_sources(rows, contract.fields['referencia'], year):
        if score < 80 or len(attempted) >= 5:
            continue
        url = document_url(row)
        if url in attempted:
            continue
        attempted.add(url)
        try:
            result.update(extract_document(row, year))
            return result
        except SourceError as error:
            failures.append(str(error))
            continue
    warnings.append(f'No se extrajeron obligaciones de {source_label(year)} para el año {year}. Cargue ese documento legible o transcriba sus obligaciones. No se usó otro tipo de documento automáticamente.')
    if failures:
        warnings.append(f'Último resultado de lectura: {failures[-1]}')
    return result


def audit(contract, catalog_sha, fields, obligations, original_items, source, source_sha, source_url, issued_on, signer, role, year=None, document=None):
    originals = {item['texto']: item.get('pagina') for item in original_items}
    detected_year, year_origin = contract_year(contract)
    year = year if year is not None else detected_year
    document = document or {}
    return {
        'generado_en': datetime.now(timezone.utc).isoformat(),
        'version_app': '1.1.0', 'base_sha256': catalog_sha, 'fila_csv': contract.row_number,
        'id_contrato': contract.fields['id_contrato'], 'datos_originales': contract.fields,
        'datos_certificado': fields,
        'campos_editados': [k for k in fields if fields[k] != contract.fields.get(k, '')],
        'regla_documental': {'año_contrato': year, 'origen_año': year_origin if detected_year == year else 'confirmado por el usuario',
                            'documento_esperado': source_label(year) if year else None},
        'fuente_obligaciones': {'archivo': source, 'sha256': source_sha, 'url_secop': source_url,
                               'dataset': document.get('_dataset'), 'asociacion': document.get('_asociacion'),
                               'proceso': document.get('proceso'), 'archivo_zip': document.get('_archivo_zip'),
                               'miembro_zip': document.get('_miembro_zip'), 'zip_sha256': document.get('_zip_sha256')},
        'obligaciones_originales': original_items,
        'obligaciones_certificado': [{'texto': o, 'pagina': originals.get(o),
                                      'origen': 'PDF' if o in originals else 'Edición manual'} for o in obligations],
        'fecha_documento': str(issued_on), 'firmante': signer, 'cargo': role,
        'estado': 'Borrador para revisión y firma',
    }
