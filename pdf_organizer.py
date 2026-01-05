import os
import sys
import shutil
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
try:
    import fitz  # PyMuPDF
    from PIL import Image
    import pytesseract
    from pdf2image import convert_from_path
except ImportError as e:
    import tkinter.messagebox
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    tkinter.messagebox.showerror(
        "Error de Dependencias",
        f"Falta una librería necesaria: {e.name}\n\n"
        "Por favor ejecute el siguiente comando en su terminal para instalar todo:\n"
        "pip install -r requirements.txt"
    )
    sys.exit(1)

# --- Configuration ---
# You might need to set the tesseract path explicitly if it's not in PATH
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class PDFOrganizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Organizador de Constancias PDF")
        self.root.geometry("600x450")
        
        # Styles
        style = ttk.Style()
        style.theme_use('clam')
        
        # Variables
        self.source_dir = tk.StringVar()
        if os.path.exists("Docs"):
            self.source_dir.set(os.path.abspath("Docs"))

        self.dest_dir = tk.StringVar()
        default_dest = "Docs organizados"
        if os.path.exists(default_dest):
            self.dest_dir.set(os.path.abspath(default_dest))
        elif os.path.exists("Docs"):
            # If source exists but dest doesn't, suggest 'Docs organizados' sibling
            self.dest_dir.set(os.path.abspath(default_dest))

        self.status_var = tk.StringVar(value="Listo")
        self.files_processed = 0
        self.errors = 0
        
        self.create_widgets()
        
        # Check dependencies after UI load so we can show messageboxes
        self.root.after(100, self.check_dependencies)

    def create_widgets(self):
        # Header
        header_frame = ttk.Frame(self.root, padding="10")
        header_frame.pack(fill=tk.X)
        ttk.Label(header_frame, text="Organizador de Documentos PDF", font=("Helvetica", 16, "bold")).pack()
        ttk.Label(header_frame, text="Extrae Nombres y Fechas para clasificar archivos autom\u00e1ticamente.").pack()

        # Input Area
        input_frame = ttk.LabelFrame(self.root, text="Configuraci\u00f3n", padding="10")
        input_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Source Directory
        ttk.Label(input_frame, text="Carpeta Origen:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.source_dir, width=50).grid(row=0, column=1, padx=5)
        ttk.Button(input_frame, text="Buscar...", command=self.browse_source).grid(row=0, column=2)

        # Destination Directory
        ttk.Label(input_frame, text="Carpeta Destino:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(input_frame, textvariable=self.dest_dir, width=50).grid(row=1, column=1, padx=5)
        ttk.Button(input_frame, text="Buscar...", command=self.browse_dest).grid(row=1, column=2)

        # Actions
        action_frame = ttk.Frame(self.root, padding="10")
        action_frame.pack(fill=tk.X, padx=10)
        
        self.start_btn = ttk.Button(action_frame, text="Iniciar Organizaci\u00f3n", command=self.start_processing)
        self.start_btn.pack(side=tk.RIGHT)

        # Log/Status Area
        log_frame = ttk.LabelFrame(self.root, text="Estado", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.log_text = tk.Text(log_frame, height=10, state='disabled')
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Status Bar
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def browse_source(self):
        directory = filedialog.askdirectory()
        if directory:
            self.source_dir.set(directory)

    def browse_dest(self):
        directory = filedialog.askdirectory()
        if directory:
            self.dest_dir.set(directory)

    def log(self, message):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')
        self.root.update_idletasks()

    def start_processing(self):
        source = self.source_dir.get()
        dest = self.dest_dir.get()
        
        if not source or not os.path.isdir(source):
            messagebox.showerror("Error", "Seleccione una carpeta de origen v\u00e1lida.")
            return
        if not dest:
            messagebox.showerror("Error", "Seleccione una carpeta de destino.")
            return

        self.start_btn.config(state='disabled')
        self.log("Iniciando proceso...")
        self.files_processed = 0
        self.errors = 0
        
        # Start processing in a loop (for simplicity, running on main thread for now, 
        # normally would thread this but let's keep it simple as requested)
        self.process_files(source, dest)
        
        self.log(f"--- Proceso Finalizado ---")
        self.log(f"Procesados: {self.files_processed}")
        self.log(f"Errores/No identificados: {self.errors}")
        messagebox.showinfo("Completado", f"Proceso finalizado.\nArchivos: {self.files_processed}\nErrores: {self.errors}")
        self.start_btn.config(state='normal')

    def process_files(self, source, dest):
        valid_extensions = ('.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff')
        
        for filename in os.listdir(source):
            if filename.lower().endswith(valid_extensions):
                filepath = os.path.join(source, filename)
                self.log(f"Analizando: {filename}...")
                
                try:
                    info = self.extract_info(filepath)
                    if info:
                        year = info.get('year', 'Desconocido')
                        name = info.get('name', 'Desconocido')
                        self.move_file(filepath, dest, year, name)
                        self.files_processed += 1
                    else:
                        self.log(f"  [!] No se pudo extraer informaci\u00f3n de {filename}")
                        self.errors += 1
                        
                except Exception as e:
                    self.log(f"  [X] Error procesando {filename}: {e}")
                    self.errors += 1

    def move_file(self, filepath, dest_root, year, name):
        # Sanitize directory name
        safe_name = "".join([c for c in name if c.isalpha() or c in (' ', '-', '_')]).strip()
        if not safe_name:
            safe_name = "SinNombre"
            
        target_dir = os.path.join(dest_root, str(year), safe_name)
        os.makedirs(target_dir, exist_ok=True)
        
        filename = os.path.basename(filepath)
        target_path = os.path.join(target_dir, filename)
        
        # Avoid overwriting
        counter = 1
        base, ext = os.path.splitext(filename)
        while os.path.exists(target_path):
            target_path = os.path.join(target_dir, f"{base}_{counter}{ext}")
            counter += 1
            
        shutil.copy2(filepath, target_path)
        self.log(f"  -> Copiado a: {year}/{safe_name}/")

    def extract_info(self, file_path):
        """
        Extracts Name and Date/Year from PDF or Image.
        Returns dict: {'name': str, 'year': str} or None if failed.
        """
        text = ""
        ext = os.path.splitext(file_path)[1].lower()
        
        # A. Handle PDF
        if ext == '.pdf':
            # 1. Try PyMuPDF (Text based)
            try:
                doc = fitz.open(file_path)
                for page in doc:
                    text += page.get_text()
                doc.close()
            except Exception as e:
                self.log(f"  Error leyendo PDF: {e}")
                return None

            # 2. If Text is empty, try OCR (Image based)
            if not text or len(text.strip()) < 50:
                self.log("  Texto insuficiente en PDF, intentando OCR...")
                try:
                    images = convert_from_path(file_path, first_page=1, last_page=1)
                    if images:
                        try:
                            text = pytesseract.image_to_string(images[0], lang='spa')
                        except pytesseract.TesseractError as te:
                            if "Failed loading language 'spa'" in str(te):
                                self.log("  [!] Error: Pack de idioma Español ('spa') no instalado en Tesseract.")
                                self.log("      Intentando con 'eng' (Inglés)...")
                                text = pytesseract.image_to_string(images[0], lang='eng')
                            else:
                                raise te
                except Exception as e:
                    if "poppler" in str(e).lower() or "page count" in str(e).lower():
                        self.log("  [X] Error Crítico: Poppler no está instalado o en el PATH.")
                        self.log("      Se requiere Poppler para procesar PDFs escaneados.")
                    else:
                        self.log(f"  Fallo en OCR de PDF: {e}")

        # B. Handle Images
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.tiff'):
            self.log("  Imagen detectada, ejecutando OCR...")
            try:
                with Image.open(file_path) as image:
                    try:
                        text = pytesseract.image_to_string(image, lang='spa')
                    except pytesseract.TesseractError as te:
                        if "Failed loading language 'spa'" in str(te):
                            self.log("  [!] Error: Idioma Español faltante en Tesseract. Usando Inglés...")
                            text = pytesseract.image_to_string(image, lang='eng')
                        else:
                            raise te
            except Exception as e:
                self.log(f"  Fallo al leer imagen: {e}")
                return None
                
        if not text:
            return None
            
        # Clean text
        text = text.replace('\n', ' ').strip()
        
        # Calling extraction logic
        name = self.find_name(text)
        year = self.find_date(text)
        
        return {'name': name, 'year': year}

    def find_date(self, text):
        # Normalizar texto para facilitar búsqueda
        text_lower = text.lower()
        
        # 1. Busqueda explícita de "de [Mes] de [Año]"
        months = r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
        
        # Pattern: 12 de Enero de 2024 / 12 de Enero del 2024
        date_pattern = re.search(f"\\b\\d{{1,2}}\\s+de\\s+{months}\\s+de(l)?\\s+(20[0-3][0-9])\\b", text_lower)
        if date_pattern:
            return date_pattern.group(3) # Group 3 is the year
            
        # 2. Busqueda de "Mes de [Año]" o "Mes [Año]" (Ej: Enero 2024)
        month_year_pattern = re.search(f"{months}\\s+(?:de(l)?\\s+)?(20[0-3][0-9])\\b", text_lower)
        if month_year_pattern:
            return month_year_pattern.group(3)

        # 3. Fallback: buscar solo el año (4 dígitos 2000-2039)
        years = re.findall(r'\b(20[0-3][0-9])\b', text)
        if years:
            # Retornar el año mas frecuente o el ultimo mencionado
            return years[-1]
            
        return "SinFecha"

    def find_name(self, text):
        # Limpiar texto de espacios multiples y caracteres extraños
        clean_text = re.sub(r'\s+', ' ', text)
        
    def find_name(self, text):
        # Limpiar texto de espacios multiples y caracteres extraños
        clean_text = re.sub(r'\s+', ' ', text)
        
        # Palabras clave que preceden al nombre (Spanish + English)
        keywords = [
            "otorga a", "otorga el presente", "certifica a", "certifica que", 
            "reconocimiento a", "presente a", "favor de", "constancia a",
            "presente diploma a", "se hace constar que", "certificamos a",
            "certifies that", "presented to", "awarded to", "reviewer certificate",
            "thank you", "recognition of"
        ]
        
        # Palabras que marcan el FIN del nombre (Stopwords)
        stop_words = {
            "por", "en", "con", "el", "la", "los", "las", "se", "ha", "haber",
            "asistencia", "participación", "participacion", "curso", "taller",
            "fecha", "dado", "expide", "aguascalientes", "enero", "febrero",
            "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
            "octubre", "noviembre", "diciembre",
            "for", "of", "and", "in", "to", "date", "given"
        }
        
        for kw in keywords:
            # Buscar la keyword case-insensitive
            match = re.search(f"{kw}\\W+", clean_text, re.IGNORECASE)
            if match:
                # Obtener el texto DESPUES de la keyword
                rest_of_text = clean_text[match.end():]
                
                # Tokenizar palabras
                words = rest_of_text.split()
                candidate_parts = []
                
                for word in words:
                    # Limpiar puntuación del final de la palabra
                    word_clean = word.rstrip(',.;:')
                    
                    if not word_clean:
                        continue
                        
                    # Verificar si es una stopword
                    if word_clean.lower() in stop_words:
                        break
                        
                    # Heurística: Si la palabra empieza con mayúscula o es todo mayús
                    # (Permitimos conectores de nombres como 'de', 'del' si ya tenemos algo)
                    if word_clean[0].isupper() or word_clean.lower() in ('de', 'del', 'y', 'la', 'los'):
                        candidate_parts.append(word_clean)
                    else:
                        # Si encontramos una palabra lowercase que no es conector comun, probablemente terminamos
                        break
                        
                    # Limite de longitud maxima del nombre
                    if len(candidate_parts) > 6:
                        break
                
                # Validar candidato
                if len(candidate_parts) >= 2:
                    # Checar que no sean puros conectores
                    real_names = [p for p in candidate_parts if p.lower() not in ('de', 'del', 'y')]
                    if len(real_names) >= 1:
                        return " ".join(candidate_parts).title()
        
        return "Desconocido"

    def process_files(self, source, dest):
        valid_extensions = ('.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff')
        
        for filename in os.listdir(source):
            if filename.lower().endswith(valid_extensions):
                filepath = os.path.join(source, filename)
                self.log(f"Analizando: {filename}...")
                
                try:
                    info = self.extract_info(filepath)
                    if info:
                        year = info.get('year', 'Desconocido')
                        name = info.get('name', 'Desconocido')
                        
                        # Fallback: Si el nombre es Desconocido, intentar extraerlo del nombre del archivo
                        if name == "Desconocido":
                            # Heuristica simple: Si el archivo parece tener un nombre propio
                            # Ej: "Vicente Esparza Villalpando.pdf" -> "Vicente Esparza Villalpando"
                            # Ignorar numeros y palabras comunes
                            clean_filename = os.path.splitext(filename)[0]
                            clean_filename = re.sub(r'[\d_()]+', ' ', clean_filename).strip()
                            if len(clean_filename.split()) >= 2:
                                name = clean_filename.title()
                                self.log(f"  [i] Nombre extraído del archivo: {name}")

                        self.move_file(filepath, dest, year, name)
                        self.files_processed += 1
                    else:
                        self.log(f"  [!] No se pudo extraer informaci\u00f3n de {filename}")
                        self.errors += 1
                        
                except Exception as e:
                    self.log(f"  [X] Error procesando {filename}: {e}")
                    self.errors += 1

    def check_dependencies(self):
        # 0. Check for Local Poppler (User requested specific path)
        # Look for the directory structure "poppler-XX/Library/bin" or "poppler-XX/bin"
        local_poppler_found = False
        cwd = os.getcwd()
        possible_patterns = [
            os.path.join(cwd, "poppler-25.12.0", "Library", "bin"),
            os.path.join(cwd, "poppler-25.12.0", "bin"),
        ]
        
        # Also check generalized pattern in case version changes
        for item in os.listdir(cwd):
            if "poppler" in item.lower() and os.path.isdir(item):
                 possible_patterns.append(os.path.join(cwd, item, "Library", "bin"))
                 possible_patterns.append(os.path.join(cwd, item, "bin"))

        for path in possible_patterns:
            if os.path.exists(path):
                self.log(f"  [i] Poppler local detectado: {path}")
                os.environ["PATH"] += os.pathsep + path
                local_poppler_found = True
                break

        # 1. Check Tesseract
        tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        else:
            # Check if it's in PATH by running a blind command
            try:
                pytesseract.get_tesseract_version()
            except:
                messagebox.showwarning(
                    "Dependencia faltante: Tesseract", 
                    "No se detectó Tesseract-OCR. La lectura de archivos escaneados fallará.\n"
                    "Por favor instale Tesseract o verifique que esté en el PATH."
                )

        # 2. Check Poppler (needed for pdf2image)
        try:
            from pdf2image.exceptions import PDFInfoNotInstalledError
            try:
                from pdf2image import pdfinfo_from_path
                # We can't easily dry-run without a file, but importing usually checks for poppler in PATH
                # If we found it locally, we assume it works.
                if not local_poppler_found:
                   # Try a dummy check if possible, mostly implicit
                   pass
            except ImportError:
                pass
        except ImportError:
            pass
            
if __name__ == "__main__":
    if sys.platform.startswith('win'):
        # Fix for high DPI displays on Windows
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
            
    root = tk.Tk()
    app = PDFOrganizerApp(root)
    root.mainloop()
