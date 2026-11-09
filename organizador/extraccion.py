"""Extracción de texto de PDFs e imágenes.

- PDFs con texto: PyMuPDF.
- PDFs escaneados e imágenes: se renderizan con PyMuPDF/Pillow y se leen con
  RapidOCR (ONNX, 100% local; no requiere Tesseract ni Poppler).
"""
import hashlib
import os

import numpy as np
import pymupdf
from PIL import Image, ImageOps

MIN_TEXTO_PDF = 80   # menos caracteres que esto => se trata como escaneado
MIN_TEXTO_PDF_CON_IMAGEN = 150  # si hay imágenes, se exige más texto antes de omitir el OCR
MAX_PAGINAS_OCR = 3
MAX_LADO_IMAGEN = 2400

_ocr_engine = None


def _ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
    return _ocr_engine


def hash_archivo(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _ocr_array(img: np.ndarray) -> str:
    resultado, _ = _ocr()(img)
    if not resultado:
        return ""
    # Ordenar cajas por renglón (y) y luego x para conservar el orden de lectura
    cajas = []
    for box, texto, _conf in resultado:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        cajas.append((min(ys), min(xs), max(ys) - min(ys), texto))
    cajas.sort(key=lambda c: (c[0], c[1]))
    lineas, actual, y_ref, alto_ref = [], [], None, None
    for y, x, alto, texto in cajas:
        if y_ref is not None and y - y_ref > max(alto_ref, alto) * 0.6:
            lineas.append(" ".join(actual))
            actual = []
            y_ref = None
        if y_ref is None:
            y_ref, alto_ref = y, alto
        actual.append(texto)
    if actual:
        lineas.append(" ".join(actual))
    return "\n".join(lineas)


def _ocr_imagen_pil(im: Image.Image) -> str:
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((MAX_LADO_IMAGEN, MAX_LADO_IMAGEN))
    return _ocr_array(np.array(im))


def extraer_texto(ruta: str) -> tuple[str, str]:
    """Devuelve (texto, metodo) donde metodo es 'pdf-texto', 'pdf-ocr' u 'ocr'."""
    ext = os.path.splitext(ruta)[1].lower()
    if ext == ".pdf":
        with pymupdf.open(ruta) as doc:
            texto = "\n".join(p.get_text() for p in doc)
            tiene_imagenes = any(p.get_images() for p in doc)
            # Diplomas que solo traen el nombre como texto y el resto en imagen => OCR
            if len(texto.strip()) >= MIN_TEXTO_PDF_CON_IMAGEN or (
                    len(texto.strip()) >= MIN_TEXTO_PDF and not tiene_imagenes):
                return texto, "pdf-texto"
            partes = []
            for i, pagina in enumerate(doc):
                if i >= MAX_PAGINAS_OCR:
                    break
                pix = pagina.get_pixmap(dpi=200)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                partes.append(_ocr_array(arr[:, :, :3].copy()))
            ocr = "\n".join(partes)
            # Algunos PDFs traen un poco de texto real (folios, nombre) + imagen
            combinado = (texto.strip() + "\n" + ocr).strip()
            return combinado, "pdf-ocr"
    with Image.open(ruta) as im:
        return _ocr_imagen_pil(im), "ocr"
