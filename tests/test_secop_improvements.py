import io
import unittest
import zipfile
from unittest.mock import patch
from src.contracts import parse_csv
from src.documents import resolve_process, lookup_documents
from src.network import SourceError, DOCUMENT_DATASETS
from src.obligations import extract
from src.secop_archive import build_archive
from tests.test_core import csv_fixture


class SecopImprovements(unittest.TestCase):
    def test_2025_document_history_is_included(self):
        self.assertEqual(DOCUMENT_DATASETS['h4m3-b4e2'], 'Histórico 2025')

    @patch('src.documents.api_rows')
    def test_resolve_process_by_exact_contract(self, api):
        contract = parse_csv(csv_fixture()).contracts[0]
        api.return_value = [{'id_contrato': 'CO1.PCCNTR.100', 'proceso_de_compra': 'CO1.BDOS.42'}]
        self.assertEqual(resolve_process(contract), 'CO1.BDOS.42')
        api.return_value[0]['id_contrato'] = 'CO1.PCCNTR.999'
        with self.assertRaises(SourceError):
            resolve_process(contract)

    @patch('src.documents.list_documents')
    def test_process_documents_found_without_contract_documents(self, listing):
        listing.side_effect = lambda cid, ds, process=None: ([{'id_documento': 'ep', 'proceso': process}]
                                                           if process and ds == 'dmgg-8hin' else [])
        rows, warnings = lookup_documents('CO1.PCCNTR.100', process='CO1.BDOS.42')
        self.assertEqual(len(rows), 1)
        self.assertFalse(warnings)

    @patch('src.obligations.pdf_pages')
    def test_2026_intro_mentions_general_obligations_without_ending_section(self, pages):
        pages.return_value = ['OBLIGACIONES ESPECÍFICAS DEL CONTRATISTA\nAdemás de las obligaciones generales, cumple las siguientes:\n1. Apoyar.\n2. Entregar.\n3. MODALIDAD DE SELECCIÓN\nTexto ajeno.']
        self.assertEqual(len(extract(b'x').obligations), 2)

    @patch('src.obligations.pdf_pages')
    def test_hierarchical_numbering_lowercase_and_general_boundary(self, pages):
        pages.return_value = ['OBLIGACIONES ESPECÍFICAS A CARGO DEL CONTRATISTA\n'
                              '2.1 apoyar la gestión.\n2.2 entregar informes.\n'
                              'OBLIGACIONES GENERALES: 1. Texto ajeno.']
        self.assertEqual([i['texto'] for i in extract(b'x').obligations],
                         ['apoyar la gestión.', 'entregar informes.'])

    @patch('src.secop_archive.read_url')
    def test_archive_preserves_files_and_records_failures(self, read):
        read.side_effect = [b'%PDF-test', SourceError('HTTP 403')]
        rows = [{'nombre_archivo': '../soporte.pdf', 'url_descarga_documento':
                 f'https://community.secop.gov.co/Public/Archive/RetrieveFile/Index?id={i}'} for i in range(2)]
        name, data, inventory = build_archive(rows, 'ATENEA-1-2026')
        self.assertEqual(inventory[0]['estado'], 'Descargado')
        self.assertIn('HTTP 403', inventory[1]['estado'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            self.assertTrue(all('/' not in n for n in archive.namelist()))
            self.assertIn('inventario_documentos_secop.csv', archive.namelist())
