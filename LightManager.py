from phue import Bridge
from time import sleep
import requests
import random

class LightManager:
	# constants
	WHITE = [0.347,0.357]
	DEFAULT = [0.22,0.45] # ruined-king green
	BLUE = [0.156,0.145]
	RED = [0.678,0.3018]

	def __init__(self, active_IDs, ip, username):
		# INPUT params:
		# light_ids to be managed, as stored on Bridge
		# ip of Bridge
		# username to access Bridge API

		self.active_IDs = active_IDs
		self.ip = ip
		self.username = username

		# To interface with lights through phue.py
		self.lights = Bridge(ip=ip, username=username).get_light_objects('id')

		# To interface with lights through http
		base_address = '/'.join(['http:/',
			ip,
			"api",
			username,
			"lights"])
		# a dictionary containing each light's http address from which to query
		self.address = {ID: '/'.join([base_address, str(ID)]) for ID in active_IDs}

		# TODO user can't adjust brightness themselves without a transition mucking it
		self.brightness = {ID: self.lights[ID].brightness for ID in active_IDs}

		# for rainbow()
		self.gamut_vertices = {}
		for ID in active_IDs:
			self.gamut_vertices[ID] = requests.get(self.address[ID]).json()['capabilities']['control']['colorgamut']

	# For each active light, begin the colorloop.
	# Buffer denotes how far apart each light will be in the cycle.
	#        in unit revolutions
	# Buffer should be in [0,1]. Note that the endpoints are functionally identical.
	def colorloop(self, buffer=0.005):
		hue = int(random.uniform(0,65535))
		buffer = int(buffer*65535)
		for ID in self.active_IDs:
			self.lights[ID].hue = hue
			r = requests.put(self.address[ID]+"/state/", json={'effect':'colorloop'})
			hue = (hue + buffer) % 65535

	def end_colorloop(self):
		for ID in self.active_IDs:
			r = requests.put(self.address[ID]+"/state/", json={'effect':'none'})

	# Custom rainbow function.
	# Unlike the Hue colorloop effect, the time per cycle can be adjusted.
	# Will return to original color when finished.
	def rainbow(self, time_per_cycle=2, cycles=1, brightness_coeff=1):
		# Store initial value
		init_vals = {ID: requests.get(self.address[ID]).json()['state']['xy'] for ID in self.active_IDs}

		for ID in self.active_IDs:
			self.lights[ID].brightness = int(brightness_coeff*self.brightness[ID])

		for cycle in range(cycles):
			# Rainbow by transitioning to all three corners of gamut
			for i in range(3):
				for ID in self.active_IDs:
					self.lights[ID].transitiontime = time_per_cycle*10/3
					self.lights[ID].xy=self.gamut_vertices[ID][i]
				sleep(time_per_cycle/3)
	
		# Return to initial value
		for ID in self.active_IDs:
			self.lights[ID].transitiontime=40
			self.lights[ID].xy = init_vals[ID]
			self.lights[ID].brightness = self.brightness[ID]

	# Returns a JSON string for each dictionary's xy
	# e.g. '{"3":[0.3,0.3], "4":[0.4,0.4]}'
	# for good input into db_manager.set_state()
	# TODO but NOT for good input into LightManager.apply_state()
	def get_state(self):
		# We need double quotes around the keys
		result = {str(ID): self.lights[ID].xy for ID in self.active_IDs}
		return str(result).replace('\'', '\"')


	def apply_state(self, state, transitiontime=4, brightness_coeff=1):
		# state should be a dictionary {lightid: [x1, y1], ...}
		# lightid may be integer or string (e.g. 3 or '3') # TODO this introduces problems on .xy and .brightness
		#  													      currently, it has to be string.
		# transitiontime is an integer in unit deciseconds.
		for ID in state:
			intID = int(ID)
			if intID in self.active_IDs:
				self.lights[intID].transitiontime = transitiontime
				self.lights[intID].xy = state[ID]
				self.lights[intID].brightness = int(brightness_coeff*self.brightness[intID])

	def apply_color(self, xy=DEFAULT, transitiontime=4, brightness_coeff=1):
		for ID in self.active_IDs:
			self.lights[ID].transitiontime = transitiontime
			self.lights[ID].xy = xy
			# TODO user can't adjust brightness themselves without a transition mucking it
			self.lights[ID].brightness = int(brightness_coeff*self.brightness[ID])