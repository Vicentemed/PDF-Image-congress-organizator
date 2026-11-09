"""Configuración: rutas, nombre del titular, categorías y parámetros del modelo."""
import json
import os
from dataclasses import dataclass, field, asdict

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# CLASIFICADOR_DATOS permite usar otra carpeta de datos (p. ej. para pruebas sin tocar la memoria real)
DATOS_DIR = os.environ.get("CLASIFICADOR_DATOS") or os.path.join(APP_DIR, "datos")
CONFIG_PATH = os.path.join(DATOS_DIR, "config.json")
MEMORIA_PATH = os.path.join(DATOS_DIR, "memoria.json")

EXTENSIONES = (".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

# Tipo de documento (la forma del documento)
TIPOS = [
    "Constancia",
    "Reconocimiento",
    "Certificado",
    "Reporte de revisión",
    "Diploma",
    "Carta",
    "Otro",
]

# Categoría de actividad (lo que se reporta a la institución)
CATEGORIAS = [
    "Ponencia",
    "Coautoría",
    "Evaluador / Revisor",
    "Asistencia",
    "Curso / Formación docente",
    "Comité organizador",
    "Participación institucional",
    "Divulgación",
    "Otro",
]

DESCRIPCION_CATEGORIAS = {
    "Ponencia": "El titular presentó: ponente, conferencista, conferencia magistral, expositor, plática, tema presentado.",
    "Coautoría": "Constancia de ponencia/cartel cuyo titular es OTRA persona (p. ej. un estudiante) y el usuario aparece como coautor en la lista de nombres.",
    "Evaluador / Revisor": "Revisor de manuscritos (reviewer certificate, review report), evaluador de solicitudes, jurado o revisor de concursos.",
    "Asistencia": "Asistió o participó como asistente en un congreso, semana cultural, encuentro, sin presentar trabajo.",
    "Curso / Formación docente": "Acreditó o cursó un curso, taller, diplomado o conferencia de formación docente.",
    "Comité organizador": "Formó parte del comité organizador o coordinó el evento.",
    "Participación institucional": "Comisiones y trabajo institucional: presentación de un posgrado, elaboración de expedientes/planes, comités académicos.",
    "Divulgación": "Entrevistas, programas de radio o televisión, notas de divulgación científica.",
    "Otro": "Cualquier otro caso, o documentos donde el usuario no aparece.",
}

# Abreviaturas para nombres de archivo
CATEGORIA_CORTA = {
    "Ponencia": "Ponencia",
    "Coautoría": "Coautoria",
    "Evaluador / Revisor": "Evaluador",
    "Asistencia": "Asistencia",
    "Curso / Formación docente": "Curso",
    "Comité organizador": "Comite",
    "Participación institucional": "Institucional",
    "Divulgación": "Divulgacion",
    "Otro": "Otro",
}

CAMPOS = [
    "tipo_documento",
    "categoria",
    "titular",
    "mi_nombre_presente",
    "fecha",
    "fecha_evento",
    "institucion",
    "evento",
    "titulo",
    "lugar",
    "horas",
    "resumen",
]


@dataclass
class Config:
    mi_nombre: str = "Vicente Esparza Villalpando"
    grado: str = "Dr."
    usar_llm: bool = True
    modelo: str = "qwen2.5:7b-instruct"
    ollama_url: str = "http://localhost:11434"
    ejemplos_few_shot: int = 3
    carpeta_origen: str = ""
    carpeta_destino: str = ""
    copiar_en_vez_de_mover: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def nombre_completo(self) -> str:
        return f"{self.grado} {self.mi_nombre}".strip()

    @classmethod
    def cargar(cls, ruta: str = CONFIG_PATH) -> "Config":
        if os.path.exists(ruta):
            try:
                with open(ruta, encoding="utf-8") as f:
                    data = json.load(f)
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (OSError, ValueError, TypeError):
                pass
        return cls()

    def guardar(self, ruta: str = CONFIG_PATH) -> None:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
