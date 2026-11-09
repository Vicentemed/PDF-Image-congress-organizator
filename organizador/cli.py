"""Uso por línea de comandos.

    python -m organizador procesar Docs "Docs clasificados"
    python -m organizador entrenar Docs datos/etiquetas_docs.json
    python -m organizador evaluar
    python -m organizador excel "Docs clasificados/Productividad_academica.xlsx"
    python -m organizador word informe.docx --anios 2024 2025 --categorias Ponencia
    python -m organizador duplicados
    python -m organizador respaldo respaldo.json      (o: --fusionar respaldo.json)
"""
import argparse
import json
import os
import re
import sys
import time

from . import reglas
from .config import CONFIG_PATH, DATOS_DIR, MEMORIA_PATH, Config
from .excel import exportar
from .extraccion import extraer_texto, hash_archivo
from .memoria import Memoria
from .procesador import Procesador

NOMBRE_EXCEL = "Productividad_academica.xlsx"


def cmd_procesar(a, cfg, mem):
    proc = Procesador(cfg, mem)
    proc.procesar_rutas(a.rutas[:-1], a.rutas[-1], reprocesar=a.reprocesar)
    ruta = exportar(mem.lista(), os.path.join(a.rutas[-1], NOMBRE_EXCEL), cfg.nombre_completo)
    print(f"\nExcel: {ruta}")


def cmd_entrenar(a, cfg, mem):
    with open(a.etiquetas, encoding="utf-8") as f:
        etiquetas = json.load(f)["documentos"]
    n = 0
    for nombre, campos in etiquetas.items():
        ruta = os.path.join(a.carpeta, nombre)
        if not os.path.exists(ruta):
            print(f"  [!] No existe: {nombre}")
            continue
        doc_id = hash_archivo(ruta)
        reg = mem.get(doc_id) or {"id": doc_id, "archivo_original": nombre, "ruta_origen": os.path.abspath(ruta),
                                  "campos": {}, "metodo": "manual"}
        if not reg.get("texto"):
            t0 = time.time()
            reg["texto"], reg["metodo_texto"] = extraer_texto(ruta)
            print(f"  {nombre}: texto {reg['metodo_texto']} ({time.time() - t0:.1f}s)")
        reg["campos"] = dict(campos)
        reg["verificado"] = True
        reg["confianza"] = "verificado"
        reg.setdefault("avisos", [])
        mem.upsert(reg)
        n += 1
    mem.guardar()
    print(f"{n} ejemplos verificados en {mem.ruta}")


def _coincide_texto(a: str, b: str) -> bool:
    ta = set(re.findall(r"[a-z0-9]{3,}", reglas.normalizar(a or "")))
    tb = set(re.findall(r"[a-z0-9]{3,}", reglas.normalizar(b or "")))
    if not ta and not tb:
        return True
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.6


def cmd_evaluar(a, cfg, mem):
    """Validación dejando uno fuera: cada documento se clasifica sin verse a sí mismo
    ni a sus copias (mismo evento y fecha) entre los ejemplos."""
    proc = Procesador(cfg, mem, log=lambda m: None)
    verif = mem.verificados()
    if a.limite:
        verif = verif[: a.limite]
    campos_eval = ["tipo_documento", "categoria", "mi_nombre_presente", "fecha", "institucion", "evento", "titulo"]
    aciertos = {"reglas": {k: 0 for k in campos_eval}, "final": {k: 0 for k in campos_eval}}
    detalle = []
    t_total = time.time()
    for i, reg in enumerate(verif, 1):
        real = reg["campos"]
        excluir = {d["id"] for d in mem.verificados()
                   if d["id"] == reg["id"] or (d["campos"].get("fecha") == real.get("fecha")
                                               and d["campos"].get("evento") == real.get("evento")
                                               and d["campos"].get("titular") == real.get("titular"))}
        t0 = time.time()
        rg = reglas.clasificar(reg["texto"], cfg.mi_nombre, reg["archivo_original"], cfg.nombre_completo)
        final, conf, metodo, avisos = proc.clasificar_texto(reg["texto"], reg["archivo_original"], excluir=excluir)
        fila = {"archivo": reg["archivo_original"], "segundos": round(time.time() - t0, 1), "metodo": metodo,
                "confianza": conf, "errores": {}}
        for nombre, pred in (("reglas", rg), ("final", final)):
            for k in campos_eval:
                if k in ("institucion", "evento", "titulo"):
                    ok = _coincide_texto(pred.get(k), real.get(k))
                else:
                    ok = pred.get(k) == real.get(k)
                aciertos[nombre][k] += ok
                if not ok and nombre == "final":
                    fila["errores"][k] = {"esperado": real.get(k), "obtenido": pred.get(k)}
        fila["resumen"] = final.get("resumen")
        detalle.append(fila)
        marca = "OK " if not fila["errores"] else "ERR"
        print(f"[{i:>2}/{len(verif)}] {marca} {reg['archivo_original'][:55]:<55} {fila['segundos']:>5}s  "
              + ", ".join(f"{k}: {v['obtenido']!r} (esperado {v['esperado']!r})" for k, v in fila["errores"].items()
                          if k in ("categoria", "fecha", "tipo_documento", "mi_nombre_presente")))
    n = len(verif)
    print(f"\nPrecisión sobre {n} documentos (validación dejando uno fuera), {time.time() - t_total:.0f}s en total:")
    print(f"{'campo':<20}{'reglas':>10}{'final':>10}")
    for k in campos_eval:
        print(f"{k:<20}{aciertos['reglas'][k] / n:>10.0%}{aciertos['final'][k] / n:>10.0%}")
    salida = os.path.join(DATOS_DIR, "evaluacion.json")
    with open(salida, "w", encoding="utf-8") as f:
        json.dump({"n": n, "modelo": cfg.modelo if cfg.usar_llm else "reglas", "aciertos": aciertos,
                   "detalle": detalle}, f, ensure_ascii=False, indent=2)
    print(f"Detalle: {salida}")


