"""Exportación de la memoria a Excel (documentos, conteo por año/categoría e informe)."""
import re
from collections import Counter, defaultdict
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .config import CATEGORIAS
from .reglas import sin_acentos

COLUMNAS = [
    ("Fecha", "fecha", 12),
    ("Año", "_anio", 7),
    ("Categoría", "categoria", 22),
    ("Tipo de documento", "tipo_documento", 18),
    ("Titular", "titular", 28),
    ("¿Aparece mi nombre?", "_presente", 11),
    ("Institución que otorga", "institucion", 40),
    ("Evento / Congreso / Revista", "evento", 42),
    ("Título / Tema", "titulo", 42),
    ("Fechas del evento", "fecha_evento", 20),
    ("Lugar", "lugar", 18),
    ("Horas", "horas", 7),
    ("Resumen", "resumen", 80),
    ("Archivo renombrado", "_archivo_nuevo", 48),
    ("Archivo original", "_archivo_original", 36),
    ("Verificado", "_verificado", 10),
    ("Confianza", "_confianza", 10),
    ("Posible duplicado", "_duplicado", 30),
    ("Método", "_metodo", 24),
]

AZUL = PatternFill("solid", fgColor="1F4E78")
GRIS = PatternFill("solid", fgColor="F2F2F2")
AMARILLO = PatternFill("solid", fgColor="FFF2CC")
BORDE = Border(bottom=Side(style="thin", color="D9D9D9"))


def _valor(reg: dict, clave: str):
    c = reg.get("campos", {})
    if clave == "_anio":
        f = c.get("fecha") or ""
        return int(f[:4]) if f[:4].isdigit() else "SinFecha"
    if clave == "_presente":
        return "Sí" if c.get("mi_nombre_presente") else "No"
    if clave == "_archivo_nuevo":
        return reg.get("archivo_nuevo", "")
    if clave == "_archivo_original":
        return reg.get("archivo_original", "")
    if clave == "_verificado":
        return "Sí" if reg.get("verificado") else "No"
    if clave == "_confianza":
        return "verificado" if reg.get("verificado") else reg.get("confianza", "")
    if clave == "_duplicado":
        return reg.get("posible_duplicado", "")
    if clave == "_metodo":
        return reg.get("metodo", "")
    v = c.get(clave, "")
    if clave == "horas" and str(v).replace(".", "", 1).isdigit():
        return float(v) if "." in str(v) else int(v)
    return v


def _orden_anio(a):
    """Años del más reciente al más antiguo; 'SinFecha' al final."""
    return (1, 0) if not isinstance(a, int) else (0, -a)


def _clave_actividad(reg: dict) -> tuple:
    c = reg["campos"]
    norm = lambda s: re.sub(r"[^a-z0-9]", "", sin_acentos(str(s or "")).lower())  # noqa: E731
    return (c.get("fecha"), c.get("categoria"), norm(c.get("titular"))[:14], norm(c.get("evento"))[:40],
            norm(c.get("titulo"))[:40])


def _unicos(registros: list[dict]) -> list[dict]:
    """Una sola entrada por actividad (p. ej. dos fotos de la misma constancia). Prefiere la verificada."""
    vistos, salida = set(), []
    for r in sorted(registros, key=lambda x: not x.get("verificado")):
        k = _clave_actividad(r)
        if r["campos"].get("fecha") and k in vistos:
            continue
        vistos.add(k)
        salida.append(r)
    return salida


def _encabezado(ws, titulos, fila=1):
    for col, t in enumerate(titulos, 1):
        cel = ws.cell(row=fila, column=col, value=t)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = AZUL
        cel.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[fila].height = 32


