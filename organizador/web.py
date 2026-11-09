"""Interfaz web local (solo 127.0.0.1). Sin dependencias externas: http.server de la biblioteca estándar."""
import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import APP_DIR, CATEGORIAS, CONFIG_PATH, DATOS_DIR, EXTENSIONES, MEMORIA_PATH, TIPOS, Config
from . import duplicados
from .excel import exportar
from .extraccion import hash_archivo
from .llm import ClienteOllama
from .memoria import Memoria
from .procesador import FECHA_RE, Procesador
from .word import Filtros, generar_word, nombre_archivo_informe

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
NOMBRE_EXCEL = "Productividad_academica.xlsx"
MAX_SUBIDA = 60 * 1024 * 1024


class Estado:
    """Estado compartido entre el servidor y el hilo de trabajo."""

    def __init__(self):
        self.cfg = Config.cargar(CONFIG_PATH)
        if not self.cfg.carpeta_origen and os.path.isdir(os.path.join(APP_DIR, "Docs")):
            self.cfg.carpeta_origen = os.path.join(APP_DIR, "Docs")
        if not self.cfg.carpeta_destino:
            self.cfg.carpeta_destino = os.path.join(APP_DIR, "Docs clasificados")
        self.memoria = Memoria(MEMORIA_PATH)
        try:
            self.memoria.respaldo_diario(os.path.join(DATOS_DIR, "respaldos"))
        except OSError:
            pass
        self.log_lineas: deque = deque(maxlen=2000)
        self.log_total = 0
        self.lock = threading.Lock()
        self.trabajos: queue.Queue = queue.Queue()
        self.trabajando = False
        self.progreso = [0, 0]
        self.cancelar = False
        self.llm = {"ok": False, "msg": "Sin verificar", "modelos": []}
        threading.Thread(target=self._trabajador, daemon=True).start()
        threading.Thread(target=self.verificar_llm, daemon=True).start()

    # ---------------------------------------------------------------- log
    def log(self, msg: str):
        with self.lock:
            self.log_lineas.append(msg)
            self.log_total += 1

    def log_desde(self, n: int) -> tuple[list[str], int]:
        with self.lock:
            total = self.log_total
            nuevos = min(total - n, len(self.log_lineas)) if n < total else 0
            return list(self.log_lineas)[-nuevos:] if nuevos > 0 else [], total

    # ---------------------------------------------------------------- llm
    def verificar_llm(self):
        if not self.cfg.usar_llm:
            self.llm = {"ok": False, "msg": "Solo reglas (Qwen desactivado)", "modelos": []}
            return
        c = ClienteOllama(self.cfg.ollama_url, self.cfg.modelo)
        ok, msg = c.disponible()
        self.llm = {"ok": ok, "msg": f"{self.cfg.modelo} listo" if ok else msg, "modelos": c.modelos()}

    # ---------------------------------------------------------------- trabajos
    def encolar(self, rutas: list[str], reprocesar: bool = False):
        self.trabajos.put((rutas, reprocesar))

    def _trabajador(self):
        while True:
            rutas, reprocesar = self.trabajos.get()
            self.trabajando, self.cancelar = True, False
            try:
                proc = Procesador(self.cfg, self.memoria, log=self.log)
                res = proc.procesar_rutas(rutas, self.cfg.carpeta_destino, reprocesar=reprocesar,
                                          progreso=self._progreso, cancelado=lambda: self.cancelar)
                revisar = sum(1 for r in res if r.get("confianza") == "revisar" and not r.get("verificado"))
                self.exportar_excel()
                self.log(f"--- Terminado: {len(res)} documento(s); {revisar} para revisar. Excel actualizado. ---")
            except Exception as e:  # noqa: BLE001
                self.log(f"[X] Error: {e}")
            finally:
                if self.trabajos.empty():
                    self.trabajando = False

    def _progreso(self, i, n):
        self.progreso = [i, n]

    def exportar_excel(self) -> str:
        os.makedirs(self.cfg.carpeta_destino, exist_ok=True)
        ruta = os.path.join(self.cfg.carpeta_destino, NOMBRE_EXCEL)
        try:
            return exportar(self.memoria.lista(), ruta, self.cfg.nombre_completo)
        except PermissionError:
            alterna = os.path.join(self.cfg.carpeta_destino, "Productividad_academica (copia).xlsx")
            self.log("[!] El Excel está abierto; se guardó una copia: " + os.path.basename(alterna))
            return exportar(self.memoria.lista(), alterna, self.cfg.nombre_completo)

    def carpeta_entrada(self) -> str:
        d = self.cfg.carpeta_origen or os.path.join(DATOS_DIR, "entrada")
        os.makedirs(d, exist_ok=True)
        return d


