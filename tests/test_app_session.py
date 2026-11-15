import unittest
from types import SimpleNamespace
from unittest.mock import patch

import intelligent_requirement_analyzer as app


class SessionTests(unittest.TestCase):
    def test_initial_state_is_empty(self):
        self.assertEqual(app.initial_state, app._empty_state())
        self.assertNotIn(app.MODEL_NAME, app.header_html)

    def test_missing_file_gives_clear_error_and_keeps_session(self):
        state = app._build_state({'project': 'Previous'}, {'stories': '- **US-01** As a user, I want access, so that I can work'})
        result = app.analyze_document(None, '', [], state)
        self.assertIn('Please upload a file', result[0])
        self.assertEqual(result[10], state)

    def test_clear_resets_state_inputs_downloads_and_filters(self):
        result = app.clear_session()
        self.assertEqual(result[10], app._empty_state())
        self.assertEqual(result[11:13], (None, ''))
        self.assertTrue(all(not item['visible'] and item['value'] is None for item in result[13:16]))
        self.assertEqual(result[16:], ('', '', ''))

    def test_new_analysis_generates_only_selected_section(self):
        page = SimpleNamespace(page_content='Requirement text. ' * 10)
        fake_llm = SimpleNamespace(invoke=lambda prompt: SimpleNamespace(content='- **US-01** As a user, I want access, so that I can work'))
        with patch.object(app, 'llm', fake_llm), patch.object(app, 'PyPDFLoader') as loader:
            loader.return_value.load.return_value = [page]
            result = app.analyze_and_reset_downloads(SimpleNamespace(name='test.pdf'), 'Project', ['stories'], app._empty_state())
        self.assertIn('Analysis complete', result[0])
        self.assertEqual(len(result[10]['rows']['stories']), 1)
        self.assertEqual(result[10]['rows']['acceptance'], [])
        self.assertTrue(all(not item['visible'] and item['value'] is None for item in result[11:14]))
        self.assertEqual(result[14:], ('', '', ''))


if __name__ == '__main__':
    unittest.main()
