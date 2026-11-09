"""Informe general de productividad en Word (.docx), con filtros por año, categoría y estado."""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .config import CATEGORIAS
from .excel import _unicos
from .reglas import normalizar

AZUL = RGBColor(0x1F, 0x4E, 0x78)
GRIS = RGBColor(0x66, 0x66, 0x66)
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]

# Frases para la redacción del resumen general (singular, plural)
FRASES = {
    "Ponencia": ("ponencia o conferencia", "ponencias o conferencias"),
    "Coautoría": ("trabajo presentado como coautor", "trabajos presentados como coautor"),
    "Evaluador / Revisor": ("participación como evaluador o revisor", "participaciones como evaluador o revisor"),
    "Asistencia": ("asistencia a congresos o eventos académicos", "asistencias a congresos o eventos académicos"),
    "Curso / Formación docente": ("curso o actividad de formación docente", "cursos o actividades de formación docente"),
    "Comité organizador": ("participación en comité organizador", "participaciones en comités organizadores"),
    "Participación institucional": ("participación institucional", "participaciones institucionales"),
    "Divulgación": ("actividad de divulgación científica", "actividades de divulgación científica"),
    "Otro": ("otra actividad", "otras actividades"),
}


@dataclass
class Filtros:
    anios: list[str] = field(default_factory=list)        # vacío = todos; "SinFecha" permitido
    categorias: list[str] = field(default_factory=list)   # vacío = todas
    solo_verificados: bool = False
    incluir_sin_mi_nombre: bool = False
    texto: str = ""
    incluir_anexo: bool = True

    @classmethod
    def desde_dict(cls, d: dict) -> "Filtros":
        d = d or {}
        return cls(
            anios=[str(a) for a in d.get("anios") or []],
            categorias=[c for c in d.get("categorias") or [] if c in CATEGORIAS],
            solo_verificados=bool(d.get("solo_verificados")),
            incluir_sin_mi_nombre=bool(d.get("incluir_sin_mi_nombre")),
            texto=str(d.get("texto") or "").strip(),
            incluir_anexo=bool(d.get("incluir_anexo", True)),
        )


def anio_de(reg: dict) -> str:
    f = reg["campos"].get("fecha") or ""
    return f[:4] if f[:4].isdigit() else "SinFecha"


def filtrar(registros: list[dict], f: Filtros) -> list[dict]:
    salida = []
    q = normalizar(f.texto)
    for r in registros:
        c = r["campos"]
        if not c.get("mi_nombre_presente") and not f.incluir_sin_mi_nombre:
            continue
        if f.anios and anio_de(r) not in f.anios:
            continue
        if f.categorias and c.get("categoria") not in f.categorias:
            continue
        if f.solo_verificados and not r.get("verificado"):
            continue
        if q and q not in normalizar(" ".join(str(v) for v in c.values()) + " " + r.get("archivo_original", "")):
            continue
        salida.append(r)
    return _unicos(salida)


def _orden_anio(a: str):
    return (1, 0) if not a.isdigit() else (0, -int(a))


def _fecha_larga(iso: str) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", iso or "")
    if m:
        return f"{int(m.group(3))} de {MESES[int(m.group(2)) - 1]} de {m.group(1)}"
    m = re.match(r"^(\d{4})-(\d{2})$", iso or "")
    if m:
        return f"{MESES[int(m.group(2)) - 1]} de {m.group(1)}"
    return iso or "sin fecha"


