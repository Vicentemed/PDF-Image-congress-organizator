# Clasificador de Constancias Académicas

Aplicación de escritorio que **identifica, clasifica, renombra y resume** constancias, reconocimientos,
certificados y reportes de revisión (PDF o imagen), y mantiene un **Excel acumulado** listo para los
informes de productividad que pide la institución.

Todo corre **en local**: OCR con RapidOCR y clasificación con **Qwen 2.5 (7B) vía Ollama**, apoyado por
un algoritmo de reglas que funciona incluso sin Ollama.

## Qué extrae de cada documento

| Campo | Ejemplo |
|---|---|
| Tipo de documento | Constancia, Reconocimiento, Certificado, Reporte de revisión… |
| Categoría | Ponencia, Coautoría, Evaluador / Revisor, Asistencia, Curso / Formación docente, Comité organizador, Participación institucional, Divulgación |
| ¿Aparece mi nombre? | Detección tolerante a errores de OCR (`Vilpando`, `VICENTEESPARZA-VILLALPANDO`) |
| Titular | A quién se otorga (en coautorías, el estudiante) |
| Fecha | Fecha de expedición `AAAA-MM-DD` y fechas del evento |
| Institución | Quién otorga el documento |
| Evento | Congreso, jornada, curso, convocatoria o revista |
| Título / tema | Ponencia, curso o manuscrito |
| Lugar, horas | Cuando aparecen |
| Resumen | 1–2 oraciones formales para el informe institucional |

## Cómo funciona

```
archivo ──► texto (PyMuPDF / RapidOCR) ──► reglas ─┐
                                                   ├─► combinación ──► renombrar y copiar ──► memoria.json ──► Excel
            ejemplos verificados ──► Qwen (Ollama) ┘
```

1. **Texto**: si el PDF trae texto se lee directo; si es escaneado o una foto se aplica OCR (también funciona con fotos rotadas).
2. **Reglas**: detectan nombre, fechas, tipo y categoría por palabras clave.
3. **Qwen**: recibe el texto y los **3 documentos verificados más parecidos** como ejemplos (few-shot) y
   devuelve un JSON con esquema fijo. Así "aprende" de las correcciones sin reentrenar pesos.
4. **Combinación**: la detección del nombre y la fecha se validan con las reglas (evita alucinaciones);
   tipo y categoría usan las reglas cuando encontraron palabras clave y Qwen cuando no; instituciones,
   eventos, títulos y resúmenes vienen de Qwen. Si hay desacuerdo, el documento se marca para revisar.
5. **Salida**: `Destino/<Año>/<Categoría>/<AAAA-MM-DD>_<Categoría>_<Evento>.ext` (copia; el original no se toca),
   registro en `datos/memoria.json` y `Destino/Productividad_academica.xlsx`.

### El Excel

- **Documentos**: una fila por documento con todos los campos, resumen, archivo renombrado y estado. Filas en amarillo = revisar.
- **Por año y categoría**: conteos para el informe.
- **Informe**: resúmenes agrupados por año y categoría, listos para copiar y pegar.

### Informe general en Word

Botón **Informe Word**: genera un `.docx` con resumen narrativo del periodo, tabla de actividades por
categoría y año, el detalle de cada actividad (resumen formal) agrupado por año y categoría, y un anexo
con la relación de documentos probatorios. Filtros: años (uno o varios, incluido "sin fecha"),
categorías, solo verificados, búsqueda de texto y documentos donde no aparece el titular. Se descarga y
queda guardado en `Destino/Informes/`. Los duplicados se cuentan una sola vez.

### Identificador de duplicados

- **Archivo idéntico** (mismo contenido): se reconoce al cargarlo y nunca se registra dos veces.
- **Misma actividad**: misma fecha, categoría, titular y evento/título (p. ej. dos fotos o un escaneo y
  un PDF de la misma constancia), o texto casi idéntico.

El botón **Duplicados (n)** muestra cada grupo con vista previa. Puede conservar uno y descartar los
demás (la copia se mueve a `Destino/_Duplicados`, no se borra nada y deja de contar en Excel y Word),
marcar "No son duplicados" (no se vuelve a sugerir) o restaurar un descartado.

