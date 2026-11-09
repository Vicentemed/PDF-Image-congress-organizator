"""Identificación de documentos duplicados.

Tres señales (calibradas con los documentos reales):
1. Archivo idéntico (mismo hash SHA-256): se detecta al cargarlo y nunca se duplica en memoria.
2. Mismos datos clave: misma fecha, misma categoría, mismo titular y evento/título equivalente
   (p. ej. dos fotos o un escaneo y un PDF de la misma constancia).
3. Texto casi idéntico (TF-IDF ≥ 0.92) con fechas compatibles.

La similitud de texto sola NO basta: constancias distintas hechas con la misma plantilla
(cursos de la UAA, certificados de revisor) llegan a 0.84, por eso el umbral es alto.

Estado en cada registro de memoria:
- "descartado": True  → duplicado descartado (no cuenta en Excel/Word).
- "duplicado_de": id del documento que se conservó.
- "no_duplicado": [ids] → el usuario indicó que NO son duplicados (no se vuelve a sugerir).
"""
import math
import re
from collections import Counter
from itertools import combinations

from .reglas import normalizar

UMBRAL_TEXTO = 0.92
UMBRAL_EVENTO = 0.6
TITULOS_PERSONA = {"dr", "dra", "mtro", "mtra", "lic", "ing", "en", "c", "d", "ce", "cd", "mcb", "mce", "de", "del", "la"}


def _tokens(s: str, minimo: int = 3) -> set[str]:
    return set(re.findall(rf"[a-z0-9]{{{minimo},}}", normalizar(s or "")))


def _tokens_nombre(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", normalizar(s or "")) if t not in TITULOS_PERSONA and len(t) > 2}


def mismo_titular(a: str, b: str) -> bool:
    A, B = _tokens_nombre(a), _tokens_nombre(b)
    if not A or not B:
        return True
    return len(A & B) >= min(2, len(A), len(B))


def _solapamiento(a: str, b: str) -> float:
    A, B = _tokens(a), _tokens(b)
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    return len(A & B) / min(len(A), len(B))


def _fechas_compatibles(fa: str, fb: str) -> bool:
    if not fa or not fb:
        return True
    n = min(len(fa), len(fb))
    return fa[:n] == fb[:n]


class _Tfidf:
    def __init__(self, registros: list[dict]):
        self.tok = {r["id"]: Counter(re.findall(r"[a-z]{4,}", normalizar(r.get("texto") or ""))) for r in registros}
        df = Counter()
        for t in self.tok.values():
            df.update(t.keys())
        n = max(1, len(registros))
        self.vec = {}
        for rid, t in self.tok.items():
            v = {w: (1 + math.log(c)) * math.log((n + 1) / (df[w] + 1)) for w, c in t.items()}
            norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
            self.vec[rid] = {w: x / norma for w, x in v.items()}

    def coseno(self, a: str, b: str) -> float:
        va, vb = self.vec.get(a, {}), self.vec.get(b, {})
        if len(va) < 8 or len(vb) < 8:
            return 0.0
        if len(va) > len(vb):
            va, vb = vb, va
        return sum(x * vb.get(w, 0.0) for w, x in va.items())


def comparar(r1: dict, r2: dict, tfidf: _Tfidf | None = None) -> str:
    """Motivo por el que r1 y r2 parecen duplicados, o "" si no lo son."""
    if r1["id"] == r2["id"]:
        return ""
    if r2["id"] in (r1.get("no_duplicado") or []) or r1["id"] in (r2.get("no_duplicado") or []):
        return ""
    a, b = r1["campos"], r2["campos"]
    if not mismo_titular(a.get("titular"), b.get("titular")):
        return ""
    fa, fb = a.get("fecha") or "", b.get("fecha") or ""
    ev_a = f"{a.get('evento') or ''} {a.get('titulo') or ''}"
    ev_b = f"{b.get('evento') or ''} {b.get('titulo') or ''}"

    if a.get("categoria") == b.get("categoria"):
        if fa and fa == fb and _solapamiento(ev_a, ev_b) >= UMBRAL_EVENTO:
            return "Misma fecha, categoría, titular y evento"
        # Reportes de revisión sin fecha: mismo manuscrito
        if not fa and not fb and a.get("titulo") and normalizar(a.get("titulo")) == normalizar(b.get("titulo")):
            return "Mismo título y categoría"
    if tfidf and _fechas_compatibles(fa, fb):
        cos = tfidf.coseno(r1["id"], r2["id"])
        if cos >= UMBRAL_TEXTO:
            return f"Texto casi idéntico ({cos:.0%})"
    return ""


def _clave_principal(r: dict):
    """El que se conserva: no descartado, verificado, PDF con texto, más texto, más antiguo."""
    return (
        bool(r.get("descartado")),
        not r.get("verificado"),
        r.get("metodo_texto") != "pdf-texto",
        -len(r.get("texto") or ""),
        r.get("creado") or "",
        r.get("archivo_original") or "",
    )


def grupos(registros: list[dict]) -> list[dict]:
    """Grupos de posibles duplicados: [{"principal", "miembros", "motivos", "pendiente"}]."""
    regs = [r for r in registros if r.get("campos")]
    tfidf = _Tfidf(regs)
    padre = {r["id"]: r["id"] for r in regs}

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    motivos: dict[tuple, str] = {}
    for r1, r2 in combinations(regs, 2):
        m = comparar(r1, r2, tfidf)
        if not m and (r1.get("duplicado_de") == r2["id"] or r2.get("duplicado_de") == r1["id"]):
            m = "Marcado como duplicado"
        if m:
            motivos[(r1["id"], r2["id"])] = m
            padre[raiz(r1["id"])] = raiz(r2["id"])

    por_raiz: dict[str, list[dict]] = {}
    for r in regs:
        por_raiz.setdefault(raiz(r["id"]), []).append(r)
    salida = []
    for miembros in por_raiz.values():
        if len(miembros) < 2:
            continue
        miembros.sort(key=_clave_principal)
        ids = {m["id"] for m in miembros}
        mot = sorted({v for (x, y), v in motivos.items() if x in ids and y in ids})
        activos = [m for m in miembros if not m.get("descartado")]
        salida.append({
            "principal": miembros[0]["id"],
            "miembros": [m["id"] for m in miembros],
            "motivos": mot,
            "pendiente": len(activos) >= 2,
        })
    salida.sort(key=lambda g: (not g["pendiente"], g["miembros"][0]))
    return salida


def duplicados_de(reg: dict, registros: list[dict]) -> list[tuple[dict, str]]:
    """Documentos ya en memoria que parecen duplicados de `reg` (para avisar al procesarlo)."""
    otros = [r for r in registros if r["id"] != reg["id"] and not r.get("descartado")]
    tfidf = _Tfidf(otros + [reg])
    res = []
    for o in otros:
        m = comparar(reg, o, tfidf)
        if m:
            res.append((o, m))
    return res


def unicos(registros: list[dict]) -> list[dict]:
    """Una entrada por actividad: excluye descartados y, en grupos pendientes, deja solo el principal."""
    activos = [r for r in registros if not r.get("descartado")]
    sobran = set()
    for g in grupos(activos):
        sobran.update(g["miembros"][1:])
    return [r for r in activos if r["id"] not in sobran]
