"""
    SleekXMPP: The Sleek XMPP Library
    Copyright (C) 2007  Nathanael C. Fritz
    This file is part of SleekXMPP.

    SleekXMPP is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    SleekXMPP is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with SleekXMPP; if not, write to the Free Software
    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
"""
from __future__ import with_statement
from xml.etree import cElementTree as ET
from . xmlstream.xmlstream import XMLStream
from . xmlstream.matcher.xmlmask import MatchXMLMask
from . xmlstream.matcher.many import MatchMany
from . xmlstream.handler.xmlcallback import XMLCallback
from . xmlstream.handler.xmlwaiter import XMLWaiter
from . xmlstream.handler.callback import Callback
from . import plugins
from . stanza.message import Message
from . stanza.iq import Iq
from . stanza.presence import Presence
from . stanza.roster import Roster

import logging
import threading

def stanzaPlugin(stanza, plugin):
	stanza.plugin_attrib_map[plugin.plugin_attrib] = plugin
	stanza.plugin_tag_map["{%s}%s" % (plugin.namespace, plugin.name)] = plugin

stanzaPlugin(Iq, Roster)

class basexmpp(object):
	def __init__(self):
		self.id = 0
		self.id_lock = threading.Lock()
		self.sentpresence = False
		self.fulljid = ''
		self.resource = ''
		self.jid = ''
		self.username = ''
		self.server = ''
		self.plugin = {}
		self.auto_authorize = True
		self.auto_subscribe = True
		self.event_handlers = {}
		self.roster = {}
		self.registerHandler(Callback('IM', MatchXMLMask("<message xmlns='%s'><body /></message>" % self.default_ns), self._handleMessage))
		self.registerHandler(Callback('Presence', MatchXMLMask("<presence xmlns='%s' />" % self.default_ns), self._handlePresence))
		self.add_event_handler('presence_subscribe', self._handlePresenceSubscribe)
		self.registerStanza(Message)
		self.registerStanza(Iq)
		self.registerStanza(Presence)
	
	def Message(self, *args, **kwargs):
		return Presence(self, *args, **kwargs)

	def Iq(self, *args, **kwargs):
		return Iq(self, *args, **kwargs)

	def Presence(self, *args, **kwargs):
		return Presence(self, *args, **kwargs)
	
	def set_jid(self, jid):
		"""Rip a JID apart and claim it as our own."""
		self.fulljid = jid
		self.resource = self.getjidresource(jid)
		self.jid = self.getjidbare(jid)
		self.username = jid.split('@', 1)[0]
		self.server = jid.split('@',1)[-1].split('/', 1)[0]
		
	def registerPlugin(self, plugin, pconfig = {}):
		"""Register a plugin not in plugins.__init__.__all__ but in the plugins
		directory."""
		# discover relative "path" to the plugins module from the main app, and import it.
		__import__("%s.%s" % (globals()['plugins'].__name__, plugin))
		# init the plugin class
		self.plugin[plugin] = getattr(getattr(plugins, plugin), plugin)(self, pconfig) # eek
		# all of this for a nice debug? sure.
		xep = ''
		if hasattr(self.plugin[plugin], 'xep'):
			xep = "(XEP-%s) " % self.plugin[plugin].xep
		logging.debug("Loaded Plugin %s%s" % (xep, self.plugin[plugin].description))
	
	def register_plugins(self):
		"""Initiates all plugins in the plugins/__init__.__all__"""
		if self.plugin_whitelist:
			plugin_list = self.plugin_whitelist
		else:
			plugin_list = plugins.__all__
		for plugin in plugin_list:
			if plugin in plugins.__all__:
				self.registerPlugin(plugin, self.plugin_config.get(plugin, {}))
			else:
				raise NameError("No plugin by the name of %s listed in plugins.__all__." % plugin)
		# run post_init() for cross-plugin interaction
		for plugin in self.plugin:
			self.plugin[plugin].post_init()
	
	def getNewId(self):
		with self.id_lock:
			self.id += 1
			return self.getId()
	
	def add_handler(self, mask, pointer, disposable=False, threaded=False, filter=False, instream=False):
		#logging.warning("Deprecated add_handler used for %s: %s." % (mask, pointer))
		self.registerHandler(XMLCallback('add_handler_%s' % self.getNewId(), MatchXMLMask(mask), pointer, threaded, disposable, instream))
	
	def getId(self):
		return "%x".upper() % self.id

	def sendXML(self, data, mask=None, timeout=10):
		return self.send(self.tostring(data), mask, timeout)
	
	def send(self, data, mask=None, timeout=10):
		#logging.warning("Deprecated send used for \"%s\"" % (data,))
		#if not type(data) == type(''):
		#	data = self.tostring(data)
		if hasattr(mask, 'xml'):
			mask = mask.xml
		data = str(data)
		if mask is not None:
			waitfor = XMLWaiter('SendWait_%s' % self.getNewId(), MatchXMLMask(mask))
			self.registerHandler(waitfor)
		self.sendRaw(data)
		if mask is not None:
			return waitfor.wait(timeout)
	
	def makeIq(self, id=0, ifrom=None):
		return self.Iq().setValues({'id': id, 'from': ifrom})
	
	def makeIqGet(self, queryxmlns = None):
		iq = self.Iq().setValues({'type': 'get'})
		if queryxmlns:
			iq.append(ET.Element("{%s}query" % queryxmlns))
		return iq
	
	def makeIqResult(self, id):
		return self.Iq().setValues({'id': id, 'type': 'result'})
	
	def makeIqSet(self, sub=None):
		iq = self.Iq().setValues({'type': 'set'})
		if sub != None:
			iq.append(sub)
		return iq

	def makeIqError(self, id, type='cancel', condition='feature-not-implemented', text=None):
		iq = self.Iq().setValues({'id': id})
		iq['error'].setValues({'type': type, 'condition': condition, 'text': text})
		return iq

	def makeIqQuery(self, iq, xmlns):
		query = ET.Element("{%s}query" % xmlns)
		iq.append(query)
		return iq
	
	def makeQueryRoster(self, iq=None):
		query = ET.Element("{jabber:iq:roster}query")
		if iq:
			iq.append(query)
		return query
	
	def add_event_handler(self, name, pointer, threaded=False, disposable=False):
		if not name in self.event_handlers:
			self.event_handlers[name] = []
		self.event_handlers[name].append((pointer, threaded, disposable))

	def event(self, name, eventdata = {}): # called on an event
		for handler in self.event_handlers.get(name, []):
			if handler[1]: #if threaded
				#thread.start_new(handler[0], (eventdata,))
				x = threading.Thread(name="Event_%s" % str(handler[0]), target=handler[0], args=(eventdata,))
				x.start()
			else:
				handler[0](eventdata)
			if handler[2]: #disposable
				with self.lock:
					self.event_handlers[name].pop(self.event_handlers[name].index(handler))
	
	def makeMessage(self, mto, mbody='', msubject=None, mtype=None, mhtml=None, mfrom=None, mnick=None):
		message = ET.Element('{%s}message' % self.default_ns)
		if mfrom is None:
			message.attrib['from'] = self.fulljid
		else:
			message.attrib['from'] = mfrom
		message.attrib['to'] = mto
		if not mtype:
			mtype='chat'
		message.attrib['type'] = mtype
		if mtype == 'none':
			del message.attrib['type']
		if mbody:
			body = ET.Element('body')
			body.text = mbody
			message.append(body)
		if mhtml :
			html = ET.Element('{http://jabber.org/protocol/xhtml-im}html')
			html_body = ET.XML('<body xmlns="http://www.w3.org/1999/xhtml">' + mhtml + '</body>')
			html.append(html_body)
			message.append(html)
		if msubject:
			subject = ET.Element('subject')
			subject.text = msubject
			message.append(subject)
		if mnick:
			print("generating nick")
			nick = ET.Element("{http://jabber.org/protocol/nick}nick")
			nick.text = mnick
			message.append(nick)
		return message
	
	def makePresence(self, pshow=None, pstatus=None, ppriority=None, pto=None, ptype=None, pfrom=None):
		if pshow == 'unavailable':
			pshow = None
			ptype = 'unavailable'
		presence = ET.Element('{%s}presence' % self.default_ns)
		if ptype:
			presence.attrib['type'] = ptype
		if pshow:
			show = ET.Element('show')
			show.text = pshow
			presence.append(show)
		if pstatus:
			status = ET.Element('status')
			status.text = pstatus
			presence.append(status)
		if ppriority:
			priority = ET.Element('priority')
			priority.text = str(ppriority)
			presence.append(priority)
		if pto:
			presence.attrib['to'] = pto
		if pfrom is None:
			presence.attrib['from'] = self.fulljid
		else:
			presence.attrib['from'] = pfrom
		return presence
	
	def sendMessage(self, mto, mbody, msubject=None, mtype=None, mhtml=None, mfrom=None, mnick=None):
		self.send(self.makeMessage(mto,mbody,msubject,mtype,mhtml,mfrom,mnick))
	
	def sendPresence(self, pshow=None, pstatus=None, ppriority=None, pto=None, pfrom=None, ptype=None):
		self.send(self.makePresence(pshow,pstatus,ppriority,pto, ptype=ptype, pfrom=pfrom))
		if not self.sentpresence:
			self.event('sent_presence')
			self.sentpresence = True

	def sendPresenceSubscription(self, pto, pfrom=None, ptype='subscribe', pnick=None) :
		presence = self.makePresence(ptype=ptype, pfrom=pfrom, pto=self.getjidbare(pto))
		if pnick :
			nick = ET.Element('{http://jabber.org/protocol/nick}nick')
			nick.text = pnick
			presence.append(nick)
		self.send(presence)
	
	def getjidresource(self, fulljid):
		if '/' in fulljid:
			return fulljid.split('/', 1)[-1]
		else:
			return ''
	
	def getjidbare(self, fulljid):
		return fulljid.split('/', 1)[0]

	def _handleMessage(self, msg):
		self.event('message', msg)
	
	def _handlePresence(self, presence):
		"""Update roster items based on presence"""
		self.event("presence_%s" % presence['type'], presence)
		if not presence['type'] in ('available', 'unavailable'):
			return
		jid = presence['from'].bare
		resource = presence['from'].resource
		show = presence['type']
		status = presence['status']
		priority = presence['priority']
		wasoffline = False
		oldroster = self.roster.get(jid, {}).get(resource, {})
		if not presence['from'].bare in self.roster:
			self.roster[jid] = {'groups': [], 'name': '', 'subscription': 'none', 'presence': {}, 'in_roster': False}
		if not resource in self.roster[jid]['presence']:
			wasoffline = True
			self.roster[jid]['presence'][resource] = {'show': show, 'status': status, 'priority': priority}
		else:
			if self.roster[jid]['presence'][resource].get('show', None) == 'unavailable':
				wasoffline = True
			self.roster[jid]['presence'][resource] = {'show': show, 'status': status}
			self.roster[jid]['presence'][resource]['priority'] = priority
		name = self.roster[jid].get('name', '')
		if wasoffline and show in ('available', 'away', 'xa', 'na', 'ffc'):
			self.event("got_online", presence)
		elif not wasoffline and show == 'unavailable':
			self.event("got_offline", eventdata)
			if len(self.roster[jid]['presence']) > 1:
				del self.roster[jid]['presence'][resource]
			else:
				del self.roster[jid]
		elif oldroster != self.roster.get(jid, {'presence': {}})['presence'].get(resource, {}) and show != 'unavailable':
			self.event("changed_status", presence)
		name = ''
		if name:
			name = "(%s) " % name
		logging.debug("STATUS: %s%s/%s[%s]: %s" % (name, jid, resource, show,status))
	
	def _handlePresenceSubscribe(self, presence):
		"""Handling subscriptions automatically."""
		if self.auto_authorize == True:
			self.send(self.makePresence(ptype='subscribed', pto=presence['from'].bare))
			if self.auto_subscribe:
				self.send(self.makePresence(ptype='subscribe', pto=presence['from'].bare))
		elif self.auto_authorize == False:
			self.send(self.makePresence(ptype='unsubscribed', pto=presence['from'].bare))
