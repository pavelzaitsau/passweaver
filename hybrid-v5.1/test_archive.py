from pathlib import Path
import tempfile
import unittest
import zipfile

from reporting import archive


class ArchiveTests(unittest.TestCase):
    def test_standalone_archive_includes_review_and_repairs_link(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'report'
            output.mkdir()
            final = output / 'FINAL-REVIEW.md'
            final.write_text('# Review\n\n[Journal](../../../review/REVIEW.md)\n')
            review = root / 'source-review.md'
            review.write_text('# Journal\n\nAll findings closed.\n')
            target = root / 'report.zip'
            archive.create(output, target, [final], review)
            with zipfile.ZipFile(target) as saved:
                self.assertIn('review/REVIEW.md', saved.namelist())
                self.assertIn('(review/REVIEW.md)', saved.read('FINAL-REVIEW.md').decode())

    def test_missing_local_link_rejects_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            final = root / 'FINAL-REVIEW.md'
            final.write_text('# Review\n\n[Missing](absent.md)\n')
            review = root / 'source-review.md'
            review.write_text('# Journal\n')
            with self.assertRaises(ValueError):
                archive.create(root, root / 'report.zip', [final], review)
            self.assertFalse((root / 'report.zip').exists())


if __name__ == '__main__':
    unittest.main()
