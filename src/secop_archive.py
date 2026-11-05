"""Descarga verificable de todos los documentos inventariados, sin expandir ZIP."""
import csv
import hashlib
import io
import re
import zipfile
from .documents import document_url
from .network import SourceError, allowed_url, DOCUMENT_HOST, read_url


def build_archive(rows, reference):
    if not rows:
        raise SourceError('No hay documentos SECOP para descargar.')
    if len(rows) > 100:
        raise SourceError('Hay más de 100 documentos. Descargue los archivos desde el inventario para evitar superar la memoria disponible.')
    output, inventory, total = io.BytesIO(), [], 0
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, row in enumerate(rows, 1):
            name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', str(row.get('nombre_archivo') or 'documento')).strip(' .')[:150] or 'documento'
            name = f'{index:03d}_{name}'
            url = document_url(row)
            item = {'id_documento': row.get('id_documento', ''), 'archivo': name,
                    'proceso': row.get('proceso', ''), 'asociacion': row.get('_asociacion', ''),
                    'url': url, 'estado': '', 'bytes': 0, 'sha256': ''}
            try:
                if not allowed_url(url, DOCUMENT_HOST, '/Public/Archive/RetrieveFile/Index'):
                    raise SourceError('Enlace de descarga SECOP inválido.')
                remaining = 100 * 1024 * 1024 - total
                if remaining <= 0:
                    raise SourceError('Se alcanzó el límite total de 100 MB.')
                data = read_url(url, min(50 * 1024 * 1024, remaining), 'Documento SECOP',
                                {'Referer': 'https://community.secop.gov.co/'})
                if data.lstrip()[:100].lower().startswith((b'<!doctype html', b'<html')):
                    raise SourceError('SECOP devolvió una página web en lugar del archivo.')
                archive.writestr(name, data)
                total += len(data)
                item.update(estado='Descargado', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            except SourceError as error:
                item['estado'] = 'No descargado: ' + str(error)
            inventory.append(item)
        manifest = io.StringIO(newline='')
        writer = csv.DictWriter(manifest, fieldnames=list(inventory[0]))
        writer.writeheader()
        writer.writerows(inventory)
        archive.writestr('inventario_documentos_secop.csv', '\ufeff' + manifest.getvalue())
    safe = re.sub(r'[^\w.-]', '_', reference)
    return f'Documentos_SECOP_{safe}.zip', output.getvalue(), inventory
