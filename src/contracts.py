"""Lectura del CSV maestro y búsqueda sin seleccionar coincidencias ambiguas."""
import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from .network import MAX_CSV_BYTES, SourceError

REFERENCE = 'referencia_del_contrato (contratos_electronicos)'
OBJECT = 'descripcion_del_proceso (contratos_electronicos)'
FIELDS = {
    'referencia': [REFERENCE, 'referencia_del_contrato'],
    'id_contrato': ['id_contrato', 'id_contrato (contratos_electronicos)'],
    'contratista': ['proveedor_adjudicado (contratos_electronicos)', 'proveedor_adjudicado'],
    'documento': ['documento_proveedor (contratos_electronicos)', 'documento_proveedor'],
    'tipo_documento': ['tipodocproveedor (contratos_electronicos)', 'tipodocproveedor'],
    'objeto': [OBJECT, 'descripcion_del_proceso'],
    'valor': ['valor_del_contrato (contratos_electronicos)', 'valor_del_contrato'],
    'inicio': ['fecha_de_inicio_del_contrato (contratos_electronicos)', 'fecha_de_inicio_del_contrato'],
    'fin': ['fecha_de_fin_del_contrato (contratos_electronicos)', 'fecha_de_fin_del_contrato'],
    'plazo': ['duraci_n_del_contrato (contratos_electronicos)', 'duracion_contrato'],
    'estado': ['estado_contrato (contratos_electronicos)', 'estado_contrato'],
    'url': ['urlproceso (contratos_electronicos)', 'urlproceso'],
}


def text(value):
    result = '' if value is None else str(value).strip()
    return '' if result.casefold() in {'nan', 'none', 'null', 'nat', 'no definido', 'no informado'} else result


def fold(value):
    normalized = unicodedata.normalize('NFKD', text(value))
    return ''.join(c for c in normalized if not unicodedata.combining(c)).upper()


def reference_key(value):
    return re.sub(r'[\s\-\u2010-\u2015\u2212]+', '', fold(value))


def contract_year(contract):
    """El año contractual se obtiene de la referencia, nunca del año de descarga."""
    years = set(re.findall(r'(?<!\d)(20\d{2})(?!\d)', contract.fields['referencia']))
    if len(years) == 1:
        return int(years.pop()), 'referencia del contrato'
    if len(years) > 1:
        return None, 'referencia con varios años'
    for value, origin in [
        (contract.raw.get('fecha_de_firma (contratos_electronicos)'), 'fecha de firma'),
        (contract.raw.get('año_inferido'), 'año reportado en la base'),
    ]:
        match = re.match(r'^(20\d{2})(?:\D|$)', text(value))
        if match:
            return int(match[1]), origin
    return None, 'año no identificado'


@dataclass
class Contract:
    fields: dict
    row_number: int
    raw: dict

    @property
    def key(self):
        return f'{self.fields["id_contrato"]}:{self.row_number}'


@dataclass
class Catalog:
    contracts: list[Contract]
    sha256: str


def parse_csv(data):
    if len(data) > MAX_CSV_BYTES:
        raise SourceError('La base supera 50 MB.')
    try:
        content = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise SourceError('El CSV debe estar codificado en UTF-8.') from None
    try:
        dialect = csv.Sniffer().sniff(content[:32768], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(content, newline=''), dialect)
    try:
        headers = [c.strip() for c in next(reader)]
    except (StopIteration, csv.Error):
        raise SourceError('El CSV no contiene encabezados válidos.') from None
    if len(headers) != len(set(headers)):
        raise SourceError('El CSV contiene encabezados duplicados.')
    if not any(h in headers for h in FIELDS['referencia']) or not any(h in headers for h in FIELDS['objeto']):
        raise SourceError('Faltan las columnas de referencia del contrato y/o descripción del proceso.')
    contracts = []
    try:
        for row_number, values in enumerate(reader, 2):
            if row_number > 200001:
                raise SourceError('La base supera 200.000 filas.')
            if not values or not any(v.strip() for v in values):
                continue
            if len(values) != len(headers):
                raise SourceError(f'La fila {row_number} tiene un número de columnas incompatible.')
            raw = dict(zip(headers, values))
            fields = {key: next((text(raw[c]) for c in cols if text(raw.get(c))), '')
                      for key, cols in FIELDS.items()}
            if re.fullmatch(r'\d+(?:[.,]\d+)?', fields['plazo']):
                fields['plazo'] += ' (unidad por confirmar)'
            if fields['referencia']:
                contracts.append(Contract(fields, row_number, raw))
    except csv.Error:
        raise SourceError('No fue posible leer el CSV. Revise su estructura.') from None
    if not contracts:
        raise SourceError('No se encontraron contratos con referencia en la base.')
    return Catalog(contracts, hashlib.sha256(data).hexdigest())


def search(catalog, query, mode):
    if not text(query):
        return []
    if mode == 'Número del contrato':
        q = reference_key(query)
        exact = [c for c in catalog.contracts if reference_key(c.fields['referencia']) == q
                 or reference_key(c.fields['id_contrato']) == q]
        if exact:
            return exact
        # Un número corto encuentra el segmento completo, nunca 12 dentro de 312.
        if re.fullmatch(r'\d+', q):
            return [c for c in catalog.contracts if any(t.isdigit() and int(t) == int(q)
                    for t in re.split(r'\D+', c.fields['referencia']) if t)]
        return [c for c in catalog.contracts if q in reference_key(c.fields['referencia'])]
    terms = re.findall(r'\w+', fold(query))
    return [c for c in catalog.contracts if all(t in fold(c.fields['objeto']) for t in terms)]