def _publico(reg: dict) -> dict:
    r = {k: v for k, v in reg.items() if k != "texto"}
    r["tiene_texto"] = bool(reg.get("texto"))
    return r


def _abrir_en_sistema(ruta: str):
    if sys.platform.startswith("win"):
        os.startfile(ruta)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", ruta])
    else:
        subprocess.Popen(["xdg-open", ruta])


def crear_handler(estado: Estado, puerto: int):
    hosts_validos = {f"127.0.0.1:{puerto}", f"localhost:{puerto}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "Clasificador/2.0"

        def log_message(self, fmt, *args):  # silencio en consola
            pass

        # ------------------------------------------------------------ helpers
        def _host_ok(self) -> bool:
            if self.headers.get("Host") not in hosts_validos:
                self.send_error(HTTPStatus.FORBIDDEN)
                return False
            return True

        def _json(self, data, status=200):
            cuerpo = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _archivo(self, ruta: str, descarga: str | None = None):
            tipo = mimetypes.guess_type(ruta)[0] or "application/octet-stream"
            with open(ruta, "rb") as f:
                datos = f.read()
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(datos)))
            if descarga:
                self.send_header("Content-Disposition",
                                 f"attachment; filename*=UTF-8''{urllib.parse.quote(descarga)}")
            self.end_headers()
            self.wfile.write(datos)

        def _cuerpo_json(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        # ------------------------------------------------------------ GET
        def do_GET(self):
            if not self._host_ok():
                return
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            ruta = url.path
            if ruta in ("/", "/index.html"):
                return self._archivo(os.path.join(STATIC_DIR, "index.html"))
            if ruta == "/api/estado":
                lineas, total = estado.log_desde(int(q.get("desde", ["0"])[0]))
                c = estado.cfg
                return self._json({
                    "trabajando": estado.trabajando or not estado.trabajos.empty(),
                    "progreso": estado.progreso, "log": lineas, "log_total": total, "llm": estado.llm,
                    "config": {"carpeta_origen": c.carpeta_origen, "carpeta_destino": c.carpeta_destino,
                               "usar_llm": c.usar_llm, "modelo": c.modelo, "mi_nombre": c.mi_nombre,
                               "grado": c.grado},
                    "categorias": CATEGORIAS, "tipos": TIPOS,
                })
            if ruta == "/api/documentos":
                regs = estado.memoria.lista()
                return self._json({"documentos": [_publico(r) for r in regs],
                                   "duplicados": duplicados.grupos(regs)})
            if ruta == "/api/respaldo":
                from datetime import datetime
                datos = estado.memoria.exportar_json()
                nombre = f"respaldo_memoria_{datetime.now():%Y-%m-%d_%H%M}.json"
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.send_header("Content-Disposition", f"attachment; filename={nombre}")
                self.end_headers()
                self.wfile.write(datos)
                return
            if ruta == "/api/word":
                f = Filtros.desde_dict({
                    "anios": [a for a in q.get("anios", [""])[0].split(",") if a],
                    "categorias": [c for c in q.get("categorias", [""])[0].split("|") if c],
                    "solo_verificados": q.get("solo_verificados", ["0"])[0] == "1",
                    "incluir_anexo": q.get("anexo", ["1"])[0] == "1",
                    "incluir_sin_mi_nombre": q.get("sin_mi_nombre", ["0"])[0] == "1",
                    "texto": q.get("texto", [""])[0],
                })
                carpeta = os.path.join(estado.cfg.carpeta_destino, "Informes")
                os.makedirs(carpeta, exist_ok=True)
                destino = os.path.join(carpeta, nombre_archivo_informe(f))
                try:
                    res = generar_word(estado.memoria.lista(), destino, estado.cfg.nombre_completo, f)
                except PermissionError:
                    return self._json({"error": "Cierre el informe en Word para poder regenerarlo."}, 409)
                estado.log(f"Informe Word ({res['documentos']} actividades, {res['periodo']}): {destino}")
                return self._archivo(destino, descarga=os.path.basename(destino))
            if ruta == "/api/excel":
                archivo = estado.exportar_excel()
                return self._archivo(archivo, descarga=os.path.basename(archivo))
            m = re.match(r"^/api/archivo/([0-9a-f]{64})$", ruta)
            if m:
                reg = estado.memoria.get(m.group(1))
                for p in ((reg or {}).get("ruta_destino"), (reg or {}).get("ruta_origen")):
                    if p and os.path.exists(p):
                        return self._archivo(p)
                return self.send_error(HTTPStatus.NOT_FOUND)
            self.send_error(HTTPStatus.NOT_FOUND)

        # ------------------------------------------------------------ POST
        def do_POST(self):
            if not self._host_ok():
                return
            url = urllib.parse.urlparse(self.path)
            ruta = url.path
            try:
                if ruta == "/api/subir":
                    return self._subir(urllib.parse.parse_qs(url.query))
                if ruta == "/api/respaldo/fusionar":
                    n = int(self.headers.get("Content-Length") or 0)
                    if n <= 0 or n > MAX_SUBIDA:
                        return self._json({"error": "Archivo vacío o demasiado grande"}, 400)
                    res = estado.memoria.fusionar(json.loads(self.rfile.read(n).decode("utf-8")))
                    estado.memoria.guardar()
                    estado.exportar_excel()
                    estado.log(f"Respaldo fusionado: {res['agregados']} agregados, {res['actualizados']} "
                               f"actualizados, {res['sin_cambio']} ya existían.")
                    return self._json({"ok": True, **res})
                datos = self._cuerpo_json()
                if ruta == "/api/procesar":
                    origen = estado.cfg.carpeta_origen
                    if not origen or not os.path.isdir(origen):
                        return self._json({"error": "La carpeta de origen no existe."}, 400)
                    estado.encolar([origen], bool(datos.get("reprocesar")))
                    return self._json({"ok": True})
                if ruta == "/api/cancelar":
                    estado.cancelar = True
                    return self._json({"ok": True})
                if ruta == "/api/config":
                    return self._config(datos)
                if ruta == "/api/verificar":
                    return self._verificar(datos)
                if ruta == "/api/reclasificar":
                    reg = estado.memoria.get(datos.get("id", ""))
                    if not reg:
                        return self._json({"error": "No existe"}, 404)
                    fuente = next((p for p in (reg.get("ruta_origen"), reg.get("ruta_destino"))
                                   if p and os.path.exists(p)), None)
                    if not fuente:
                        return self._json({"error": "No se encontró el archivo en disco."}, 400)
                    reg["verificado"] = False
                    estado.encolar([fuente], reprocesar=True)
                    return self._json({"ok": True})
                if ruta == "/api/duplicados/resolver":
                    return self._resolver_duplicados(datos)
                if ruta == "/api/duplicados/no-son":
                    ids = [i for i in datos.get("ids", []) if estado.memoria.get(i)]
                    for i in ids:
                        r = estado.memoria.get(i)
                        r["no_duplicado"] = sorted(set(r.get("no_duplicado") or []) | (set(ids) - {i}))
                    estado.memoria.guardar()
                    estado.exportar_excel()
                    estado.log(f"Marcados como NO duplicados: {len(ids)} documentos.")
                    return self._json({"ok": True})
                if ruta == "/api/duplicados/restaurar":
                    reg = estado.memoria.get(datos.get("id", ""))
                    if not reg:
                        return self._json({"error": "No existe"}, 404)
                    reg["descartado"] = False
                    reg.pop("duplicado_de", None)
                    Procesador(estado.cfg, estado.memoria, log=estado.log).reubicar(reg, estado.cfg.carpeta_destino)
                    estado.memoria.guardar()
                    estado.exportar_excel()
                    estado.log(f"Restaurado: {reg.get('archivo_nuevo')}")
                    return self._json({"ok": True})
                if ruta == "/api/quitar":
                    estado.memoria.eliminar(datos.get("id", ""))
                    estado.memoria.guardar()
                    return self._json({"ok": True})
                if ruta == "/api/abrir":
                    destino = estado.cfg.carpeta_destino
                    if datos.get("id"):
                        reg = estado.memoria.get(datos["id"]) or {}
                        destino = next((p for p in (reg.get("ruta_destino"), reg.get("ruta_origen"))
                                        if p and os.path.exists(p)), "")
                    elif datos.get("que") == "excel":
                        destino = estado.exportar_excel()
                    if destino and os.path.exists(destino):
                        _abrir_en_sistema(destino)
                        return self._json({"ok": True})
                    return self._json({"error": "No existe"}, 404)
            except (ValueError, KeyError, OSError) as e:
                return self._json({"error": str(e)}, 400)
            self.send_error(HTTPStatus.NOT_FOUND)

        def _subir(self, q):
            nombre = os.path.basename(q.get("nombre", [""])[0]).strip()
            if not nombre.lower().endswith(EXTENSIONES):
                return self._json({"error": f"Tipo de archivo no soportado: {nombre}"}, 400)
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_SUBIDA:
                return self._json({"error": "Archivo vacío o demasiado grande"}, 400)
            datos = self.rfile.read(n)
            carpeta = estado.carpeta_entrada()
            destino = os.path.join(carpeta, nombre)
            base, ext = os.path.splitext(nombre)
            k = 2
            while os.path.exists(destino):
                with open(destino, "rb") as f:
                    if f.read() == datos:
                        break  # mismo archivo ya existe
                destino = os.path.join(carpeta, f"{base} ({k}){ext}")
                k += 1
            if not os.path.exists(destino):
                with open(destino, "wb") as f:
                    f.write(datos)
            ya = estado.memoria.get(hash_archivo(destino))
            estado.log(f"Recibido: {nombre}" + (" (ya estaba en memoria)" if ya else ""))
            estado.encolar([destino])
            return self._json({"ok": True, "ruta": destino, "duplicado": bool(ya)})

        def _config(self, d):
            c = estado.cfg
            for k in ("carpeta_origen", "carpeta_destino", "modelo", "mi_nombre", "grado"):
                if k in d and isinstance(d[k], str) and d[k].strip():
                    setattr(c, k, d[k].strip())
            if "usar_llm" in d:
                c.usar_llm = bool(d["usar_llm"])
            c.guardar(CONFIG_PATH)
            threading.Thread(target=estado.verificar_llm, daemon=True).start()
            return self._json({"ok": True})

        def _resolver_duplicados(self, d):
            conservar = estado.memoria.get(d.get("conservar", ""))
            if not conservar:
                return self._json({"error": "Documento a conservar no existe"}, 404)
            proc = Procesador(estado.cfg, estado.memoria, log=estado.log)
            conservar["descartado"] = False
            conservar.pop("duplicado_de", None)
            n = 0
            for i in d.get("descartar", []):
                r = estado.memoria.get(i)
                if not r or i == conservar["id"]:
                    continue
                r["descartado"] = True
                r["duplicado_de"] = conservar["id"]
                proc.mover_a_duplicados(r, estado.cfg.carpeta_destino)
                estado.memoria.upsert(r)
                n += 1
            proc.reubicar(conservar, estado.cfg.carpeta_destino)
            estado.memoria.guardar()
            estado.exportar_excel()
            estado.log(f"Duplicados resueltos: se conserva «{conservar.get('archivo_nuevo')}», {n} descartado(s) "
                       "(movidos a _Duplicados; no se borró nada).")
            return self._json({"ok": True, "descartados": n})

        def _verificar(self, d):
            reg = estado.memoria.get(d.get("id", ""))
            if not reg:
                return self._json({"error": "No existe"}, 404)
            campos = {k: str(v).strip() for k, v in (d.get("campos") or {}).items()
                      if k in reg["campos"] and k != "mi_nombre_presente"}
            campos["mi_nombre_presente"] = bool((d.get("campos") or {}).get("mi_nombre_presente"))
            if campos.get("fecha") and not FECHA_RE.match(campos["fecha"]):
                return self._json({"error": "Fecha inválida: use AAAA-MM-DD"}, 400)
            if campos.get("categoria") and campos["categoria"] not in CATEGORIAS:
                return self._json({"error": "Categoría inválida"}, 400)
            reg = estado.memoria.verificar(reg["id"], campos)
            reg["confianza"], reg["avisos"] = "verificado", []
            Procesador(estado.cfg, estado.memoria, log=estado.log).reubicar(reg, estado.cfg.carpeta_destino)
            estado.memoria.guardar()
            estado.exportar_excel()
            estado.log(f"Verificado: {reg.get('archivo_nuevo')}")
            return self._json({"ok": True, "documento": _publico(reg)})

    return Handler


def servir(puerto: int = 8765, abrir: bool = True):
    estado = Estado()
    servidor = None
    for p in range(puerto, puerto + 20):
        try:
            servidor = ThreadingHTTPServer(("127.0.0.1", p), crear_handler(estado, p))
            puerto = p
            break
        except OSError:
            continue
    if servidor is None:
        raise SystemExit("No hay puertos libres entre 8765 y 8784")
    url = f"http://127.0.0.1:{puerto}/"
    print(f"Clasificador de constancias en {url}  (Ctrl+C para salir)")
    if abrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando…")
    finally:
        estado.memoria.guardar()
        servidor.server_close()
