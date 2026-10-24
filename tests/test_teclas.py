import unittest

import wx

from tdt import teclas


class _Evento:
    def __init__(self, modificadores, codigo):
        self._m, self._c = modificadores, codigo

    def GetModifiers(self):
        return self._m

    def GetKeyCode(self):
        return self._c


class Teclas(unittest.TestCase):
    def test_normalizar_y_wx(self):
        self.assertEqual(teclas.normalizar("shift+ctrl+f1"), "Ctrl+Shift+F1")
        self.assertEqual(teclas.normalizar("alt+up"), "Alt+UP")
        self.assertEqual(teclas.a_wx("Ctrl+Shift+F1"), (wx.MOD_CONTROL | wx.MOD_SHIFT, wx.WXK_F1))
        self.assertEqual(teclas.a_wx("Ctrl+,"), (wx.MOD_CONTROL, ord(",")))
        self.assertIsNone(teclas.a_wx("Ctrl+Inventada"))
        self.assertEqual(teclas.legible("Ctrl+Shift+Up"), "Ctrl+Mayús+Flecha arriba")
        self.assertEqual(teclas.legible(""), "sin tecla")

    def test_globales_validas(self):
        self.assertTrue(teclas.valida_global("F3"))
        self.assertTrue(teclas.valida_global("Ctrl+Shift+A"))
        self.assertFalse(teclas.valida_global("A"))
        self.assertFalse(teclas.valida_global("Shift+B"))

    def test_personalizacion_y_conflictos(self):
        windows = {"teclas": {"repro_pausa": "ctrl+f2", "inexistente": "F9", "repro_detener": 5}}
        t = teclas.Teclas(windows)
        self.assertEqual(t.combo("repro_pausa"), "Ctrl+F2")
        self.assertTrue(t.es_personalizada("repro_pausa"))
        self.assertEqual(t.combo("repro_detener"), "F4")
        self.assertEqual(t.conflicto("canal_reproducir", "F4"), "repro_detener")
        self.assertIsNone(t.conflicto("repro_detener", "F4"))
        self.assertTrue(t.es_reservada("Space"))
        t.establecer("repro_pausa", "F2")
        self.assertFalse(t.es_personalizada("repro_pausa"))
        self.assertEqual(windows["teclas"], {})
        t.establecer("repro_siguiente", "Ctrl+Right")
        self.assertEqual(t.accion_global(_Evento(wx.MOD_CONTROL, wx.WXK_RIGHT)), "repro_siguiente")
        self.assertIsNone(t.accion_global(_Evento(0, wx.WXK_F8)))
        t.restaurar(seccion=teclas.SEC_REPRODUCTOR)
        self.assertEqual(t.accion_global(_Evento(0, wx.WXK_F8)), "repro_siguiente")
        self.assertEqual(t.etiqueta_menu("repro_pausa"), "Reproducir o &pausar\tF2")
        self.assertIn("F2", t.texto_ayuda())

    def test_sin_teclas_repetidas_por_defecto(self):
        vistas = {}
        for accion, combo in teclas.DEFECTO.items():
            if combo:
                self.assertNotIn(combo, vistas, f"{accion} repite {combo} con {vistas.get(combo)}")
                vistas[combo] = accion
        for accion in teclas.ACCIONES_GLOBALES:
            self.assertTrue(teclas.valida_global(teclas.DEFECTO[accion]), accion)


if __name__ == "__main__":
    unittest.main()
