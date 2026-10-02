"""Interfaz Streamlit de búsqueda, revisión y descarga de certificados ATENEA."""
import hashlib
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from src.contracts import parse_csv, search, text, contract_year
from src.documents import document_url, ranked_sources, source_label, expected_source, document_kind
from src.network import SourceError, download_oracle, allowed_url, DOCUMENT_HOST, DOCUMENT_DATASETS
from src.obligations import extract
from src.certificate import build_certificate, limpiar_nombre_archivo
from src.workflow import prepare, fingerprint, audit, extract_document


def setting(key, default=''):
    try:
        return str(st.secrets.get(key, os.environ.get(key, default)))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return os.environ.get(key, default)


@st.cache_data(ttl=3600, max_entries=4, show_spinner=False)
def oracle_catalog(par_url):
    return parse_csv(download_oracle(par_url))


@st.cache_data(ttl=3600, max_entries=4, show_spinner=False)
def uploaded_catalog(data):
    return parse_csv(data)


def reset_result():
    for key in ('results', 'catalog', 'selected_key', 'selected_rule', 'prepared', 'output', 'output_state', 'extraction_token'):
        st.session_state.pop(key, None)


def apply_extraction(prepared, pdf, name, year, url='', document=None):
    kind = document_kind(name)
    if kind and kind != expected_source(year):
        raise SourceError(f'Para el año {year}, cargue {source_label(year)}.')
    extraction = extract(pdf)
    return {**prepared, 'extraction': extraction, 'pdf': pdf,
            'document': document or {'nombre_archivo': name, 'url_descarga_documento': url}}


