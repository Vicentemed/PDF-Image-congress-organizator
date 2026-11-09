"""Memoria persistente en JSON.

Cada documento procesado queda registrado (por hash SHA-256) con su texto, los
campos extraídos, el resumen y si fue verificado por el usuario. Los registros
verificados funcionan como "entrenamiento": se usan como ejemplos (few-shot)
para que Qwen clasifique los documentos nuevos con el mismo criterio.
"""
import json
import math
import os
import re
import shutil
import threading
from collections import Counter
from datetime import datetime

from .reglas import normalizar

VERSION = 1
MAX_TEXTO = 6000


class Memoria:
    def __init__(self, ruta: str):
        self.ruta = ruta
        self._lock = threading.RLock()
        self.documentos: dict[str, dict] = {}
        self.cargar()

    # ------------------------------------------------------------ persistencia
    def cargar(self) -> None:
        if not os.path.exists(self.ruta):
            return
        with open(self.ruta, encoding="utf-8") as f:
            data = json.load(f)
        self.documentos = {d["id"]: d for d in data.get("documentos", [])}

    def guardar(self) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self.ruta) or ".", exist_ok=True)
            tmp = self.ruta + ".tmp"
            data = {
                "version": VERSION,
                "actualizado": datetime.now().isoformat(timespec="seconds"),
                "documentos": sorted(self.documentos.values(), key=lambda d: d.get("campos", {}).get("fecha", "")),
            }
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.exists(self.ruta):
                shutil.copy2(self.ruta, self.ruta + ".bak")
            os.replace(tmp, self.ruta)

    # ------------------------------------------------------------ respaldos
    def exportar_json(self) -> bytes:
        """Contenido completo de la memoria (para descargar como respaldo)."""
        with self._lock:
            data = {
                "version": VERSION,
                "tipo": "respaldo-clasificador-constancias",
                "exportado": datetime.now().isoformat(timespec="seconds"),
                "total": len(self.documentos),
                "documentos": sorted(self.documentos.values(), key=lambda d: d.get("campos", {}).get("fecha", "")),
            }
            return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    def fusionar(self, data: dict) -> dict:
        """Agrega los documentos de un respaldo SIN borrar ni sobrescribir lo existente.

        - Documentos nuevos (hash que no existe) → se agregan.
        - Ya existentes → se conservan; solo se adopta la versión del respaldo si allá está
          verificado y aquí no.
        """
        docs = data.get("documentos") if isinstance(data, dict) else None
        if not isinstance(docs, list):
            raise ValueError("El archivo no es un respaldo válido (falta la lista 'documentos').")
        agregados = actualizados = sin_cambio = 0
        with self._lock:
            for d in docs:
                if not isinstance(d, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(d.get("id", ""))) \
                        or not isinstance(d.get("campos"), dict):
                    continue
                actual = self.documentos.get(d["id"])
                if actual is None:
                    self.documentos[d["id"]] = d
                    agregados += 1
                elif d.get("verificado") and not actual.get("verificado"):
                    for k in ("ruta_origen", "ruta_destino", "archivo_nuevo"):
                        d[k] = actual.get(k, d.get(k))  # conservar ubicaciones de esta computadora
                    self.documentos[d["id"]] = d
                    actualizados += 1
                else:
                    sin_cambio += 1
        return {"agregados": agregados, "actualizados": actualizados, "sin_cambio": sin_cambio}

    def respaldo_diario(self, carpeta: str, conservar: int = 15) -> str | None:
        """Copia memoria.json a carpeta/memoria_AAAA-MM-DD.json una vez al día; conserva los últimos N."""
        if not os.path.exists(self.ruta):
            return None
        os.makedirs(carpeta, exist_ok=True)
        destino = os.path.join(carpeta, f"memoria_{datetime.now():%Y-%m-%d}.json")
        if not os.path.exists(destino):
            shutil.copy2(self.ruta, destino)
        archivos = sorted(f for f in os.listdir(carpeta) if re.fullmatch(r"memoria_\d{4}-\d{2}-\d{2}\.json", f))
        for viejo in archivos[:-conservar]:
            os.remove(os.path.join(carpeta, viejo))
        return destino

    # ------------------------------------------------------------ registros
    def get(self, doc_id: str) -> dict | None:
        return self.documentos.get(doc_id)

    def upsert(self, registro: dict) -> None:
        with self._lock:
            registro["texto"] = (registro.get("texto") or "")[:MAX_TEXTO]
            registro.setdefault("creado", datetime.now().isoformat(timespec="seconds"))
            registro["modificado"] = datetime.now().isoformat(timespec="seconds")
            self.documentos[registro["id"]] = registro

    def eliminar(self, doc_id: str) -> None:
        with self._lock:
            self.documentos.pop(doc_id, None)

    def verificar(self, doc_id: str, campos: dict) -> dict:
        """Guarda la corrección del usuario y marca el registro como ejemplo verificado."""
        with self._lock:
            reg = self.documentos[doc_id]
            reg["campos"].update(campos)
            reg["verificado"] = True
            reg["metodo"] = reg.get("metodo", "") if "manual" in reg.get("metodo", "") else (reg.get("metodo", "") + "+manual").lstrip("+")
            self.upsert(reg)
            return reg

    def lista(self) -> list[dict]:
        return sorted(self.documentos.values(),
                      key=lambda d: (d["campos"].get("fecha") or "0000", d.get("archivo_original", "")))

    def verificados(self) -> list[dict]:
        return [d for d in self.documentos.values() if d.get("verificado") and d.get("texto")]

    # ------------------------------------------------------------ similitud
    @staticmethod
    def _tokens(texto: str) -> Counter:
        return Counter(w for w in re.findall(r"[a-z]{4,}", normalizar(texto)))

    def similares(self, texto: str, k: int = 3, excluir: set[str] | None = None) -> list[dict]:
        """k ejemplos verificados más parecidos (coseno TF-IDF), diversificando categorías."""
        candidatos = [d for d in self.verificados() if not excluir or d["id"] not in excluir]
        if not candidatos or k <= 0:
            return []
        docs_tok = [self._tokens(d["texto"]) for d in candidatos]
        n = len(docs_tok)
        df = Counter()
        for tok in docs_tok:
            df.update(tok.keys())
        idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}

        def vec(tok):
            v = {w: (1 + math.log(c)) * idf.get(w, math.log(n + 1) + 1) for w, c in tok.items()}
            norma = math.sqrt(sum(x * x for x in v.values())) or 1.0
            return v, norma

        q, nq = vec(self._tokens(texto))
        puntajes = []
        for d, tok in zip(candidatos, docs_tok):
            v, nv = vec(tok)
            s = sum(q[w] * v[w] for w in q.keys() & v.keys()) / (nq * nv)
            puntajes.append((s, d))
        puntajes.sort(key=lambda x: -x[0])
        elegidos, vistos = [], Counter()
        for s, d in puntajes:
            cat = d["campos"].get("categoria")
            if vistos[cat] >= 2:
                continue
            elegidos.append(d)
            vistos[cat] += 1
            if len(elegidos) >= k:
                break
        return elegidos
