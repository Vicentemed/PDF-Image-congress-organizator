"""Clasificación con Qwen local vía Ollama (salida JSON con esquema estricto)."""
import json
import urllib.error
import urllib.request

from .config import CATEGORIAS, DESCRIPCION_CATEGORIAS, TIPOS

MAX_CHARS_TEXTO = 3500

ESQUEMA = {
    "type": "object",
    "properties": {
        "tipo_documento": {"type": "string", "enum": TIPOS},
        "categoria": {"type": "string", "enum": CATEGORIAS},
        "titular": {"type": "string"},
        "mi_nombre_presente": {"type": "boolean"},
        "fecha": {"type": "string"},
        "fecha_evento": {"type": "string"},
        "institucion": {"type": "string"},
        "evento": {"type": "string"},
        "titulo": {"type": "string"},
        "lugar": {"type": "string"},
        "horas": {"type": "string"},
        "resumen": {"type": "string"},
    },
    "required": ["tipo_documento", "categoria", "titular", "mi_nombre_presente", "fecha",
                 "fecha_evento", "institucion", "evento", "titulo", "lugar", "horas", "resumen"],
}


def _system_prompt(mi_nombre: str, nombre_completo: str) -> str:
    cats = "\n".join(f"- {k}: {v}" for k, v in DESCRIPCION_CATEGORIAS.items())
    return f"""Eres un asistente que clasifica constancias, reconocimientos y certificados académicos de {mi_nombre}.
Recibirás el texto de un documento (a veces de OCR: puede venir sin espacios, sin acentos o desordenado).
Devuelve SOLO un JSON con estos campos:

- tipo_documento: forma del documento, uno de {TIPOS}.
- categoria: actividad que acredita a {mi_nombre}, una de:
{cats}
- titular: persona a quien se otorga el documento (nombre bien escrito, con acentos).
- mi_nombre_presente: true si "{mi_nombre}" aparece (con cualquier variación u error de OCR), si no false.
  Si es false, la categoria debe ser "Otro".
- fecha: fecha de expedición en formato AAAA-MM-DD (si solo hay fechas del evento, usa el último día del evento).
  Si no hay día usa AAAA-MM, si solo hay año AAAA, y si no hay fecha deja "". No uses años de citas bibliográficas.
- fecha_evento: fechas del evento tal como se describen (ej. "19 al 21 de febrero de 2025"), o "".
- institucion: institución(es) que otorgan el documento, nombre completo y bien escrito (puede incluir la dependencia).
- evento: nombre del congreso, encuentro, curso, convocatoria o revista. Para revisiones, el nombre de la revista.
- titulo: título de la ponencia, tema, curso o manuscrito; "" si no hay.
- lugar: ciudad y estado (ej. "Aguascalientes, Ags."), o "".
- horas: número de horas acreditadas, o "".
- resumen: 1 o 2 oraciones en español formal, en tercera persona, para un informe institucional de productividad.
  Empieza con el tipo de documento e incluye quién lo otorga, a quién ({nombre_completo}), por qué actividad, evento y fecha.
  Si el usuario es coautor, menciona al titular y que {nombre_completo} figura como coautor.
Los lemas institucionales ("Por mi raza hablará el espíritu", "Se Lumen Proferre") NO son títulos ni eventos.
Si un dato no aparece, usa "" (nunca "No especificado").
Corrige errores evidentes de OCR (espacios, acentos, letras cambiadas). No inventes datos que no estén en el texto."""


def _mensaje_usuario(texto: str, nombre_archivo: str) -> str:
    return f"Archivo: {nombre_archivo}\nTexto del documento:\n\"\"\"\n{texto[:MAX_CHARS_TEXTO]}\n\"\"\""


def _campos_ejemplo(campos: dict) -> str:
    return json.dumps({k: campos.get(k, "") for k in ESQUEMA["properties"]}, ensure_ascii=False)


class ClienteOllama:
    def __init__(self, url: str, modelo: str, timeout: int = 180):
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout

    def disponible(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                modelos = [m["name"] for m in json.load(r).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError) as e:
            return False, f"Ollama no responde en {self.url} ({e})"
        if self.modelo not in modelos:
            return False, f"El modelo '{self.modelo}' no está instalado. Disponibles: {', '.join(modelos) or 'ninguno'}"
        return True, "ok"

    def modelos(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                return [m["name"] for m in json.load(r).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return []

    def clasificar(self, texto: str, nombre_archivo: str, mi_nombre: str, nombre_completo: str,
                   ejemplos: list[dict]) -> dict:
        mensajes = [{"role": "system", "content": _system_prompt(mi_nombre, nombre_completo)}]
        for ej in ejemplos:
            mensajes.append({"role": "user", "content": _mensaje_usuario(ej["texto"], ej.get("archivo_original", ""))})
            mensajes.append({"role": "assistant", "content": _campos_ejemplo(ej["campos"])})
        mensajes.append({"role": "user", "content": _mensaje_usuario(texto, nombre_archivo)})
        cuerpo = {
            "model": self.modelo,
            "messages": mensajes,
            "stream": False,
            "format": ESQUEMA,
            "options": {"temperature": 0, "num_ctx": 12288},
            "keep_alive": "15m",
        }
        req = urllib.request.Request(f"{self.url}/api/chat", data=json.dumps(cuerpo).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            respuesta = json.load(r)
        contenido = respuesta["message"]["content"]
        datos = json.loads(contenido)
        return {k: datos.get(k, "") for k in ESQUEMA["properties"]}
