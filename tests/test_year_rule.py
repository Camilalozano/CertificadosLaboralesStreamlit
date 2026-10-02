import io
import unittest
import zipfile
from unittest.mock import patch
from src.archives import zip_pdfs
from src.contracts import Contract, contract_year, parse_csv
from src.documents import list_documents, lookup_documents, ranked_sources, document_kind
from src.network import SourceError, DOCUMENT_DATASETS
from src.obligations import extract, Extraction
from src.workflow import prepare, audit
from tests.test_core import csv_fixture
from datetime import date


def make_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buffer.getvalue()


class YearRuleTests(unittest.TestCase):
    def test_contract_reference_precedes_later_start_date(self):
        c = Contract({'referencia': 'ATENEA-999-2025', 'inicio': '2026-01-01'}, 2,
                     {'año_inferido': '2026', 'fecha_de_firma (contratos_electronicos)': '2025-12-30'})
        self.assertEqual(contract_year(c), (2025, 'referencia del contrato'))
        c.fields['referencia'] = 'SIN-AÑO'
        self.assertEqual(contract_year(c)[0], 2025)
        c.raw = {}
        self.assertIsNone(contract_year(c)[0])

    def test_expected_document_changes_at_2026(self):
        rows = [{'nombre_archivo': name, 'extensi_n': 'pdf', 'id_documento': str(i)}
                for i, name in enumerate(['MINUTA CONTRATO.pdf', '2. ESTUDIOS-PREVIOS.pdf',
                                          'MINUTA CESIÓN.pdf', 'INFORME ESTUDIOS PREVIOS.pdf'])]
        for year, expected in [(2024, 'MINUTA CONTRATO.pdf'), (2025, 'MINUTA CONTRATO.pdf'),
                               (2026, '2. ESTUDIOS-PREVIOS.pdf'), (2027, '2. ESTUDIOS-PREVIOS.pdf')]:
            eligible = [r for score, r in ranked_sources(rows, 'ATENEA-999', year) if score >= 80]
            self.assertEqual([r['nombre_archivo'] for r in eligible], [expected])

    def test_zip_directory_does_not_classify_unrelated_pdf(self):
        data = make_zip({'Documentos Previos/CDP.pdf': b'%PDF-CDP',
                         'Documentos Previos/2. ESTUDIOS-PREVIOS.pdf': b'%PDF-EP',
                         'Documentos Previos/MINUTA.pdf': b'%PDF-MINUTA'})
        row = {'nombre_archivo': 'Documentos Previos.zip', 'extensi_n': 'zip'}
        for year, expected in [(2026, b'%PDF-EP'), (2024, b'%PDF-MINUTA')]:
            items = list(zip_pdfs(data, row, year))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0][0], expected)
            self.assertIn('_zip_sha256', items[0][1])
        self.assertIsNone(document_kind('Documentos Previos/CDP.pdf'))

    def test_zip_limits_and_invalid_data(self):
        for data in [b'not a zip', make_zip({f'{i}.txt': b'' for i in range(501)}),
                     make_zip({'EP.pdf': b'not a PDF'})]:
            with self.assertRaises(SourceError):
                list(zip_pdfs(data, {}, 2026))

    @patch('src.documents.api_rows')
    def test_process_documents_exclude_other_contracts(self, api):
        process = 'CO1.BDOS.123'
        api.return_value = [{'id_documento': '1', 'proceso': process},
                            {'id_documento': '2', 'proceso': process, 'n_mero_de_contrato': 'CO1.PCCNTR.100'},
                            {'id_documento': '3', 'proceso': process, 'n_mero_de_contrato': 'CO1.PCCNTR.200'}]
        rows = list_documents('CO1.PCCNTR.100', 'nbae-kzan', process)
        self.assertEqual([r['id_documento'] for r in rows], ['1', '2'])
        self.assertEqual(rows[0]['_asociacion'], 'proceso')
        self.assertEqual(api.call_args.kwargs['dataset'], 'nbae-kzan')
        api.return_value = [{'proceso': 'CO1.BDOS.999'}]
        with self.assertRaises(SourceError): list_documents('CO1.PCCNTR.100', process=process)

    @patch('src.documents.list_documents')
    def test_historical_and_process_lookup_deduplicates(self, listing):
        def answer(cid, dataset, process=None):
            if dataset != 'nbae-kzan': return []
            row = {'id_documento': '1', 'proceso': 'CO1.BDOS.123', 'n_mero_de_contrato': cid}
            return [row, {'id_documento': '2', 'proceso': 'CO1.BDOS.123'}] if process else [row]
        listing.side_effect = answer
        rows, warnings = lookup_documents('CO1.PCCNTR.100')
        self.assertEqual([r['id_documento'] for r in rows], ['1', '2'])
        self.assertFalse(warnings)
        self.assertEqual(listing.call_count, 2 * len(DOCUMENT_DATASETS))

    @patch('src.documents.list_documents', side_effect=SourceError('HTTP 503'))
    def test_source_failure_is_reported_as_incomplete(self, listing):
        rows, warnings = lookup_documents('CO1.PCCNTR.100')
        self.assertEqual(rows, [])
        self.assertTrue(all('incompleta' in w for w in warnings))

    @patch('src.workflow.extract_document')
    @patch('src.workflow.lookup_documents')
    def test_2026_never_automatically_falls_back_to_minuta(self, listing, extraction):
        c = parse_csv(csv_fixture()).contracts[1]
        listing.return_value = ([{'nombre_archivo': 'MINUTA.pdf', 'extensi_n': 'pdf'}], [])
        result = prepare(c)
        self.assertIsNone(result['extraction'])
        extraction.assert_not_called()
        self.assertTrue(any('estudios previos' in w for w in result['warnings']))
        c.fields['referencia'] = 'SIN-AÑO'
        with self.assertRaises(SourceError): prepare(c)

    @patch('src.obligations.pdf_pages')
    def test_study_section_stops_before_selection_and_penalties(self, pages):
        pages.return_value = ['OBLIGACIONES ESPECÍFICAS DEL CONTRATISTA\n1. Apoyar la gestión.\n2. Presentar informes.\n'
                              '3. MODALIDAD DE SELECCIÓN Y JUSTIFICACIÓN DE LA MISMA\nTexto ajeno.\n'
                              '3. GARANTÍAS\n4. MULTAS: Texto ajeno.']
        numbered = pages.return_value[0]
        for content in [numbered, numbered.replace('3. MODALIDAD', 'MODALIDAD')]:
            pages.return_value = [content]
            result = extract(b'fixture')
            self.assertEqual([o['texto'] for o in result.obligations], ['Apoyar la gestión.', 'Presentar informes.'])
            self.assertFalse(result.warnings)

    @patch('src.obligations.pdf_pages')
    def test_agency_obligations_are_not_contractor_obligations(self, pages):
        pages.return_value = ['OBLIGACIONES ESPECÍFICAS DE LA AGENCIA ATENEA: 1. Pagar. 2. Supervisar.']
        with self.assertRaises(SourceError): extract(b'fixture')

    @patch('src.obligations.pdf_pages')
    def test_page_numbers_and_contact_footer_do_not_enter_obligations(self, pages):
        pages.return_value = ['1\nOBLIGACIONES ESPECÍFICAS: 1. Apoyar la gestión.\n',
                              '2\nCarrera 10 No. 28\nPBX: (601) 6660006\nwww.agenciaatenea.gov.co\n'
                              'atencionalciudadano@agenciaatenea.gov.co\nInformación: Línea 195\n'
                              '2. Entregar informes. CLÁUSULA TERCERA: Otra materia.']
        result = extract(b'fixture')
        self.assertEqual([o['texto'] for o in result.obligations], ['Apoyar la gestión.', 'Entregar informes.'])
        self.assertEqual([o['pagina'] for o in result.obligations], [1, 2])

    @patch('src.obligations.pdf_pages')
    def test_clause_reference_inside_an_obligation_does_not_truncate(self, pages):
        pages.return_value = ['OBLIGACIONES ESPECÍFICAS: 1. Cumplir la cláusula forma de pago. '
                              '2. Entregar informes. CLÁUSULA TERCERA: Otra materia.']
        result = extract(b'fixture')
        self.assertEqual(result.obligations[0]['texto'], 'Cumplir la cláusula forma de pago.')
        self.assertEqual(len(result.obligations), 2)

    def test_trace_records_year_and_zip_member(self):
        c = parse_csv(csv_fixture()).contracts[1]
        result = audit(c, 'csvhash', c.fields, ['Texto'], [], 'EP.pdf', 'pdfhash', '', date.today(), '', '',
                       document={'_dataset': 'dmgg-8hin', '_archivo_zip': 'Carpeta 1.zip', '_miembro_zip': '1/EP.pdf'})
        self.assertEqual(result['regla_documental']['año_contrato'], 2026)
        self.assertEqual(result['regla_documental']['documento_esperado'], 'estudios previos')
        self.assertEqual(result['fuente_obligaciones']['miembro_zip'], '1/EP.pdf')


if __name__ == '__main__': unittest.main()
