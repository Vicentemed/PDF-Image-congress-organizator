"""Clasificador por reglas (funciona sin Ollama y sirve de respaldo/validación del LLM)."""
import os
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MES_RE = "|".join(sorted(MESES, key=len, reverse=True))

ACRONIMOS = {
    "universidad autonoma de aguascalientes": "Universidad Autónoma de Aguascalientes",
    "universidad autonoma de zacatecas": "Universidad Autónoma de Zacatecas",
    "universidad autonoma de san luis potosi": "Universidad Autónoma de San Luis Potosí",
    "universidad nacional autonoma de mexico": "Universidad Nacional Autónoma de México",
    "secihti": "Secretaría de Ciencia, Humanidades, Tecnología e Innovación (SECIHTI)",
    "conahcyt": "CONAHCYT",
    "sociedad nacional de investigadores en odontologia": "Sociedad Nacional de Investigadores en Odontología, A.C.",
    "colegio mexicano de implantologia": "Colegio Mexicano de Implantología Bucal y Maxilofacial, A.C.",
    "instituto aguascalentense de las personas adultas mayores": "Instituto Aguascalentense de las Personas Adultas Mayores (IAPAM)",
    "facultad de odontologia, unam": "Facultad de Odontología, UNAM",
    "radio universidad": "Radio UAA 94.5 FM, Universidad Autónoma de Aguascalientes",
}

REVISTAS = [
    "Scientific Reports", "BMC Oral Health", "BMC Surgery", "Journal of Public Health Dentistry",
    "BMC Public Health", "BMC Medical Education", "PLOS ONE", "Clinical Oral Investigations",
]


