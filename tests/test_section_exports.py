import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook
import exporters
import intelligent_requirement_analyzer as app


class SectionExportTests(unittest.TestCase):
    def test_all_formats_are_isolated_by_section(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(exporters, 'EXPORT_DIR', Path(directory)):
            for section, (title, columns, _) in exporters.SECTIONS.items():
                rows = [{key: f'{section}-{key}' for _, key in columns}]
                state = {'rows': {section: rows, 'other': [{'id': 'unrelated'}]}, 'meta': {'project': 'Test'}}
                excel_update = app.export_section(state, section, 'excel')
                workbook = load_workbook(excel_update['value'])
                self.assertEqual(workbook.sheetnames, [title])
                self.assertEqual(workbook.active.cell(2, 1).value, f'{section}-{columns[0][1]}')
                csv_update = app.export_section(state, section, 'csv')
                with open(csv_update['value'], encoding='utf-8-sig', newline='') as file:
                    records = list(csv.reader(file))
                self.assertEqual(len(records), 2)
                self.assertEqual(records[1][0], f'{section}-{columns[0][1]}')

    def test_empty_section_cannot_export(self):
        with patch.object(app.gr, 'Warning') as warn:
            update = app.export_section(app._empty_state(), 'stories', 'csv')
        self.assertFalse(update['visible'])
        self.assertIsNone(update['value'])
        warn.assert_called_once()