def _num(n: int) -> str:
    palabras = ["cero", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"]
    return palabras[n] if n < len(palabras) else str(n)


def _lista_es(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def descripcion_periodo(anios: list[str]) -> str:
    con_fecha = sorted(a for a in anios if a.isdigit())
    txt = ""
    if con_fecha:
        enteros = list(map(int, con_fecha))
        if len(enteros) == 1:
            txt = con_fecha[0]
        elif enteros == list(range(enteros[0], enteros[-1] + 1)):
            txt = f"{enteros[0]}–{enteros[-1]}"
        else:
            txt = _lista_es(con_fecha)
    if "SinFecha" in anios:
        txt = (txt + " y documentos sin fecha") if txt else "documentos sin fecha"
    return txt or "todos los años"


def _horas(reg: dict) -> float:
    try:
        return float(str(reg["campos"].get("horas") or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _institucion_corta(s: str) -> str:
    """'Universidad X, Departamento Y' → 'Universidad X'; 'Facultad de Odontología, UNAM' se conserva."""
    parte = (s or "").split(";")[0].strip()
    if parte.startswith(("Universidad", "Secretar", "Sociedad", "Colegio", "Instituto", "Benem")):
        parte = parte.split(",")[0].strip()
    return parte


def _evento_o_titulo(c: dict) -> str:
    evento, titulo = (c.get("evento") or "").strip(), (c.get("titulo") or "").strip()
    if titulo and (not evento or re.match(r"^(curso|conferencia|taller)( de formaci[oó]n docente)?$", evento, re.I)):
        return titulo
    return evento or titulo


def parrafo_general(regs: list[dict], nombre: str, periodo: str) -> list[str]:
    """Texto narrativo determinista del resumen general (sin LLM, siempre consistente)."""
    if not regs:
        return [f"No se encontraron actividades para {periodo} con los filtros seleccionados."]
    cats = Counter(r["campos"].get("categoria", "Otro") for r in regs)
    partes = []
    for c in CATEGORIAS:
        n = cats.get(c)
        if n:
            sing, plur = FRASES[c]
            partes.append(f"{_num(n)} {sing if n == 1 else plur}")
    total = len(regs)
    p1 = (f"Durante el periodo {periodo}, el {nombre} acumuló {total} "
          f"{'actividad académica documentada' if total == 1 else 'actividades académicas documentadas'}: "
          f"{_lista_es(partes)}.")
    parrafos = [p1]

    inst = Counter(_institucion_corta(r["campos"].get("institucion")) for r in regs if r["campos"].get("institucion"))
    if inst:
        top = [i for i, _ in inst.most_common(4)]
        parrafos.append(f"Las actividades fueron avaladas por {len(inst)} "
                        f"{'institución' if len(inst) == 1 else 'instituciones u organismos'}, entre los que destacan "
                        f"{_lista_es(top)}.")

    extras = []
    h_cursos = sum(_horas(r) for r in regs if r["campos"].get("categoria") == "Curso / Formación docente")
    if h_cursos:
        extras.append(f"{h_cursos:g} horas de formación docente acreditadas")
    n_rev = sum(1 for r in regs if r["campos"].get("categoria") == "Evaluador / Revisor")
    revistas = sorted({r["campos"].get("evento") for r in regs
                       if r["campos"].get("categoria") == "Evaluador / Revisor"
                       and r["campos"].get("tipo_documento") in ("Certificado", "Reporte de revisión")
                       and r["campos"].get("evento")})
    if revistas and n_rev:
        extras.append(f"actividades de revisión por pares para las revistas {_lista_es(revistas)}")
    if extras:
        parrafos.append("Asimismo, se registran " + _lista_es(extras) + ".")
    return parrafos


# ------------------------------------------------------------------ formato docx

def _sombrear(celda, color_hex: str):
    tcPr = celda._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    tcPr.append(shd)


def _campo_pagina(parrafo):
    for tipo, texto in (("begin", None), (None, "PAGE"), ("end", None)):
        run = parrafo.add_run()
        if tipo:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = texto
        run._r.append(el)


def _repetir_encabezado(fila):
    trPr = fila._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def _tabla(doc, encabezados, filas, anchos_cm, tam=9, totales=False):
    t = doc.add_table(rows=1, cols=len(encabezados))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(encabezados):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(tam)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        _sombrear(c, "1F4E78")
    _repetir_encabezado(t.rows[0])
    for k, fila in enumerate(filas):
        celdas = t.add_row().cells
        ultima = totales and k == len(filas) - 1
        for i, v in enumerate(fila):
            celdas[i].text = ""
            r = celdas[i].paragraphs[0].add_run("" if v in (None, 0) and i > 0 and totales else str(v))
            r.font.size = Pt(tam)
            r.bold = ultima or (totales and i == 0)
            if ultima:
                _sombrear(celdas[i], "E8EEF4")
            if totales and i > 0:
                celdas[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for fila in t.rows:
        for i, w in enumerate(anchos_cm):
            fila.cells[i].width = Cm(w)
    return t


def generar_word(registros: list[dict], ruta: str, nombre_completo: str, filtros: Filtros | None = None) -> dict:
    f = filtros or Filtros()
    regs = filtrar(registros, f)
    anios = sorted({anio_de(r) for r in regs}, key=_orden_anio)
    periodo = descripcion_periodo(f.anios or anios)

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(11)
    estilo.paragraph_format.space_after = Pt(6)
    for nombre_estilo, tam in (("Heading 1", 15), ("Heading 2", 12.5), ("Title", 22)):
        s = doc.styles[nombre_estilo]
        s.font.name = "Calibri"
        s.font.size = Pt(tam)
        s.font.color.rgb = AZUL
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.59), Cm(27.94)  # carta
    for lado in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, lado, Cm(2.3))
    pie = sec.footer.paragraphs[0]
    pie.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = pie.add_run(f"Informe de productividad académica · {nombre_completo} · Página ")
    r.font.size = Pt(8)
    r.font.color.rgb = GRIS
    _campo_pagina(pie)

    # ---- portada / encabezado
    doc.add_paragraph("Informe de productividad académica", style="Title")
    p = doc.add_paragraph()
    r = p.add_run(nombre_completo)
    r.bold = True
    r.font.size = Pt(13)
    p = doc.add_paragraph()
    r = p.add_run(f"Periodo: {periodo}")
    r.font.size = Pt(11)
    filtros_txt = []
    if f.categorias:
        filtros_txt.append("categorías: " + ", ".join(f.categorias))
    if f.solo_verificados:
        filtros_txt.append("solo documentos verificados")
    if f.texto:
        filtros_txt.append(f"búsqueda: «{f.texto}»")
    if f.incluir_sin_mi_nombre:
        filtros_txt.append("incluye documentos donde no aparece el titular")
    r = doc.add_paragraph().add_run(
        f"Generado el {datetime.now():%d/%m/%Y}" + (" · Filtros: " + "; ".join(filtros_txt) if filtros_txt else ""))
    r.font.size = Pt(9)
    r.font.color.rgb = GRIS

    # ---- resumen general
    doc.add_heading("Resumen general", level=1)
    for texto in parrafo_general(regs, nombre_completo, periodo):
        doc.add_paragraph(texto).paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    if regs:
        conteo = defaultdict(Counter)
        for reg in regs:
            conteo[reg["campos"].get("categoria", "Otro")][anio_de(reg)] += 1
        cats = [c for c in CATEGORIAS if conteo.get(c)]
        etiquetas = ["Sin fecha" if a == "SinFecha" else a for a in anios]
        filas = [[c] + [conteo[c].get(a, 0) for a in anios] + [sum(conteo[c].values())] for c in cats]
        filas.append(["Total"] + [sum(conteo[c].get(a, 0) for c in cats) for a in anios] + [len(regs)])
        ancho_cat = 6.2
        ancho_col = max(1.6, min(2.4, (16.9 - ancho_cat) / (len(anios) + 1)))
        doc.add_paragraph()
        cap = doc.add_paragraph()
        rr = cap.add_run("Tabla 1. Actividades por categoría y año")
        rr.bold = True
        rr.font.size = Pt(9.5)
        _tabla(doc, ["Categoría"] + etiquetas + ["Total"], filas, [ancho_cat] + [ancho_col] * (len(anios) + 1),
               tam=10, totales=True)

    # ---- detalle por año y categoría
    for anio in anios:
        del_anio = [r for r in regs if anio_de(r) == anio]
        titulo = "Documentos sin fecha" if anio == "SinFecha" else f"Año {anio}"
        doc.add_heading(f"{titulo} ({len(del_anio)} {'actividad' if len(del_anio) == 1 else 'actividades'})", level=1)
        for cat in CATEGORIAS:
            items = sorted([r for r in del_anio if r["campos"].get("categoria") == cat],
                           key=lambda r: r["campos"].get("fecha") or "")
            if not items:
                continue
            doc.add_heading(f"{cat} ({len(items)})", level=2)
            for i, reg in enumerate(items, 1):
                c = reg["campos"]
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.6)
                p.paragraph_format.first_line_indent = Cm(-0.6)
                p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                p.add_run(f"{i}. ").bold = True
                if c.get("fecha"):
                    rf = p.add_run(_fecha_larga(c["fecha"]).capitalize() + ". ")
                    rf.bold = True
                p.add_run(c.get("resumen") or c.get("evento") or reg.get("archivo_original", ""))

    # ---- anexo
    if f.incluir_anexo and regs:
        nueva = doc.add_section()
        nueva.orientation = WD_ORIENT.LANDSCAPE
        nueva.page_width, nueva.page_height = Cm(27.94), Cm(21.59)
        doc.add_heading("Anexo. Relación de documentos probatorios", level=1)
        filas = []
        for reg in sorted(regs, key=lambda r: (r["campos"].get("fecha") or "0000"), reverse=True):
            c = reg["campos"]
            filas.append([c.get("fecha") or "—", c.get("categoria", ""), _evento_o_titulo(c),
                          c.get("institucion", ""), c.get("horas") or "",
                          reg.get("archivo_nuevo") or reg.get("archivo_original", "")])
        _tabla(doc, ["Fecha", "Categoría", "Evento / Título", "Institución", "Horas", "Archivo"], filas,
               [2.0, 3.2, 6.0, 5.6, 1.2, 5.3], tam=8)

    doc.save(ruta)
    return {"ruta": ruta, "documentos": len(regs), "periodo": periodo}


def nombre_archivo_informe(filtros: Filtros, anios_disponibles: list[str] | None = None) -> str:
    periodo = descripcion_periodo(filtros.anios) if filtros.anios else "completo"
    periodo = re.sub(r"[^\w–-]+", "_", periodo.replace("–", "-")).strip("_")
    sufijo = ""
    if filtros.categorias and len(filtros.categorias) <= 2:
        sufijo = "_" + "_".join(re.sub(r"\W+", "", normalizar(c).title()) for c in filtros.categorias)
    elif filtros.categorias:
        sufijo = "_filtrado"
    return f"Informe_productividad_{periodo}{sufijo}.docx"