def exportar(registros: list[dict], ruta: str, nombre_completo: str = "") -> str:
    registros = sorted(registros, key=lambda r: (r["campos"].get("fecha") or "0000"), reverse=True)
    wb = Workbook()

    # ---- Hoja 1: documentos
    ws = wb.active
    ws.title = "Documentos"
    _encabezado(ws, [c[0] for c in COLUMNAS])
    for i, reg in enumerate(registros, 2):
        for j, (_t, clave, _w) in enumerate(COLUMNAS, 1):
            cel = ws.cell(row=i, column=j, value=_valor(reg, clave))
            cel.alignment = Alignment(vertical="top", wrap_text=clave in ("resumen", "titulo", "evento", "institucion"))
            cel.border = BORDE
        if not reg.get("verificado") and reg.get("confianza") == "revisar":
            for j in range(1, len(COLUMNAS) + 1):
                ws.cell(row=i, column=j).fill = AMARILLO
    for j, (_t, _c, w) in enumerate(COLUMNAS, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS))}{max(1, len(registros) + 1)}"

    # ---- Hoja 2: conteo por año y categoría (solo documentos donde aparezco, sin duplicados)
    ws2 = wb.create_sheet("Por año y categoría")
    propios = _unicos([r for r in registros if r["campos"].get("mi_nombre_presente")])
    conteo = defaultdict(Counter)
    for r in propios:
        conteo[_valor(r, "_anio")][r["campos"].get("categoria", "Otro")] += 1
    anios = sorted(conteo, key=_orden_anio)
    _encabezado(ws2, ["Categoría"] + [str(a) for a in anios] + ["Total"])
    for i, cat in enumerate(CATEGORIAS, 2):
        ws2.cell(row=i, column=1, value=cat).font = Font(bold=True)
        for j, a in enumerate(anios, 2):
            ws2.cell(row=i, column=j, value=conteo[a][cat] or None)
        ws2.cell(row=i, column=len(anios) + 2, value=f"=SUM(B{i}:{get_column_letter(len(anios) + 1)}{i})")
    fila_total = len(CATEGORIAS) + 2
    ws2.cell(row=fila_total, column=1, value="Total").font = Font(bold=True)
    for j in range(2, len(anios) + 3):
        letra = get_column_letter(j)
        c = ws2.cell(row=fila_total, column=j, value=f"=SUM({letra}2:{letra}{fila_total - 1})")
        c.font = Font(bold=True)
        c.fill = GRIS
    ws2.column_dimensions["A"].width = 30
    for j in range(2, len(anios) + 3):
        ws2.column_dimensions[get_column_letter(j)].width = 11

    # ---- Hoja 3: informe de resúmenes listo para copiar
    ws3 = wb.create_sheet("Informe")
    ws3.column_dimensions["A"].width = 6
    ws3.column_dimensions["B"].width = 120
    ws3.cell(row=1, column=1, value=f"Informe de productividad académica — {nombre_completo}").font = Font(bold=True, size=14)
    ws3.cell(row=2, column=1, value=f"Generado el {datetime.now():%d/%m/%Y %H:%M}. Solo documentos donde aparece el "
                                    "nombre del titular; los duplicados se cuentan una vez.").font = Font(italic=True, color="666666")
    fila = 4
    por_anio = defaultdict(lambda: defaultdict(list))
    for r in propios:
        por_anio[_valor(r, "_anio")][r["campos"].get("categoria", "Otro")].append(r)
    for anio in sorted(por_anio, key=_orden_anio):
        ws3.cell(row=fila, column=1, value=str(anio)).font = Font(bold=True, size=13, color="1F4E78")
        fila += 1
        for cat in CATEGORIAS:
            docs = por_anio[anio].get(cat)
            if not docs:
                continue
            ws3.cell(row=fila, column=1, value=f"{cat} ({len(docs)})").font = Font(bold=True)
            fila += 1
            for n, r in enumerate(sorted(docs, key=lambda x: x["campos"].get("fecha") or ""), 1):
                ws3.cell(row=fila, column=1, value=n).alignment = Alignment(vertical="top")
                c = ws3.cell(row=fila, column=2, value=r["campos"].get("resumen", ""))
                c.alignment = Alignment(wrap_text=True, vertical="top")
                fila += 1
            fila += 1

    wb.save(ruta)
    return ruta