### Respaldo

- **Respaldo JSON** descarga toda la memoria (`respaldo_memoria_AAAA-MM-DD_HHMM.json`).
- La app guarda además una copia automática diaria en `datos/respaldos/` (conserva las últimas 15).
- En **Configuración → Restaurar / fusionar un respaldo** se puede cargar un respaldo: agrega los
  documentos que falten y no borra ni sobrescribe los existentes.

### Memoria y "entrenamiento"

`datos/memoria.json` guarda cada documento procesado (por hash, así no se duplica aunque lo vuelva a cargar).
Cuando corrige un documento en la app y presiona **Guardar y verificar**, queda como ejemplo verificado y
Qwen lo usará para clasificar los siguientes documentos parecidos. Los 34 documentos de `Docs/` ya vienen
verificados (`datos/etiquetas_docs.json`).

Precisión medida con validación "deja uno fuera" (cada documento se clasifica sin verse a sí mismo):
ver `python -m organizador evaluar`.

> `datos/` y las carpetas de documentos están en `.gitignore`: contienen información personal y no se suben a GitHub.

## Instalación

1. Python 3.10 o superior.
2. Dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. (Recomendado) [Ollama](https://ollama.com) con el modelo Qwen:
   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
   Sin Ollama la app funciona igual con el algoritmo de reglas, pero sin resúmenes redactados por el modelo.

Ya **no** se necesitan Tesseract ni Poppler.

## Uso

### Interfaz (se abre en el navegador, corre solo en su computadora)
```bash
python pdf_organizer.py
```
1. **Arrastre las constancias** a la zona superior (o haga clic para elegirlas). Cada archivo se guarda en la
   carpeta de origen, se clasifica, se renombra, se resume y se agrega al Excel. También puede usar
   **▶ Clasificar carpeta de origen** para procesar una carpeta completa.
2. Revise los documentos marcados **revisar**, corrija lo necesario y presione **✔ Guardar y verificar**
   (el archivo se renombra de nuevo, el Excel se actualiza y el documento pasa a ser ejemplo para Qwen).
3. **Copiar resumen** pone el resumen en el portapapeles; **Abrir Excel** abre el consolidado.
4. En **Configuración** se cambian las carpetas, el nombre del titular y el modelo.

El servidor escucha solo en `127.0.0.1`; ningún documento sale de la computadora.

### Línea de comandos
```bash
python -m organizador procesar Docs "Docs clasificados"            # clasificar y renombrar
python -m organizador entrenar Docs datos/etiquetas_docs.json       # importar etiquetas verificadas
python -m organizador evaluar                                       # medir precisión
python -m organizador excel "Docs clasificados/Productividad_academica.xlsx"
python -m organizador word informe.docx --anios 2024 2025 --categorias Ponencia
python -m organizador duplicados                                    # listar posibles duplicados
python -m organizador respaldo respaldo.json                        # exportar memoria
python -m organizador respaldo --fusionar respaldo.json             # fusionar un respaldo
python -m organizador --sin-llm procesar ...                        # solo reglas
```

### Pruebas
```bash
python -m unittest discover tests
```

## Estructura

```
pdf_organizer.py         Inicia la interfaz web local
organizador/
  web.py, static/        Servidor local e interfaz (arrastrar y soltar, revisión, Excel)
  config.py              Nombre del titular, categorías, modelo
  extraccion.py          Texto de PDF/imagen + OCR
  reglas.py              Algoritmo de identificación por reglas
  llm.py                 Cliente de Ollama/Qwen con salida JSON
  memoria.py             Memoria JSON + búsqueda de ejemplos similares
  procesador.py          Flujo completo, renombrado y copia
  excel.py               Exportación a Excel
  word.py                Informe general en Word con filtros
  duplicados.py          Identificador de duplicados
  cli.py                 Línea de comandos
datos/                   (local, no se sube) config.json, memoria.json, etiquetas_docs.json
```

El nombre del titular y el modelo se cambian en `datos/config.json` (`mi_nombre`, `grado`, `modelo`).
