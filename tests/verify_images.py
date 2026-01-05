import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf_organizer import PDFOrganizerApp
import tkinter as tk

class TestImagePipeline(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = PDFOrganizerApp(self.root)
        self.test_dir = "test_images"
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Create a dummy image
        self.dummy_image_path = os.path.join(self.test_dir, "test.jpg")
        img = Image.new('RGB', (100, 100), color = 'white')
        img.save(self.dummy_image_path)

    def tearDown(self):
        self.root.destroy()
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    @patch('pdf_organizer.pytesseract.image_to_string')
    def test_image_extraction(self, mock_ocr):
        # Setup mock return value
        mock_ocr.return_value = """
        Diploma
        Certifica a:
        ANNA SMITH
        Febrero 2024
        """
        
        # Run extraction
        info = self.app.extract_info(self.dummy_image_path)
        
        # Verify OCR was called
        mock_ocr.assert_called()
        
        # Verify info extraction
        self.assertIsNotNone(info)
        print(f"Image Test Result: {info}")
        self.assertEqual(info['name'], "Anna Smith")
        self.assertEqual(info['year'], "2024")

if __name__ == '__main__':
    unittest.main()
