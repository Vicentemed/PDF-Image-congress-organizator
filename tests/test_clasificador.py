"""Pruebas del algoritmo de reglas, la combinación con el LLM, el renombrado y el Excel.

Ejecutar:  python -m unittest discover tests
(No requieren Ollama ni los documentos reales.)
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from organizador import reglas  # noqa: E402
from organizador.excel import exportar  # noqa: E402
from organizador.memoria import Memoria  # noqa: E402
from organizador.procesador import combinar, nombre_nuevo  # noqa: E402

YO = "Vicente Esparza Villalpando"

PONENCIA = ("Por su valiosa participación como Conferencista Magistral con la ponencia: al Dr. Vicente Esparza "
            "Villalpando La Universidad Autónoma de Aguascalientes a través del Departamento de Estomatología "
            "otorga el presente Reconocimiento Buenas prácticas en análisis de datos en odontología En el marco "
            "de la XL Semana Cultural de Estomatología UAA, llevado a cabo los días 19, 20 y 21 de febrero de 2025")
COAUTOR_OCR = ("Otorgan la presente Constancia a: Sandra Daniela Arreola Martinez Masuoka Ito David, Esparza "
               "Vilpando Vicente, Barrera Bernal Jose Luis Categoria:Licenciatura Por su participacion como ponente "
               "en el XXXIIENCUENTRONACIONAL Efectuadolosdias6,7y8denoviembrede2024. \"Por mi raza hablard mi espiritu\" "
               "Leon,Guanajuato,8denoviembrede2024.")
AJENO = ("Constancia a: Castillo Sagredo Emily Libertad Masuoka Ito David, Gomez Aguirre Yenny Adriana "
         "Por su participacion como ponente. Leon, Guanajuato, 8 de noviembre de 2024.")
REVISOR = ("REVIEWER CERTIFICATE This certificate is awarded to in recognition of their contribution to "
           "Vicente Esparza-Villalpando 2 manuscripts in 2024 for BMC Oral Health 27 November 2024")
ASISTENCIA = ("Otorga la presente CONSTANCIA a: VICENTEESPARZA-VILLALPANDO Por su ASISTENCIA en el Tercer Encuentro "
              "Ciudad Universitaria, a 14 de noviembre de 2025 Dr. Sergio Coordinador del Comite Organizador")


class TestReglas(unittest.TestCase):
    def test_nombre_con_errores_ocr(self):
        self.assertTrue(reglas.nombre_presente(COAUTOR_OCR, YO))
        self.assertTrue(reglas.nombre_presente(ASISTENCIA, YO))
        self.assertFalse(reglas.nombre_presente(AJENO, YO))

    def test_fechas(self):
        self.assertEqual(reglas.fecha_principal(PONENCIA)[0], "2025-02-21")
        self.assertEqual(reglas.fecha_principal(COAUTOR_OCR)[0], "2024-11-08")
        self.assertEqual(reglas.fecha_principal(REVISOR)[0], "2024-11-27")
        self.assertEqual(reglas.fecha_principal("JALISCODEL1AL4OCTUBREDE2025")[0], "2025-10-04")
        self.assertEqual(reglas.fecha_principal("sin fechas", "Foro 2024.pdf")[0], "2024")

    def test_categorias(self):
        self.assertEqual(reglas.categoria(PONENCIA, YO), "Ponencia")
        self.assertEqual(reglas.categoria(COAUTOR_OCR, YO), "Coautoría")
        self.assertEqual(reglas.categoria(REVISOR, YO), "Evaluador / Revisor")
        self.assertEqual(reglas.categoria(ASISTENCIA, YO), "Asistencia")
        self.assertEqual(reglas.categoria(AJENO, YO), "Otro")

    def test_tipo_y_evento(self):
        self.assertEqual(reglas.tipo_documento(PONENCIA), "Reconocimiento")
        self.assertEqual(reglas.tipo_documento(REVISOR), "Certificado")
        self.assertEqual(reglas.evento(REVISOR), "BMC Oral Health")
        self.assertIn("Semana Cultural", reglas.evento(PONENCIA))

    def test_lema_no_es_titulo(self):
        self.assertEqual(reglas.titulo(COAUTOR_OCR), "")


class TestCombinar(unittest.TestCase):
    def test_llm_alucina_nombre(self):
        rg = reglas.clasificar(AJENO, YO, nombre_completo="Dr. " + YO)
        llm = dict(rg, mi_nombre_presente=True, categoria="Coautoría", _texto=AJENO,
                   resumen="Constancia a Emily Libertad Castillo Sagredo; el Dr. Vicente Esparza Villalpando figura como coautor.")
        c, conf, avisos = combinar(llm, rg, "Dr. " + YO)
        self.assertFalse(c["mi_nombre_presente"])
        self.assertEqual(c["categoria"], "Otro")
        self.assertNotIn("figura como coautor", c["resumen"])
        self.assertNotIn("el Dr. El", c["resumen"])
        self.assertTrue(avisos)

    def test_placeholders_y_fecha_invalida(self):
        rg = reglas.clasificar(PONENCIA, YO)
        llm = dict(rg, titulo="No especificado", fecha="21/02/25", _texto=PONENCIA)
        c, _conf, _av = combinar(llm, rg, YO)
        self.assertEqual(c["fecha"], "2025-02-21")
        self.assertNotEqual(c["titulo"], "No especificado")

    def test_sin_llm(self):
        rg = reglas.clasificar(REVISOR, YO)
        c, conf, _ = combinar(None, rg, YO)
        self.assertEqual(c["categoria"], "Evaluador / Revisor")
        self.assertEqual(conf, "media")


class TestSalida(unittest.TestCase):
    def test_nombre_archivo(self):
        c = {"fecha": "2025-02-21", "categoria": "Ponencia", "mi_nombre_presente": True,
             "evento": "XL Semana Cultural de Estomatología UAA 2025"}
        self.assertEqual(nombre_nuevo(c, ".PDF"), "2025-02-21_Ponencia_XL Semana Cultural de Estomatologia UAA 2025.pdf")
        c2 = dict(c, categoria="Coautoría", titular="María José Rangel de Lira")
        self.assertTrue(nombre_nuevo(c2, ".jpg").endswith("_Maria Jose Rangel de Lira.jpg"))

    def test_memoria_y_excel(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memoria(os.path.join(d, "memoria.json"))
            for i, texto in enumerate((PONENCIA, REVISOR, AJENO)):
                m.upsert({"id": str(i), "archivo_original": f"{i}.pdf", "texto": texto, "verificado": True,
                          "campos": reglas.clasificar(texto, YO)})
            m.guardar()
            m2 = Memoria(os.path.join(d, "memoria.json"))
            self.assertEqual(len(m2.documentos), 3)
            similares = m2.similares("Reviewer certificate for Scientific Reports", k=1)
            self.assertEqual(similares[0]["id"], "1")
            ruta = exportar(m2.lista(), os.path.join(d, "x.xlsx"), "Dr. " + YO)
            self.assertTrue(os.path.getsize(ruta) > 0)

    def test_duplicados_cuentan_una_vez(self):
        from organizador.excel import _unicos
        c = reglas.clasificar(PONENCIA, YO)
        regs = [{"id": "a", "campos": dict(c)}, {"id": "b", "campos": dict(c), "verificado": True}]
        unicos = _unicos(regs)
        self.assertEqual(len(unicos), 1)
        self.assertEqual(unicos[0]["id"], "b")


if __name__ == "__main__":
    unittest.main()
