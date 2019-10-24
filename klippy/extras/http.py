import logging
import threading

import tornado.web
import tornado.gen
import tornado.websocket
import base64
import uuid
import os
import copy
import shutil
import kinematics.extruder
import json
import io, traceback
from multiprocessing import Queue, JoinableQueue


class RequestHandler(tornado.web.RequestHandler):
	def set_default_headers(self):
		self.set_header("Connection", "close")
		self.set_header("Access-Control-Allow-Origin", "*")
		self.set_header("Access-Control-Allow-Methods", "*")
		self.set_header("Access-Control-Allow-Headers", "*")


class RestHandler(RequestHandler):
	def set_default_headers(self):
		super(RestHandler, self).set_default_headers()
		self.set_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
		self.set_header('Content-Type', 'application/json')

	def initialize(self, manager):
		self.manager = manager

	def options(self, *kwargs):
		self.set_status(204)
		self.finish()

	def write_error(self, status_code, exc_info):
		out = io.BytesIO()
		traceback.print_exception(exc_info[0], exc_info[1], exc_info[2], None, out)
		formatted = out.getvalue()
		out.close()
		self.set_header("Content-Type", "text/plain")
		self.finish(formatted)


class MachineFileHandler(RestHandler):
	def put(self, path):
		real_path = self.manager.virtual_sdcard.resolve_path(path)
		dirname = os.path.dirname(real_path)
		if not os.path.exists(dirname):
			os.makedirs(dirname)
		with open(real_path, 'w') as file:
			file.write(self.request.body)

	def delete(self, path):
		real_path = self.manager.virtual_sdcard.resolve_path(path)
		if os.path.isdir(real_path):
			shutil.rmtree(real_path)
		else:
			os.remove(real_path)

	def get(self, path):
		def force_download(buff, filename):
			self.set_header('Content-Type', 'application/force-download')
			self.set_header('Content-Disposition', 'attachment; filename=%s' % filename)
			self.finish(buff)

		real_path = self.manager.virtual_sdcard.resolve_path(path)

		if os.path.isfile(real_path):
			with open(real_path, "rb") as f:
				force_download(f.read(), os.path.basename(real_path))
		else:
			raise tornado.web.HTTPError(404, "File does not exist")


class HeightMapHandler(RestHandler):
	def get(self):
		bed_mesh = self.manager.printer.lookup_object("bed_mesh")
		if bed_mesh and bed_mesh.z_mesh and bed_mesh.z_mesh.mesh_z_table:
			height_map = self.get_height_map(bed_mesh)
			self.finish(height_map)
		else:
			raise tornado.web.HTTPError(404, "No height map available")

	def get_height_map(self, bed_mesh):
		z_mesh = bed_mesh.z_mesh

		mesh = []
		for y in range(z_mesh.mesh_y_count - 1, -1, -1):
			for x, z in enumerate(z_mesh.mesh_z_table[y]):
				mesh.append(
					[z_mesh.mesh_x_min + x * z_mesh.mesh_x_dist, z_mesh.mesh_y_min + (y - 1) * z_mesh.mesh_y_dist, (z)])

		probed = []
		for y, line in enumerate(bed_mesh.calibrate.probed_z_table):
			for x, z in enumerate(line):
				probed.append(
					[z_mesh.mesh_x_min + x * z_mesh.mesh_x_dist, z_mesh.mesh_y_min + (y - 1) * z_mesh.mesh_y_dist, z])

		return dict(mesh=mesh, probed=probed)


class WebSocketHandler(tornado.websocket.WebSocketHandler):
	clients = set()

	def initialize(self, manager):
		self.manager = manager

	def check_origin(self, origin):
		return True

	def open(self):
		WebSocketHandler.clients.add(self)
		self.handle_status()

	def on_message(self, data):
		message = json.parse(data)
		if message["type"] == "gcode":
			self.handle_gcode(message.payload)
		elif message["type"] == "status":
			self.handle_status()

	def on_close(self):
		try:
			WebSocketHandler.clients.remove(self)
		except:
			pass

	def handle_gcode(self, gcode):
		self.manager.dispatch(self.manager.process_gcode, gcode)

	def handle_status(self):
		self.write_message({
			"type": "status",
			"payload": self.manager.dispatch(self.manager.get_state, self.manager.reactor.monotonic())
		})

	@classmethod
	def broadcast(cls, payload):
		for client in copy.copy(cls.clients):
			try:
				# remove the client and wait for reply before sending updates again
				WebSocketHandler.clients.remove(client)
				client.write_message(payload)
			except:
				logging.exception("unable to write")