def main():
    st.set_page_config(page_title='Certificaciones contractuales · ATENEA', page_icon='📄', layout='wide')
    st.title('Certificaciones laborales y contractuales')
    st.caption('ATENEA · Busca el contrato, revisa las obligaciones y descarga el documento Word.')
    with st.sidebar:
        st.header('Fuente de información')
        st.caption('La consulta usa la base contractual de Oracle y los documentos actuales e históricos de SECOP II.')
        with st.expander('Configurar o actualizar la conexión'):
            par_url = st.text_input('Ruta PAR de Oracle', value=setting('ORACLE_PAR_URL'), type='password', key='par_url')
            upload = st.file_uploader('CSV alternativo (opcional)', type=['csv'], key='base_csv')
            if st.button('Actualizar base', key='refresh'):
                oracle_catalog.clear()
                reset_result()
                st.success('La próxima búsqueda cargará la base nuevamente.')
        with st.expander('Datos de expedición'):
            issued = st.date_input('Fecha del documento', value=datetime.now(ZoneInfo('America/Bogota')).date())
            signer = st.text_input('Nombre del firmante (opcional)', value=setting('FIRMANTE'))
            role = st.text_input('Cargo', value=setting('CARGO_FIRMANTE', 'Subgerencia de Gestión Administrativa'))
            logo = st.file_uploader('Logo institucional (opcional)', type=['png', 'jpg', 'jpeg'])
        st.caption('El Word queda como borrador para revisión y firma. No se agrega una firma digital.')
    st.subheader('1. Buscar contrato')
    mode = st.radio('Buscar por', ['Número del contrato', 'Objeto del contrato'], horizontal=True)
    query = st.text_input('Número u objeto del contrato', placeholder='Ejemplo: ATENEA-003-2025 o palabras del objeto')
    upload_data = upload.getvalue() if upload else None
    context = fingerprint([mode, query.strip(), hashlib.sha256(upload_data).hexdigest() if upload_data else par_url])
    if st.session_state.get('search_context') != context:
        reset_result()
        st.session_state['search_context'] = context
    if st.button('Buscar contrato', type='primary', key='search'):
        reset_result()
        if not query.strip():
            st.info('Ingresa el número del contrato o palabras de su objeto.')
            return
        if not upload_data and not par_url:
            st.info('Configura ORACLE_PAR_URL en los secretos de Streamlit o ingresa la ruta PAR en el panel lateral.')
            return
        try:
            with st.spinner('Consultando la base contractual…'):
                catalog = uploaded_catalog(upload_data) if upload_data else oracle_catalog(par_url)
                matches = search(catalog, query, mode)
            st.session_state['catalog'] = catalog
            st.session_state['results'] = matches
        except SourceError as e:
            st.error(str(e))
            return
    matches = st.session_state.get('results')
    if matches is None:
        return
    if not matches:
        st.info('No se encontraron coincidencias. Prueba con otra referencia o con menos palabras del objeto.')
        return
    if len(matches) > 200:
        st.info(f'Hay {len(matches)} coincidencias. Agrega palabras o el año para acotar a un máximo de 200.')
        return
    st.caption(f'{len(matches)} coincidencia(s). La selección usa el ID de contrato y la fila de la base.')
    by_key = {c.key: c for c in matches}
    selection = st.selectbox('Selecciona el contrato', list(by_key), index=0 if len(matches) == 1 else None,
        format_func=lambda k: f'{by_key[k].fields["referencia"]} · {by_key[k].fields["contratista"]} · {by_key[k].fields["id_contrato"]} · fila {by_key[k].row_number}',
        placeholder='Seleccionar una coincidencia', key='contract_select_' + context)
    if selection is None:
        return
    contract = by_key[selection]
    if st.session_state.get('selected_key') != selection:
        for key in ('prepared', 'output', 'output_state', 'extraction_token'):
            st.session_state.pop(key, None)
        st.session_state['selected_key'] = selection
    st.write(contract.fields['objeto'])
    st.subheader('Observaciones del contrato')
    observations = text(contract.raw.get('observaciones_inferido'))
    if observations:
        # Conservar el texto de la fuente sin interpretar enlaces ni formato Markdown.
        st.warning(re.sub(r'([\\`*_{}\[\]()#+\-.!|<>~$])', r'\\\1', observations))
    else:
        st.info('Sin observaciones reportadas en la base para este contrato.')
    st.caption('Fuente: observaciones_inferido de la base SECOP en Oracle.')
    st.subheader('Modificación reportada')
    modification_columns = [
        ('Tipo de modificación', 'tipo_modificacion'),
        ('Identificador', 'identificador_modificacion (modificaciones)'),
        ('Estado', 'estado_modificacion (modificaciones)'),
        ('Fecha de aprobación', 'fecha_de_aprobacion (modificaciones)'),
    ]
    st.dataframe([{label: text(contract.raw.get(column)) or 'Sin información'
                   for label, column in modification_columns}], hide_index=True)
    st.caption('Datos del registro seleccionado en la base SECOP. Esta tabla no representa el historial completo de modificaciones.')
    if allowed_url(contract.fields['url'], DOCUMENT_HOST):
        st.link_button('Consultar proceso en SECOP II', contract.fields['url'])
    year, year_origin = contract_year(contract)
    if year is None:
        year = st.number_input('Año del contrato (confirma para elegir el documento)', min_value=2000,
                               max_value=2100, value=None, step=1, key='year_' + selection)
        year_origin = 'confirmado por el usuario'
    rule_context = (selection, year)
    if st.session_state.get('selected_rule') != rule_context:
        for key in ('prepared', 'output', 'output_state', 'extraction_token'):
            st.session_state.pop(key, None)
        st.session_state['selected_rule'] = rule_context
    if year is None:
        st.info('Indica el año del contrato para continuar.')
        return
    st.info(f'Contrato {year}: las obligaciones se extraen de {source_label(year)}. Año tomado de {year_origin}.')
    if st.button('Obtener obligaciones de SECOP', type='primary', key='prepare'):
        st.session_state.pop('output', None)
        st.session_state.pop('output_state', None)
        try:
            with st.spinner(f'Consultando archivos actuales e históricos y buscando {source_label(year)}…'):
                st.session_state['prepared'] = prepare(contract, year=year)
        except SourceError as e:
            st.session_state['prepared'] = {'documents': [], 'warnings': [str(e)], 'extraction': None, 'pdf': b'', 'document': None}
    prepared = st.session_state.get('prepared')
    if prepared is None:
        return
    st.subheader('2. Revisar datos y obligaciones')
    for warning in prepared['warnings']:
        st.warning(warning)
    with st.expander(f'Cambiar el documento o cargar {source_label(year)}'):
        sources = [row for score, row in ranked_sources(prepared['documents'], contract.fields['referencia'], year) if score >= 80]
        if sources:
            row = st.selectbox('Documentos PDF o ZIP según el año del contrato', sources,
                format_func=lambda r: f'{r.get("nombre_archivo")} · ID {r.get("id_documento")} · {r.get("fecha_carga", "")[:10]}', key='pdf_select_' + selection)
            if st.button('Extraer de este documento', key='extract_selected'):
                try:
                    with st.spinner('Leyendo el documento…'):
                        prepared = {**prepared, **extract_document(row, year)}
                    st.session_state['prepared'] = prepared
                except SourceError as e:
                    st.error(str(e))
        manual_pdf = st.file_uploader(f'PDF alternativo: {source_label(year)}', type=['pdf'], key='manual_' + selection)
        if st.button('Extraer del PDF cargado', disabled=manual_pdf is None, key='extract_uploaded'):
            try:
                prepared = apply_extraction(prepared, manual_pdf.getvalue(), manual_pdf.name, year)
                st.session_state['prepared'] = prepared
            except SourceError as e:
                st.error(str(e))
        st.caption(f'También puedes transcribir las obligaciones de {source_label(year)} en el campo de revisión. Quedarán registradas como edición manual.')
    extraction = prepared['extraction']
    document = prepared['document'] or {}
    source_name = document.get('nombre_archivo', 'Transcripción manual')
    source_url = document_url(document)
    pdf_sha = hashlib.sha256(prepared['pdf']).hexdigest() if prepared['pdf'] else ''
    token = fingerprint([selection, year, st.session_state['catalog'].sha256, pdf_sha, source_name])
    if st.session_state.get('extraction_token') != token:
        st.session_state.pop('output', None)
        st.session_state['extraction_token'] = token
    if extraction:
        st.success(f'{len(extraction.obligations)} obligaciones localizadas en {source_name}.')
        if document.get('_archivo_zip'):
            st.caption(f'PDF extraído de: {document["_archivo_zip"]}.')
        if document.get('_dataset'):
            st.caption(f'Fuente SECOP: {DOCUMENT_DATASETS.get(document["_dataset"], document["_dataset"])} · vinculado al {document.get("_asociacion", "contrato")}.')
        for warning in extraction.warnings:
            st.warning(warning)
        with st.expander('Ver evidencia y páginas de origen'):
            st.dataframe(extraction.obligations, hide_index=True)
            st.download_button('Descargar PDF consultado', prepared['pdf'], limpiar_nombre_archivo(source_name), 'application/pdf')
            st.text_area('Texto de la sección', extraction.section, height=250, disabled=True, key='section_' + token)
    fields = dict(contract.fields)
    labels = [('referencia', 'Número del contrato'), ('contratista', 'Contratista'),
              ('tipo_documento', 'Tipo de documento'), ('documento', 'Identificación'),
              ('valor', 'Valor total reportado'), ('estado', 'Estado del contrato'),
              ('inicio', 'Fecha de inicio'), ('fin', 'Fecha de finalización'), ('plazo', 'Plazo contractual reportado')]
    cols = st.columns(2)
    for index, (key, label) in enumerate(labels):
        fields[key] = cols[index % 2].text_input(label, fields.get(key, ''), key=token + '_' + key)
    fields['objeto'] = st.text_area('Objeto contractual', fields['objeto'], height=120, key=token + '_objeto')
    original_items = extraction.obligations if extraction else []
    original_text = '\n'.join(o['texto'] for o in original_items)
    raw = st.text_area('Obligaciones específicas (una por línea)', original_text, height=300, key=token + '_obligaciones')
    obligations = [re.sub(r'^\d+[.)]\s+', '', line.strip()) for line in raw.splitlines() if line.strip()]
    manual_source = st.text_input('Fuente de las obligaciones transcritas', value='', key=token + '_manual_source') if not extraction else ''
    if not extraction and manual_source.strip():
        source_name = manual_source.strip()
    logo_bytes = logo.getvalue() if logo else None
    output_state = fingerprint([fields, obligations, issued, signer, role, source_name, source_url, pdf_sha, year,
                                hashlib.sha256(logo_bytes).hexdigest() if logo_bytes else ''])
    if st.session_state.get('output_state') != output_state:
        st.session_state.pop('output', None)
    st.subheader('3. Generar y descargar')
    if st.button('Generar certificado Word', type='primary', key='generate'):
        try:
            content = build_certificate(fields, obligations, issued, signer, role, source_name, source_url, logo_bytes)
            trace = audit(contract, st.session_state['catalog'].sha256, fields, obligations, original_items,
                          source_name, pdf_sha, source_url, issued, signer, role, year=year, document=document)
            st.session_state['output'] = {'docx': content, 'audit': json.dumps(trace, ensure_ascii=False, indent=2).encode('utf-8')}
            st.session_state['output_state'] = output_state
        except SourceError as e:
            st.error(str(e))
    output = st.session_state.get('output')
    if output:
        st.success('Certificado preparado. Puedes descargar el Word y su trazabilidad.')
        filename = 'Certificado_' + limpiar_nombre_archivo(fields['referencia'])
        st.download_button('Descargar certificado Word', output['docx'], filename + '.docx',
                           'application/vnd.openxmlformats-officedocument.wordprocessingml.document', type='primary')
        st.download_button('Descargar trazabilidad', output['audit'], filename + '_trazabilidad.json', 'application/json')


if __name__ == '__main__':
    main()
