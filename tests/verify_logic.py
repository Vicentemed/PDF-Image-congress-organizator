import sys
import os
import fitz  # PyMuPDF
import unittest
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf_organizer import PDFOrganizerApp
import tkinter as tk

class MockApp:
    def log(self, msg):
        print(f"[LOG] {msg}")

    def find_name(self, text):
        return PDFOrganizerApp.find_name(self, text)
    
    def find_date(self, text):
        return PDFOrganizerApp.find_date(self, text)

class TestPDFExtraction(unittest.TestCase):
    def setUp(self):
        self.app = MockApp()
        self.test_dir = "test_pdfs"
        os.makedirs(self.test_dir, exist_ok=True)

    def create_pdf(self, filename, text):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), text, fontsize=12)
        path = os.path.join(self.test_dir, filename)
        doc.save(path)
        doc.close()
        return path

    def test_extraction_1(self):
        # Case 1: Standard Certificate
        text = """
        UNIVERSIDAD AUTONOMA
        
        Certifica a:
        Juan Perez
        
        Por su asistencia al curso.
        Aguascalientes, Ags, a 15 de Enero de 2024.
        """
        path = self.create_pdf("sample1.pdf", text)
        
        name = self.app.find_name(text)
        date = self.app.find_date(text)
        
        print(f"Sample 1 -> Name: {name}, Date: {date}")
        self.assertEqual(name, "Juan Perez")
        self.assertEqual(date, "2024")

    def test_extraction_2(self):
        # Case 2: Different wording
        text = """
        Diploma
        
        Se otorga el presente reconocimiento a
        MARIA LOPEZ GARCIA
        
        Por su brillante participacion.
        Marzo 2023
        """
        path = self.create_pdf("sample2.pdf", text)
        
        name = self.app.find_name(text)
        date = self.app.find_date(text)
        
        print(f"Sample 2 -> Name: {name}, Date: {date}")
        self.assertEqual(name, "Maria Lopez Garcia")
        self.assertEqual(date, "2023")

    def test_extraction_english(self):
        text = """
        Reviewer Certificate
        
        This certificate is awarded to
        JOHN DOE
        
        For reviewing 3 papers.
        Date: 12th January 2024
        """
        name = self.app.find_name(text)
        print(f"Sample English -> Name: {name}")
        self.assertEqual(name, "John Doe")

    def tearDown(self):
        # Clean up
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

if __name__ == '__main__':
    unittest.main()
