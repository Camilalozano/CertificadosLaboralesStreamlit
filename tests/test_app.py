import copy
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from src.obligations import Extraction
from tests.test_core import csv_fixture


PREPARED = {'documents': [], 'warnings': [], 'pdf': b'fixture-pdf',
            'document': {'nombre_archivo': 'minuta_prueba.pdf'},
            'extraction': Extraction([{'numero': 1, 'texto': 'Apoyar el análisis.', 'pagina': 2}],
                                     '1. Apoyar el análisis.', ['Texto'], [])}


class AppTests(unittest.TestCase):
    def start(self):
        self.download = patch('src.network.download_oracle', return_value=csv_fixture())
        self.preparation = patch('src.workflow.prepare', side_effect=lambda c: copy.deepcopy(PREPARED))
        self.download.start(); self.preparation.start()
        self.addCleanup(self.download.stop); self.addCleanup(self.preparation.stop)
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20)
        at.secrets['ORACLE_PAR_URL'] = 'https://objectstorage.us-ashburn-1.oraclecloud.com/p/test/n/test/b/test/o/test.csv'
        at.run()
        self.assertFalse(at.exception)
        return at

    def find(self, at, query='ATENEA-003-2025'):
        next(w for w in at.text_input if w.label == 'Número u objeto del contrato').set_value(query)
        at.button(key='search').click().run()
        self.assertFalse(at.exception)
        return at

    def test_search_prepare_generate_download_and_edit_invalidates_output(self):
        at = self.find(self.start())
        at.button(key='prepare').click().run()
        self.assertFalse(at.exception)
        at.button(key='generate').click().run()
        self.assertFalse(at.exception)
        self.assertIn('output', at.session_state)
        self.assertEqual(len(at.get('download_button')), 3)
        next(w for w in at.text_area if w.label.startswith('Obligaciones específicas')).set_value('Obligación corregida.').run()
        self.assertNotIn('output', at.session_state)

    def test_ambiguous_number_requires_selection(self):
        at = self.find(self.start(), '003')
        self.assertEqual(next(w for w in at.selectbox if w.label == 'Selecciona el contrato').value, None)
        self.assertFalse(any(w.key == 'prepare' for w in at.button))

    def test_object_query_and_context_change(self):
        at = self.start()
        next(w for w in at.radio if w.label == 'Buscar por').set_value('Objeto del contrato')
        self.find(at, 'analisis informacion')
        self.assertEqual(len(at.session_state['results']), 2)
        next(w for w in at.text_input if w.label == 'Número u objeto del contrato').set_value('otra consulta').run()
        self.assertNotIn('results', at.session_state)

    def test_no_secret_gives_actionable_message(self):
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20)
        at.secrets['ORACLE_PAR_URL'] = ''
        at.run()
        self.find(at)
        self.assertTrue(any('Configura ORACLE_PAR_URL' in x.value for x in at.info))
        self.assertFalse(at.exception)


if __name__ == '__main__': unittest.main()
