"""Lectura de PDF dentro de ZIP en memoria, con límites de descompresión."""
import hashlib
import io
import zipfile
import zlib
from .documents import document_kind, expected_source, source_label, document_url, ranked_sources
from .network import SourceError, MAX_PDF_BYTES, MAX_ZIP_BYTES, download_pdf, download_zip


def zip_pdfs(data, row, year):
    if len(data) > MAX_ZIP_BYTES:
        raise SourceError('El ZIP supera 50 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 500 or sum(m.file_size for m in members) > 100 * 1024 * 1024:
                raise SourceError('El ZIP supera los límites de lectura: 500 archivos o 100 MB descomprimidos.')
            candidates = []
            for member in members:
                if member.is_dir() or not member.filename.lower().endswith('.pdf'):
                    continue
                candidate = {**row, 'nombre_archivo': member.filename, 'extensi_n': 'pdf'}
                score = ranked_sources([candidate], '', year)[0][0]
                if score >= 80:
                    candidates.append((member, candidate))
            if not candidates:
                raise SourceError(f'El ZIP no contiene PDF identificados como {source_label(year)}.')
            if len(candidates) > 8:
                raise SourceError('El ZIP contiene más de ocho documentos candidatos. Cargue el PDF correspondiente al contrato.')
            archive_sha = hashlib.sha256(data).hexdigest()
            for member, candidate in candidates:
                if member.flag_bits & 1 or member.file_size > MAX_PDF_BYTES:
                    raise SourceError('Un PDF del ZIP está cifrado o supera 20 MB. Cargue una copia legible.')
                with archive.open(member) as handle:
                    pdf = handle.read(MAX_PDF_BYTES + 1)
                if len(pdf) > MAX_PDF_BYTES or not pdf.lstrip().startswith(b'%PDF'):
                    raise SourceError('Un archivo del ZIP no es un PDF válido o supera 20 MB.')
                yield pdf, {**candidate, '_archivo_zip': row.get('nombre_archivo', ''),
                            '_candidatos_zip': len(candidates),
                            '_miembro_zip': member.filename, '_zip_sha256': archive_sha}
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error):
        raise SourceError('No fue posible leer el ZIP. Cargue el PDF de soporte directamente.') from None


def source_pdfs(row, year):
    if str(row.get('extensi_n', '')).lower().lstrip('.') == 'zip':
        yield from zip_pdfs(download_zip(document_url(row)), row, year)
    elif document_kind(row.get('nombre_archivo', '')) == expected_source(year):
        yield download_pdf(document_url(row)), row
    else:
        raise SourceError(f'Para este año, seleccione {source_label(year)}.')
