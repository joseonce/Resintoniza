# -*- coding: utf-8 -*-
"""Complemento de NVDA: lectura completa de las listas de Resintoniza.

NVDA, al recorrer una lista de varias columnas (SysListView32), recorta el texto
de cada columna a 511 caracteres, porque usa un búfer fijo dentro del proceso
(CBEMAXSTRLEN = 512). En Resintoniza eso deja a medias la descripción de un
programa de la guía o la información de un canal.

El complemento sube ese límite y fuerza la lectura fuera del proceso, que no
tiene ese tope. Todo es reversible: al desactivar el complemento, NVDA queda
exactamente como estaba.
"""

import globalPluginHandler

try:
	from logHandler import log
except Exception:  # por si cambia la ubicación del registro entre versiones de NVDA
	import logging
	log = logging.getLogger("resintonizaListViewFix")

# Tamaño máximo de lectura por columna, en caracteres. Generoso para las sinopsis largas.
NUEVO_MAXIMO = 16384


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		self._parcheado = False
		self._sysLV = None
		self._max_original = None
		self._raw_original = None
		try:
			from NVDAObjects.IAccessible import sysListView32
		except Exception as e:
			log.warning("resintonizaListViewFix: no se pudo importar sysListView32: %r" % (e,))
			return

		ListItem = getattr(sysListView32, "ListItem", None)
		# Solo se parchea si esta versión de NVDA tiene exactamente las piezas esperadas.
		if (
			ListItem is None
			or not hasattr(sysListView32, "CBEMAXSTRLEN")
			or not hasattr(ListItem, "_getColumnContentRaw")
			or not hasattr(ListItem, "_getColumnContentRawOutProc")
		):
			log.warning(
				"resintonizaListViewFix: esta versión de NVDA no es compatible con el parche; "
				"no se aplica ningún cambio."
			)
			return

		self._sysLV = sysListView32
		self._max_original = sysListView32.CBEMAXSTRLEN
		self._raw_original = ListItem._getColumnContentRaw
		raw_original = self._raw_original

		def _getColumnContentRaw_parcheado(itemSelf, index):
			# La ruta dentro del proceso usa un búfer fijo de 512 caracteres en C; la de fuera
			# del proceso no. Si fallara, se vuelve a la original para no quedarse sin leer nada.
			try:
				return itemSelf._getColumnContentRawOutProc(index)
			except Exception:
				log.debugWarning(
					"resintonizaListViewFix: la lectura fuera del proceso falló; uso la original.",
					exc_info=True,
				)
				return raw_original(itemSelf, index)

		sysListView32.CBEMAXSTRLEN = NUEVO_MAXIMO
		ListItem._getColumnContentRaw = _getColumnContentRaw_parcheado
		self._parcheado = True
		log.info(
			"resintonizaListViewFix: lectura de listas ampliada a %d caracteres por columna."
			% (NUEVO_MAXIMO,)
		)

	def terminate(self, *args, **kwargs):
		try:
			if self._parcheado and self._sysLV is not None:
				self._sysLV.CBEMAXSTRLEN = self._max_original
				self._sysLV.ListItem._getColumnContentRaw = self._raw_original
				self._parcheado = False
		except Exception:
			log.debugWarning("resintonizaListViewFix: error al revertir el parche.", exc_info=True)
		try:
			super().terminate(*args, **kwargs)
		except Exception:
			pass