class ToolState:
	def __init__(self, manager):
		self.manager = manager
		self.printer = manager.printer
		self.printer.register_event_handler("klippy:ready", self.handle_ready)

		self.extruders = []

	def handle_ready(self):
		self.extruders = kinematics.extruder.get_printer_extruders(self.printer)

	def get_state(self, eventtime):
		tools = []
		for extruder in self.extruders:
			ex_heater_index = self.manager.heat.get_heater_index(extruder.heater)
			heater_status = extruder.heater.get_status(eventtime)

			tools.append({
				"number": self.extruders.index(extruder),
				"active": [heater_status['target']],
				"filamentExtruder": 0,
				"heaters": [ex_heater_index],
				"extruders": [self.get_extruder_index(extruder)],
			})
		return tools

	def get_extruder_index(self, extruder):
		return self.extruders.index(extruder)


class MoveState:
	def __init__(self, manager):
		self.manager = manager
		self.printer = manager.printer
		self.printer.register_event_handler("klippy:ready", self.handle_ready)

		self.gcode = self.printer.lookup_object("gcode")
		self.configfile = self.printer.lookup_object('configfile').read_main_config()

		self.extruders = []
		self.kinematics = None
		self.bed_mesh = None
		self.top_speed = 0

	def handle_ready(self):
		self.toolhead = self.printer.lookup_object('toolhead')
		self.kinematics = self.toolhead.get_kinematics()
		self.bed_mesh = self.printer.lookup_object("bed_mesh", None)
		self.extruders = kinematics.extruder.get_printer_extruders(self.printer)

	def get_state(self, eventtime):
		position = self.gcode.last_position
		gcode_status = self.gcode.get_status(eventtime)

		steppers = []
		drives = []
		axes = []
		if self.kinematics:
			for rail in self.kinematics.rails:
				min_pos, max_pos = rail.get_range()
				low_limit, high_limit = self.kinematics.limits[self.kinematics.rails.index(rail)]

				for stepper in rail.steppers:
					steppers.append(stepper)
					drives.append({
						"position": position[self.kinematics.rails.index(rail)],
					})

				axes.append({
					"letter": rail.name,
					"drives": [steppers.index(stepper) for stepper in rail.steppers],
					"homed": low_limit <= high_limit,
					"min": min_pos,
					"max": max_pos,
				})

		extruders = []
		for extruder in self.extruders:
			steppers.append(extruder.stepper)
			drives.append({
				"position": position[steppers.index(extruder.stepper)],
			})
			extruders.append({
				"drives": [steppers.index(extruder.stepper)],
				"factor": self.gcode.extrude_factor,
			})

		return ({
			"axes": axes,
			"drives": drives,
			"extruders": extruders,
			"babystepZ": self.gcode.homing_position[2],
			"speedFactor": gcode_status["speed_factor"],
			"geometry": {
				"type": self.configfile.getsection("printer").get("kinematics"),
			}
		})