def cmd_excel(a, cfg, mem):
    print(exportar(mem.lista(), a.salida, cfg.nombre_completo))


def cmd_word(a, cfg, mem):
    from .word import Filtros, generar_word
    f = Filtros(anios=a.anios or [], categorias=a.categorias or [], solo_verificados=a.solo_verificados,
                incluir_anexo=not a.sin_anexo, texto=a.buscar or "")
    r = generar_word(mem.lista(), a.salida, cfg.nombre_completo, f)
    print(f"{r['ruta']}  ({r['documentos']} actividades, periodo {r['periodo']})")


def cmd_duplicados(a, cfg, mem):
    from .duplicados import grupos
    gs = grupos(mem.lista())
    if not gs:
        print("No se encontraron posibles duplicados.")
    for i, g in enumerate(gs, 1):
        estado = "PENDIENTE" if g["pendiente"] else "resuelto"
        print(f"\nGrupo {i} [{estado}] — {', '.join(g['motivos'])}")
        for mid in g["miembros"]:
            r = mem.get(mid)
            marca = "conservar" if mid == g["principal"] else ("descartado" if r.get("descartado") else "duplicado")
            print(f"  [{marca:>10}] {r['campos'].get('fecha') or 'sin fecha'}  {r.get('archivo_nuevo') or r['archivo_original']}")


def cmd_respaldo(a, cfg, mem):
    if a.fusionar:
        with open(a.fusionar, encoding="utf-8") as f:
            res = mem.fusionar(json.load(f))
        mem.guardar()
        print(f"Fusionado: {res['agregados']} agregados, {res['actualizados']} actualizados, "
              f"{res['sin_cambio']} ya existían.")
    else:
        with open(a.salida, "wb") as f:
            f.write(mem.exportar_json())
        print(f"Respaldo con {len(mem.documentos)} documentos: {a.salida}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="organizador", description="Clasificador de constancias académicas")
    p.add_argument("--sin-llm", action="store_true", help="usar solo el algoritmo de reglas")
    p.add_argument("--modelo", help="modelo de Ollama (por defecto el de datos/config.json)")
    p.add_argument("--memoria", default=MEMORIA_PATH)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("procesar", help="clasificar, renombrar y copiar archivos")
    s.add_argument("rutas", nargs="+", help="archivos/carpetas de origen ... carpeta destino (último)")
    s.add_argument("--reprocesar", action="store_true", help="volver a clasificar aunque ya estén en memoria")
    s = sub.add_parser("entrenar", help="importar etiquetas verificadas como ejemplos")
    s.add_argument("carpeta")
    s.add_argument("etiquetas")
    s = sub.add_parser("evaluar", help="medir precisión con validación dejando uno fuera")
    s.add_argument("--limite", type=int, default=0)
    s = sub.add_parser("excel", help="regenerar el Excel desde la memoria")
    s.add_argument("salida")
    s = sub.add_parser("word", help="informe general en Word con filtros")
    s.add_argument("salida")
    s.add_argument("--anios", nargs="*", help="p. ej. 2024 2025 SinFecha")
    s.add_argument("--categorias", nargs="*", help="p. ej. Ponencia \"Evaluador / Revisor\"")
    s.add_argument("--buscar", help="texto a buscar")
    s.add_argument("--solo-verificados", action="store_true")
    s.add_argument("--sin-anexo", action="store_true")
    sub.add_parser("duplicados", help="listar grupos de posibles duplicados")
    s = sub.add_parser("respaldo", help="exportar la memoria a un JSON, o fusionar un respaldo")
    s.add_argument("salida", nargs="?", default="respaldo_memoria.json")
    s.add_argument("--fusionar", metavar="ARCHIVO", help="agregar documentos de un respaldo sin borrar nada")
    a = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = Config.cargar(CONFIG_PATH)
    if a.sin_llm:
        cfg.usar_llm = False
    if a.modelo:
        cfg.modelo = a.modelo
    mem = Memoria(a.memoria)
    {"procesar": cmd_procesar, "entrenar": cmd_entrenar, "evaluar": cmd_evaluar, "excel": cmd_excel,
     "word": cmd_word, "duplicados": cmd_duplicados, "respaldo": cmd_respaldo}[a.cmd](a, cfg, mem)


if __name__ == "__main__":
    main()
