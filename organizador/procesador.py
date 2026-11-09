"""Flujo completo: extraer texto → clasificar → renombrar/copiar → memoria → Excel."""
import os
import re
import shutil
import time
from datetime import datetime
from typing import Callable

from . import reglas
from .config import CATEGORIA_CORTA, CATEGORIAS, EXTENSIONES, TIPOS, Config
from .extraccion import extraer_texto, hash_archivo
from .llm import ClienteOllama
from .memoria import Memoria

FECHA_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
Log = Callable[[str], None]


def _limpiar_nombre(s: str, max_len: int) -> str:
    s = reglas.sin_acentos(s)
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", s)
    s = re.sub(r"[^\w .,()&'-]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rsplit(" ", 1)[0].strip(" .,")
        # no terminar en conectores ("…Iberoamericano de")
        while True:
            corto = re.sub(r"\s+(de|del|la|las|el|los|en|y|e|que|por|para|a|al|con)$", "", s, flags=re.IGNORECASE)
            if corto == s:
                break
            s = corto.strip(" .,")
    return s


EVENTO_GENERICO = re.compile(r"^(curso|conferencia|taller|diplomado)( de formaci[oó]n docente)?$", re.IGNORECASE)


def _descriptor(campos: dict) -> str:
    evento = (campos.get("evento") or "").strip()
    titulo = (campos.get("titulo") or "").strip()
    if campos.get("tipo_documento") == "Reporte de revisión":
        return f"Reporte {evento}".strip()
    sigla = re.search(r"\(([^()]{2,25})\)\s*$", evento)
    if sigla and not re.search(r"\b(oral|virtual|presencial)\b", sigla.group(1), re.IGNORECASE):
        return sigla.group(1)
    if titulo and (not evento or EVENTO_GENERICO.match(reglas.sin_acentos(evento))):
        return titulo
    return evento or titulo or campos.get("institucion") or "Documento"


def nombre_nuevo(campos: dict, ext: str) -> str:
    fecha = campos.get("fecha") or "SinFecha"
    if not campos.get("mi_nombre_presente"):
        cat = "SinMiNombre"
    else:
        cat = CATEGORIA_CORTA.get(campos.get("categoria", ""), "Otro")
    partes = [fecha, cat, _limpiar_nombre(_descriptor(campos), 70)]
    if campos.get("categoria") == "Coautoría" or not campos.get("mi_nombre_presente"):
        tit = _limpiar_nombre(campos.get("titular", ""), 30)
        if tit:
            partes.append(tit)
    return "_".join(p for p in partes if p) + ext.lower()


def _anio(campos: dict) -> str:
    f = campos.get("fecha") or ""
    return f[:4] if FECHA_RE.match(f) else "SinFecha"


def _destino_libre(carpeta: str, nombre: str, propio: str = "") -> str:
    base, ext = os.path.splitext(nombre)
    ruta = os.path.join(carpeta, nombre)
    n = 2
    while os.path.exists(ruta) and os.path.abspath(ruta) != os.path.abspath(propio or ""):
        ruta = os.path.join(carpeta, f"{base} ({n}){ext}")
        n += 1
    return ruta


PLACEHOLDER_RE = re.compile(r"^(n/?a|ninguno|ninguna|no aplica|desconocid[oa]|sin (?:t[ií]tulo|fecha|datos)|"
                            r"(?:t[ií]tulo |fecha |lugar |instituci[oó]n )?no (?:especificad[oa]|disponible|indicad[oa])|-+)\.?$",
                            re.IGNORECASE)


def quitar_mencion_propia(resumen: str, nombre: str) -> str:
    """Elimina frases del resumen que atribuyen participación al usuario cuando no aparece."""
    apellidos = [p for p in reglas.normalizar(nombre).split()[1:] if len(p) > 3]
    protegido = re.sub(r"\b(Dr|Dra|Mtro|Mtra|Lic|C|D|Ing)\.", r"\1§", resumen)
    frases = re.split(r"(?<=[.;])\s+", protegido)
    limpias = [f for f in frases if not any(a in reglas.normalizar(f) for a in apellidos)]
    texto = " ".join(limpias).replace("§", ".").strip().rstrip(";,") or resumen
    if not texto.endswith("."):
        texto += "."
    return f"{texto} El nombre de {nombre} no aparece en este documento."


def combinar(llm: dict | None, rg: dict, nombre_usuario: str = "") -> tuple[dict, str, list[str]]:
    """Une la salida del LLM con las reglas. Devuelve (campos, confianza, avisos)."""
    avisos = []
    if not llm:
        conf = "media" if rg.get("fecha") and rg["categoria"] != "Otro" else "revisar"
        return dict(rg), conf, ["Clasificado solo con reglas"]

    c = {k: (llm.get(k) if llm.get(k) not in (None,) else "") for k in rg}
    for k, v in c.items():
        if isinstance(v, str):
            c[k] = v.strip()
        if isinstance(v, str) and (PLACEHOLDER_RE.match(v.strip()) or reglas.es_lema(v)):
            c[k] = ""
    c["horas"] = re.sub(r"[^\d.]", "", str(c.get("horas", ""))) or rg.get("horas", "")

    # Tipo y categoría: las reglas (palabras clave explícitas) mandan cuando encontraron algo;
    # el modelo decide solo en los casos que las reglas no cubren.
    llm_cat, llm_tipo = c.get("categoria"), c.get("tipo_documento")
    if rg["tipo_documento"] != "Otro" or llm_tipo not in TIPOS:
        c["tipo_documento"] = rg["tipo_documento"]
    if rg["categoria"] != "Otro" or llm_cat not in CATEGORIAS:
        c["categoria"] = rg["categoria"]
    if llm_cat in CATEGORIAS and llm_cat != c["categoria"]:
        avisos.append(f"El modelo sugería la categoría '{llm_cat}'")

    # Revistas conocidas: el nombre exacto de la revista es más fiable por reglas
    if rg.get("evento") in reglas.REVISTAS:
        c["evento"] = rg["evento"]
        c["institucion"] = rg.get("institucion") or c.get("institucion", "")

    # La detección del nombre por reglas (difusa) es más confiable que el LLM
    c["mi_nombre_presente"] = bool(rg["mi_nombre_presente"])
    if not c["mi_nombre_presente"]:
        if llm.get("mi_nombre_presente"):
            avisos.append("El modelo creyó ver tu nombre, pero no se encontró en el texto")
        c["categoria"] = "Otro"
        c["resumen"] = quitar_mencion_propia(c.get("resumen", ""), nombre_usuario)

    # Fecha: validar formato y contrastar con las fechas encontradas por reglas
    fechas_texto = {f.isoformat() for f in reglas.encontrar_fechas(llm.get("_texto", "") or "")}
    if not FECHA_RE.match(c.get("fecha") or ""):
        if c.get("fecha"):
            avisos.append(f"Fecha del modelo no válida ({c['fecha']}); se usó la de reglas")
        c["fecha"] = rg["fecha"]
    elif rg.get("fecha") and len(rg["fecha"]) == 10 and c["fecha"] != rg["fecha"] and c["fecha"] not in fechas_texto:
        avisos.append(f"Fecha del modelo ({c['fecha']}) no aparece en el texto; se usó {rg['fecha']}")
        c["fecha"] = rg["fecha"]

    for k in ("institucion", "evento", "titulo", "horas"):
        if not c.get(k) and rg.get(k):
            c[k] = rg[k]
    if not c.get("resumen"):
        c["resumen"] = rg["resumen"]

    # Confianza: ¿coinciden modelo y reglas en la categoría y en la fecha?
    acuerdos = int(llm_cat == c["categoria"] or not c["mi_nombre_presente"]) + int(
        bool(c["fecha"]) and str(llm.get("fecha", "")).strip() == c["fecha"])
    conf = {2: "alta", 1: "media", 0: "revisar"}[acuerdos]
    if not c["fecha"] or (c["mi_nombre_presente"] and c["categoria"] == "Otro"):
        conf = "revisar"
    return c, conf, avisos


class Procesador:
    def __init__(self, cfg: Config, memoria: Memoria, log: Log = print):
        self.cfg = cfg
        self.memoria = memoria
        self.log = log
        self.cliente = ClienteOllama(cfg.ollama_url, cfg.modelo) if cfg.usar_llm else None
        self._llm_ok = None

    def llm_listo(self) -> bool:
        if not self.cliente:
            return False
        if self._llm_ok is None:
            ok, msg = self.cliente.disponible()
            self._llm_ok = ok
            if not ok:
                self.log(f"  [!] {msg}. Se usará solo el algoritmo de reglas.")
        return self._llm_ok

    # -------------------------------------------------------------- clasificación
    def clasificar_texto(self, texto: str, nombre_archivo: str, excluir: set[str] | None = None) -> tuple[dict, str, str, list[str]]:
        rg = reglas.clasificar(texto, self.cfg.mi_nombre, nombre_archivo, self.cfg.nombre_completo)
        llm_out, metodo = None, "reglas"
        if self.llm_listo():
            ejemplos = self.memoria.similares(texto, self.cfg.ejemplos_few_shot, excluir=excluir)
            try:
                llm_out = self.cliente.clasificar(texto, nombre_archivo, self.cfg.mi_nombre,
                                                  self.cfg.nombre_completo, ejemplos)
                llm_out["_texto"] = texto
                metodo = f"{self.cfg.modelo} ({len(ejemplos)} ejemplos)"
            except Exception as e:  # noqa: BLE001 — cualquier fallo del LLM cae a reglas
                self.log(f"  [!] Falló el modelo ({e}); se usan reglas.")
        campos, conf, avisos = combinar(llm_out, rg, self.cfg.nombre_completo)
        return campos, conf, metodo, avisos

    # -------------------------------------------------------------- archivo
    def procesar_archivo(self, ruta: str, destino: str, reprocesar: bool = False) -> dict | None:
        nombre = os.path.basename(ruta)
        doc_id = hash_archivo(ruta)
        reg = self.memoria.get(doc_id)
        t0 = time.time()

        if reg and (not reprocesar or reg.get("verificado")):
            self.log(f"  Ya está en memoria{' (verificado)' if reg.get('verificado') else ''}: se reutiliza la clasificación.")
        else:
            texto = reg["texto"] if reg and reg.get("texto") else None
            metodo_texto = reg.get("metodo_texto", "") if reg else ""
            if not texto:
                texto, metodo_texto = extraer_texto(ruta)
                self.log(f"  Texto extraído ({metodo_texto}, {len(texto)} caracteres)")
            if not texto.strip():
                self.log("  [X] No se pudo leer texto del archivo.")
            campos, conf, metodo, avisos = self.clasificar_texto(texto, nombre, excluir={doc_id})
            reg = {
                "id": doc_id,
                "archivo_original": nombre,
                "ruta_origen": os.path.abspath(ruta),
                "texto": texto,
                "metodo_texto": metodo_texto,
                "campos": campos,
                "metodo": metodo,
                "confianza": conf,
                "avisos": avisos,
                "verificado": False,
                "procesado": datetime.now().isoformat(timespec="seconds"),
            }
            anterior = self.memoria.get(doc_id)
            if anterior and anterior.get("ruta_destino"):
                reg["ruta_destino"] = anterior["ruta_destino"]

        if destino:
            self._copiar(reg, ruta, destino)
        reg["posible_duplicado"] = self.memoria.buscar_duplicado(reg)
        self.memoria.upsert(reg)
        c = reg["campos"]
        self.log(f"  → {c.get('categoria')} | {c.get('fecha') or 'sin fecha'} | {c.get('evento') or c.get('titulo') or '-'}")
        self.log(f"  → {reg.get('archivo_nuevo', '')}  [{reg.get('confianza')}, {time.time() - t0:.1f}s]")
        for a in reg.get("avisos", []):
            self.log(f"    · {a}")
        if reg["posible_duplicado"]:
            self.log(f"    · Posible duplicado de: {reg['posible_duplicado']}")
        return reg

    def _copiar(self, reg: dict, ruta: str, destino: str) -> None:
        c = reg["campos"]
        ext = os.path.splitext(ruta)[1]
        cat = CATEGORIA_CORTA.get(c.get("categoria", ""), "Otro") if c.get("mi_nombre_presente") else "SinMiNombre"
        carpeta = os.path.join(destino, _anio(c), cat)
        os.makedirs(carpeta, exist_ok=True)
        anterior = reg.get("ruta_destino", "")
        if anterior and not os.path.abspath(anterior).startswith(os.path.abspath(destino) + os.sep):
            anterior = ""  # la copia previa está en otro destino: no tocarla
        objetivo = _destino_libre(carpeta, nombre_nuevo(c, ext), propio=anterior)
        if anterior and os.path.exists(anterior) and os.path.abspath(anterior) != os.path.abspath(objetivo):
            shutil.move(anterior, objetivo)  # reclasificado: mover la copia previa
        elif not os.path.exists(objetivo):
            if self.cfg.copiar_en_vez_de_mover:
                shutil.copy2(ruta, objetivo)
            else:
                shutil.move(ruta, objetivo)
                reg["ruta_origen"] = objetivo
        reg["archivo_nuevo"] = os.path.basename(objetivo)
        reg["ruta_destino"] = os.path.abspath(objetivo)

    def reubicar(self, reg: dict, destino: str) -> None:
        """Tras una corrección manual, renombra/mueve la copia ya organizada."""
        fuente = reg.get("ruta_destino") or reg.get("ruta_origen")
        if destino and fuente and os.path.exists(fuente):
            self._copiar(reg, fuente, destino)
            self.memoria.upsert(reg)

    def procesar_rutas(self, rutas: list[str], destino: str, reprocesar: bool = False,
                       progreso: Callable[[int, int], None] | None = None,
                       cancelado: Callable[[], bool] | None = None) -> list[dict]:
        archivos = []
        for r in rutas:
            if os.path.isdir(r):
                for raiz, _dirs, files in os.walk(r):
                    if destino and os.path.abspath(raiz).startswith(os.path.abspath(destino)):
                        continue
                    archivos += [os.path.join(raiz, f) for f in sorted(files) if f.lower().endswith(EXTENSIONES)]
            elif r.lower().endswith(EXTENSIONES):
                archivos.append(r)
        resultados = []
        for i, ruta in enumerate(archivos, 1):
            if cancelado and cancelado():
                self.log("Proceso cancelado.")
                break
            self.log(f"[{i}/{len(archivos)}] {os.path.basename(ruta)}")
            try:
                reg = self.procesar_archivo(ruta, destino, reprocesar)
                if reg:
                    resultados.append(reg)
            except Exception as e:  # noqa: BLE001 — un archivo malo no detiene el lote
                self.log(f"  [X] Error: {e}")
            self.memoria.guardar()
            if progreso:
                progreso(i, len(archivos))
        return resultados