class HeatState:
	def __init__(self, manager):
		self.printer = manager.printer
		self.printer.register_event_handler("klippy:ready", self.handle_ready)

		self.heat = self.printer.lookup_object('heater')
		self.heaters = []
		self.heat_beds = []
		self.probe_temps = []

	def handle_ready(self):
		self.heaters = self.heat.heaters.items()
		self.heat_beds = self.printer.lookup_objects('heater_bed')
		self.probe_temps = self.printer.lookup_objects('probe_temp')

	def get_state(self, eventtime):
		heater_statuses = [heater.get_status(eventtime) for name, heater in self.heaters]

		beds = []
		for name, heat_bed in self.heat_beds:
			bed_heater_index = self.get_heater_index(heat_bed)
			heater_bed_status = heater_statuses[bed_heater_index]
			beds.append({
				"name": name,
				"active": [heater_bed_status['target']],
				"heaters": [bed_heater_index]
			})

		heaters = []
		if self.heat:
			for name, heater in self.heaters:
				heater_status = heater_statuses[self.get_heater_index(heater)]
				heaters.append({
					"current": heater_status["temperature"],
					"name": name,
					"state": self.get_heater_state(heater_status),
				})

		extra = []
		for name, probe_temp in self.probe_temps:
			probe_temp, probe_target = probe_temp.get_temp(eventtime)
			extra.append({
				"name": "probe_temp",
				"current": probe_temp
			})

		return ({
			"beds": beds,
			"heaters": heaters,
			"extra": extra,
		})

	def get_heater_index(self, heater):
		return self.heat.heaters.values().index(heater)

	def get_heater_state(self, status):
		state = 0
		if status['target'] > 0:
			state = 1
		return state


class SensorState:
	def __init__(self, manager):
		self.manager = manager
		self.printer = manager.printer
		self.printer.register_event_handler("klippy:ready", self.handle_ready)
		self.probes = []

	def handle_ready(self):
		query_endstops = self.printer.try_load_module(self.manager.config, 'query_endstops')
		self.endstops = query_endstops.endstops
		self.probes = self.printer.lookup_objects('probe')

	def get_state(self, eventtime):
		probes = []

		for name, probe in self.probes:
			probes.append({
				# "value": null,
				"offsets": probe.get_offsets(),
			})

		endstops = []
		# last_move_time = self.toolhead.get_last_move_time() # TODO: raises random exceptions like DripModeEndSignal
		# for endstop, name in self.endstops:
		# 	endstops.append({"name": name, "triggered": endstop.query_endstop(last_move_time)})

		return ({
			"endstops": endstops,
			"probes": probes
		})


class FanState:
	def __init__(self, manager):
		self.manager = manager
		self.printer = self.manager.printer
		self.printer.register_event_handler("klippy:ready", self.handle_ready)
		self.fans = []
		self.heater_fans = []

	def handle_ready(self):
		self.fans = self.printer.lookup_objects('fan')
		self.heater_fans = self.printer.lookup_objects('heater_fan')

	def get_state(self, eventtime):
		fans = []

		for name, fan in self.fans:
			fan_status = fan.get_status(eventtime)
			fans.append({
				"name": name,
				"value": fan_status["speed"],
				"max": fan.max_power
			})

		for name, fan in self.heater_fans:
			fan_status = fan.get_status(eventtime)
			fans.append({
				"name": name,
				"value": fan_status["speed"],
				"max": fan.fan.max_power,
				"thermostatic": {
					"control": True,
					"heaters": [self.manager.heat.get_heater_index(heater) for heater in fan.heaters],
					"temperature": fan.heater_temp
				}
			})

		return fans


class State:
	def __init__(self, manager):
		self.manager = manager
		self.printer = manager.printer
		self.virtual_sdcard = None
		self.printer.register_event_handler("klippy:ready", self.handle_ready)
		self.status = 'off'

		self.toolhead = None
		self.gcode = self.printer.lookup_object("gcode")

	def handle_ready(self):
		self.status = 'idle'
		self.toolhead = self.printer.lookup_object('toolhead', None)
		self.virtual_sdcard = self.printer.lookup_object('virtual_sdcard', None)

	def handle_disconnect(self):
		self.status = 'off'

	def get_state(self, eventtime):
		return ({
			"status": self.get_status(),
			"currentTool": self.manager.tools.get_extruder_index(self.toolhead.extruder) if self.toolhead else None,
		})

	def get_status(self):
		status = self.status

		if self.printer.is_shutdown:
			return 'off'

		if self.gcode.is_processing_data:
			status = 'busy'

		if self.virtual_sdcard and self.virtual_sdcard.current_file:
			status = 'printing'

		return status