def sin_acentos(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def normalizar(s: str) -> str:
    return re.sub(r"\s+", " ", sin_acentos(s).lower()).strip()


# ---------------------------------------------------------------- nombre

def _partes_nombre(nombre: str) -> list[str]:
    return [p for p in normalizar(nombre).split() if len(p) > 2]


def ubicar_nombre(texto: str, nombre: str) -> int:
    """Posición aproximada (en texto normalizado) del nombre del usuario, o -1.

    Tolera errores de OCR ('Vilpando', 'Bsparza') y nombres pegados
    ('VICENTEESPARZA-VILLALPANDO'). Requiere al menos 2 de las partes del nombre.
    """
    t = normalizar(texto)
    partes = _partes_nombre(nombre)
    if not partes:
        return -1
    encontrados = {}
    for m in re.finditer(r"[a-z]+", t):
        tok = m.group()
        for p in partes:
            if p in encontrados:
                continue
            if tok == p or (len(tok) >= 5 and SequenceMatcher(None, tok, p).ratio() >= 0.78) or (
                len(tok) > len(p) + 2 and p in tok
            ):
                encontrados[p] = m.start()
    # Los apellidos son lo distintivo; el nombre de pila solo no basta
    apellidos = partes[1:] if len(partes) > 1 else partes
    if len(encontrados) >= 2 and any(a in encontrados for a in apellidos):
        return min(encontrados.values())
    return -1


def nombre_presente(texto: str, nombre: str) -> bool:
    if ubicar_nombre(texto, nombre) >= 0:
        return True
    # Los reportes de revisión descargados de la plataforma ("Your review report")
    # son del propio usuario aunque no incluyan su nombre.
    return "your review report" in normalizar(texto)


# ---------------------------------------------------------------- fechas

def _a_fecha(d, m, y):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def encontrar_fechas(texto: str) -> list[date]:
    t = normalizar(texto)
    # versión con espacios reinsertados para OCR tipo "15denoviembredel2024"
    t2 = re.sub(r"([a-z])(\d)", r"\1 \2", t)
    t2 = re.sub(r"(\d)([a-z])", r"\1 \2", t2)
    t2 = re.sub(rf"(de|del)({_MES_RE})", r"\1 \2", t2)
    t2 = re.sub(rf"({_MES_RE})(de|del)\b", r"\1 \2", t2)
    fechas = []
    # 21 de febrero de 2025 / 19, 20 y 21 de febrero del 2025 / 13 de noviembre 2024
    for m in re.finditer(rf"\b(\d{{1,2}})\s+(?:de\s+)?({_MES_RE})\s*,?\s*(?:de\s+|del\s+)?(\d{{4}})\b", t2):
        f = _a_fecha(m.group(1), MESES[m.group(2)], m.group(3))
        if f:
            fechas.append(f)
    # English: March 18, 2025
    for m in re.finditer(rf"\b({_MES_RE})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", t2):
        f = _a_fecha(m.group(2), MESES[m.group(1)], m.group(3))
        if f:
            fechas.append(f)
    # 2025-03-18 / 18/03/2025
    for m in re.finditer(r"\b(20\d\d)-(\d\d)-(\d\d)\b", t2):
        f = _a_fecha(m.group(3), m.group(2), m.group(1))
        if f:
            fechas.append(f)
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b", t2):
        f = _a_fecha(m.group(1), m.group(2), m.group(3))
        if f:
            fechas.append(f)
    return [f for f in fechas if 1990 <= f.year <= date.today().year + 1]


def fecha_principal(texto: str, nombre_archivo: str = "") -> tuple[str, str]:
    """(fecha ISO, año). Usa la fecha más reciente (normalmente la de expedición)."""
    fechas = encontrar_fechas(texto)
    if fechas:
        f = max(fechas)
        return f.isoformat(), str(f.year)
    t = normalizar(texto)
    m = re.search(rf"\b({_MES_RE})\s+(?:de\s+|del\s+)?(20\d\d)\b", t)
    if m:
        return f"{m.group(2)}-{MESES[m.group(1)]:02d}", m.group(2)
    m = re.search(r"\b(20[0-4]\d)\b", sin_acentos(nombre_archivo))
    if m:
        return m.group(1), m.group(1)
    m = re.search(r"\bin (20[0-4]\d)\b", t)
    if m:
        return m.group(1), m.group(1)
    return "", ""


# ---------------------------------------------------------------- tipo / categoría

def tipo_documento(texto: str) -> str:
    t = normalizar(texto)
    if "review report" in t or "reviewer's report" in t or "reviewer report" in t:
        return "Reporte de revisión"
    if "certificate" in t or "certificado" in t:
        return "Certificado"
    if "diploma" in t:
        return "Diploma"
    pos = {}
    for clave, tipo in (("constancia", "Constancia"), ("hace constar", "Constancia"),
                        ("hago constar", "Constancia"), ("reconocimiento", "Reconocimiento")):
        i = t.find(clave)
        if i >= 0:
            pos[tipo] = min(i, pos.get(tipo, i))
    if pos:
        return min(pos, key=pos.get)
    if "a quien corresponda" in t or "presente" in t:
        return "Carta"
    return "Otro"


def _es_coautoria(texto: str, nombre: str) -> bool:
    """La constancia es de otra persona y el usuario aparece en la lista de coautores."""
    t = normalizar(texto)
    pos_nombre = ubicar_nombre(texto, nombre)
    if pos_nombre < 0:
        return False
    m = re.search(r"(?:constancia|reconocimiento|presente)\s*a\s*:\s*|\ba\s*:\s*", t)
    if not m:
        return False
    inicio = m.end()
    # Hay otro nombre propio antes del nuestro dentro de la línea de destinatarios
    tramo = t[inicio:pos_nombre]
    if pos_nombre > inicio and len(re.findall(r"[a-z]{3,}", tramo)) >= 2 and len(tramo) < 120:
        return True
    return False


def categoria(texto: str, nombre: str, presente: bool | None = None) -> str:
    t = normalizar(texto)
    if presente is None:
        presente = nombre_presente(texto, nombre)
    if not presente:
        return "Otro"
    if any(k in t for k in ("review report", "reviewer", "revisor", "evaluador", "e v a l u a d o r",
                             "jurado", "dictaminador", "arbitro", "arbitraje")):
        return "Evaluador / Revisor"
    if re.search(r"por su (?:asistencia|participacion como asistente)", t):
        return "Asistencia"
    if re.search(r"(?<!coordinador del )(?<!coordinadora del )comite (?:organizador|cientifico)", t):
        return "Comité organizador"
    if any(k in t for k in ("formacion docente", "acredito el curso", "curso de", "taller", "diplomado")):
        return "Curso / Formación docente"
    if any(k in t for k in ("ponente", "ponencia", "conferencista", "conferencia magistral",
                             "expositor", "con el tema", "speaker", "cartel")):
        if _es_coautoria(texto, nombre):
            return "Coautoría"
        return "Ponencia"
    if any(k in t for k in ("radio", "television", "entrevista", "programa de")):
        return "Divulgación"
    if any(k in t for k in ("asistencia", "asistente", "attendance", "participacion en el")):
        return "Asistencia"
    if any(k in t for k in ("posgrado", "expediente", "comision", "plan de estudios", "opinion tecnica")):
        return "Participación institucional"
    return "Otro"


# ---------------------------------------------------------------- otros campos

def institucion(texto: str) -> str:
    t = normalizar(texto)
    for clave, nombre in ACRONIMOS.items():
        if clave in t.replace("autonomade", "autonoma de"):
            return nombre
    for r in REVISTAS:
        if normalizar(r) in t:
            return "Springer Nature" if r in ("Scientific Reports",) or r.startswith("BMC") else r
    m = re.search(r"(Universidad [A-ZÁÉÍÓÚ][\wáéíóú]+(?: (?:de|del|la|las)? ?[A-ZÁÉÍÓÚ][\wáéíóú]+){0,4})", texto)
    if m:
        return m.group(1).strip()
    return ""


_EVENTO_RE = re.compile(
    r"((?:\b[XVIL]{1,6}\b|\d+\s*(?:er|do|ro|to|o|º|°)?\.?|primer|segundo|tercer|cuarto)?\s*"
    r"(?:congreso|encuentro|semana cultural|jornadas?|simposi(?:o|um)|seminario|foro|campamento|"
    r"concurso|convocatoria|coloquio|sesiones informativas|programa de radio)"
    r"[^.;:\"“”]{3,110})",
    re.IGNORECASE,
)


# Prefijo del número de manuscrito de Springer Nature/BMC (p. ej. 12893_2023_2204) → revista
PREFIJOS_REVISTA = {
    "12893": "BMC Surgery", "12903": "BMC Oral Health", "12889": "BMC Public Health",
    "12909": "BMC Medical Education", "41598": "Scientific Reports",
}


def revista_por_archivo(nombre_archivo: str) -> str:
    m = re.match(r"^(\d{5})_\d{4}_\d+", os.path.basename(nombre_archivo or ""))
    return PREFIJOS_REVISTA.get(m.group(1), "") if m else ""


def evento(texto: str, nombre_archivo: str = "") -> str:
    plano = re.sub(r"\s+", " ", texto)
    if revista_por_archivo(nombre_archivo):
        return revista_por_archivo(nombre_archivo)
    for r in REVISTAS:
        if r.lower() in plano.lower():
            return r
    m = _EVENTO_RE.search(plano)
    if not m:
        return ""
    ev = m.group(1).strip(" ,")
    ev = re.split(r",? (?:llevad[oa]|realizad[oa]|celebrad[oa]|efectuad[oa]|el cual|que se|cumpliendo|en la ciudad|el d[ií]a)",
                  ev, flags=re.IGNORECASE)[0]
    return ev.strip(" ,")


LEMAS = ("por mi raza", "se lumen proferre", "selumen proferre", "humanismi et", "pro scientia",
         "luz, ciencia", "a t e n t a m e n t e", "atentamente")


def es_lema(s: str) -> bool:
    n = normalizar(s)
    return any(l in n for l in LEMAS)


def titulo(texto: str) -> str:
    plano = re.sub(r"\s+", " ", texto)
    for m in re.finditer(r"[“\"«]([^”\"»]{8,200})[”\"»]", plano):
        if not es_lema(m.group(1)):
            return m.group(1).strip(" ,")
    for pat in (
                r"(?:con el tema|con la ponencia|ponencia)\s*:?\s*([^.]{8,200})",
                r"(?:curso de formaci[oó]n docente|conferencia de formaci[oó]n docente)\s+([^,]{5,150})",
                r"Manuscript\s+(.{10,250}?)\s+(?:Feedback|Comments)",
                r"Title:\s*(.{10,250}?)\s+Version"):
        m = re.search(pat, plano, re.IGNORECASE)
        if m:
            return m.group(1).strip(" ,")
    return ""


def horas(texto: str) -> str:
    m = re.search(r"\b(\d{1,3})\s*(?:horas|hrs\.?|hours)\b", normalizar(texto))
    return m.group(1) if m else ""


def titular(texto: str, nombre: str, presente: bool) -> str:
    plano = re.sub(r"\s+", " ", texto)
    m = re.search(r"\ba\s*:\s*((?:(?:Dr|Dra|Mtro|Mtra|D\. en C)\.?\s*)?[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+(?:\s+(?:de|del|la)?\s*[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+){1,5})",
                  plano)
    if m:
        return m.group(1).strip()
    return nombre if presente else ""


def resumen_plantilla(c: dict, nombre_completo: str) -> str:
    """Resumen determinista a partir de los campos (respaldo cuando no hay LLM)."""
    cat = c.get("categoria", "")
    frases = {
        "Ponencia": "participó como ponente",
        "Coautoría": "participó como coautor de un trabajo presentado",
        "Evaluador / Revisor": "participó como evaluador/revisor",
        "Asistencia": "asistió",
        "Curso / Formación docente": "acreditó la actividad de formación",
        "Comité organizador": "formó parte del comité organizador",
        "Participación institucional": "participó",
        "Divulgación": "participó en una actividad de divulgación",
    }
    accion = frases.get(cat, "figura en el documento")
    partes = [f"{c.get('tipo_documento') or 'Documento'} en la que se indica que {nombre_completo} {accion}"]
    if c.get("titulo"):
        partes.append(f"con «{c['titulo']}»")
    if c.get("evento"):
        partes.append(f"en {c['evento']}")
    s = " ".join(partes)
    if c.get("institucion"):
        s += f", otorgada por {c['institucion']}"
    if c.get("fecha"):
        s += f" ({c['fecha']})"
    if c.get("horas"):
        s += f", con una duración de {c['horas']} horas"
    return s + "."


def clasificar(texto: str, nombre: str, nombre_archivo: str = "", nombre_completo: str = "") -> dict:
    presente = nombre_presente(texto, nombre)
    fecha, _anio = fecha_principal(texto, nombre_archivo)
    campos = {
        "tipo_documento": tipo_documento(texto),
        "categoria": categoria(texto, nombre, presente),
        "titular": titular(texto, nombre, presente),
        "mi_nombre_presente": presente,
        "fecha": fecha,
        "fecha_evento": "",
        "institucion": "Springer Nature" if revista_por_archivo(nombre_archivo) else institucion(texto),
        "evento": evento(texto, nombre_archivo),
        "titulo": titulo(texto),
        "lugar": "",
        "horas": horas(texto),
    }
    campos["resumen"] = resumen_plantilla(campos, nombre_completo or nombre)
    return campos
