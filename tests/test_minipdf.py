import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "pdf", "spike"))

from minipdf import PDF, esc, num  # noqa: E402


class TestMiniPDF(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(esc("a(b)c\\d"), "a\\(b\\)c\\\\d")

    def test_num(self):
        self.assertEqual(num(0), "0")
        self.assertEqual(num(0.0), "0")
        self.assertEqual(num(1.5), "1.5")
        self.assertEqual(num(8.3333), "8.333")

    def test_build_roundtrip(self):
        pdf = PDF()
        page_ref = pdf.reserve()
        pages_ref = pdf.reserve()
        content = pdf.add_stream(b"0 0 0 rg 0 0 10 10 re f", compress=True)
        pdf.set(page_ref,
                (f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 10 10] "
                 f"/Contents {content} 0 R >>").encode())
        pdf.set(pages_ref, f"<< /Type /Pages /Kids [{page_ref} 0 R] /Count 1 >>".encode())
        cat = pdf.add(f"<< /Type /Catalog /Pages {pages_ref} 0 R >>".encode())
        data = pdf.build(cat)
        self.assertTrue(data.startswith(b"%PDF-1.7"))
        self.assertIn(b"/Type /Catalog", data)
        self.assertIn(b"startxref", data)
        self.assertTrue(data.endswith(b"%%EOF\n"))

    def test_unset_object_raises(self):
        pdf = PDF()
        pdf.reserve()
        cat = pdf.add(b"<< /Type /Catalog >>")
        with self.assertRaises(ValueError):
            pdf.build(cat)


if __name__ == "__main__":
    unittest.main()
