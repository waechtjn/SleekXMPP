from . import base
import queue
import logging
from .. stanzabase import StanzaBase

class Waiter(base.BaseHandler):
	
	def __init__(self, name, matcher):
		base.BaseHandler.__init__(self, name, matcher)
		self._payload = queue.Queue()
	
	def prerun(self, payload):
		self._payload.put(payload)
	
	def run(self, payload):
		pass

	def wait(self, timeout=60):
		try:
			return self._payload.get(True, timeout)
		except queue.Empty:
			logging.warning("Timed out waiting for %s" % self.name)
			return StanzaBase(stype='error')
	
	def checkDelete(self):
		return True
