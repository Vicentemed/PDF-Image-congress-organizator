"""Clasificador de Constancias Académicas.

Ejecutar:  python pdf_organizer.py
Abre la interfaz en el navegador (servidor local en 127.0.0.1; nada sale de la computadora).
"""
import argparse
import sys

try:
    from organizador.web import servir
except ImportError as e:
    sys.exit(f"Falta una librería: {e.name}\nEjecute:  pip install -r requirements.txt")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Clasificador de constancias académicas (interfaz web local)")
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--no-abrir", action="store_true", help="no abrir el navegador automáticamente")
    a = p.parse_args()
    servir(a.puerto, abrir=not a.no_abrir)