class JobState:
	def __init__(self, manager):
		self.manager = manager
		self.printer = manager.printer
		self.virtual_sdcard = None
		self.printer.register_event_handler("klippy:ready", self.handle_ready)

	def handle_ready(self):
		self.virtual_sdcard = self.printer.lookup_object('virtual_sdcard', None)

	def get_state(self, eventtime):
		if self.virtual_sdcard and self.virtual_sdcard.current_file:
			return dict(self.virtual_sdcard.get_status(), name=os.path.basename(self.virtual_sdcard.current_file.name))

		return None


class Manager:
	def __init__(self, config):
		self.config = config
		self.printer = config.get_printer()

		self.gcode_macro = self.printer.try_load_module(config, 'gcode_macro')

		if config.get('abort_gcode', None) is not None:
			self.abort_gcode = self.gcode_macro.load_template(config, 'abort_gcode')

		self.reactor = self.printer.get_reactor()

		self.gcode = self.printer.lookup_object('gcode')
		self.printer.register_event_handler("gcode:response", self.handle_gcode_response)

		self.state = State(self)
		self.tools = ToolState(self)
		self.move = MoveState(self)
		self.heat = HeatState(self)
		self.fans = FanState(self)
		self.sensors = SensorState(self)

		self.job = JobState(self)

		self.process_mutex = self.reactor.mutex()

		self.broadcast_queue = Queue()
		self.broadcast_thread = threading.Thread(target=self.broadcast_loop)
		self.broadcast_thread.start()

	def broadcast_loop(self):
		while True:
			state = self.broadcast_queue.get(True)
			if state:
				WebSocketHandler.broadcast(state)

	def handle_gcode_response(self, msg):
		self.broadcast_queue.put_nowait({
			"type": "response",
			"payload": msg
		})

	def dispatch(self, target, *args):
		q = JoinableQueue()

		def callback(e):
			q.put(target(*args))
			q.task_done()

		reactor = self.printer.get_reactor()
		reactor.register_async_callback(callback)

		q.join()
		return q.get()

	def process_gcode(self, gcode):
		responses = []

		with self.process_mutex:
			with self.gcode.get_mutex():
				self.gcode._process_commands(gcode.split('\n'))

		return responses

	def get_state(self, eventtime):
		return ({
			"state": self.state.get_state(eventtime),
			"tools": self.tools.get_state(eventtime),
			"fans": self.fans.get_state(eventtime),
			"heat": self.heat.get_state(eventtime),
			"move": self.move.get_state(eventtime),
			"job": self.job.get_state(eventtime),
		})


class KlipperWebControl:
	def __init__(self, config):
		self.config = config
		self.printer = self.config.get_printer()

		self.address = self.config.get('address', "127.0.0.1")
		self.port = self.config.getint("port", 4444)
		self.manager = Manager(self.config)
		self.app = tornado.web.Application([
			("/bed_mesh/height_map", HeightMapHandler, {"manager": self.manager}),
			(r"/files/(.*)", MachineFileHandler, {"manager": self.manager}),
			("/ws", WebSocketHandler, {"manager": self.manager}),
		], cookie_secret=base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes))

		self.thread = None
		self.ioloop = None
		self.http_server = None

		self.handle_ready()
		self.printer.register_event_handler("klippy:ready", self.handle_ready)
		self.printer.register_event_handler("klippy:disconnect", self.handle_disconnect)

	def handle_ready(self):
		if not self.thread or not self.thread.is_alive:
			self.thread = threading.Thread(target=self.spawn)
			self.thread.start()

	def handle_disconnect(self):
		if self.ioloop:
			self.ioloop.stop()

		if self.http_server:
			self.http_server.stop()

	def spawn(self):
		logging.info("HTTP starting at http://%s:%s", self.address, self.port)
		self.http_server = tornado.httpserver.HTTPServer(self.app, max_buffer_size=500 * 1024 * 1024)
		self.http_server.listen(self.port)
		self.ioloop = tornado.ioloop.IOLoop.current()
		self.ioloop.start()
		logging.info("KWC stopped.")


def load_config(config):
	return KlipperWebControl(config)
