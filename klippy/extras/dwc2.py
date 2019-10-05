import logging
import json
import threading
import kinematics.extruder
from multiprocessing import Process, Queue

import tornado.web
import tornado.gen
import base64
import uuid
import os
import datetime
import re
import time
import util
import shutil
import serial
import psutil
import math


class DWC2:
  def __init__(self, config):

    self.klipper_ready = False
    self.last_state = 'O'
    self.popup = None
    self.message = None
    self.serial = serial.Serial('/tmp/printer', 250000, timeout=0.050)
    #	get config
    self.config = config
    self.address = config.get('listen_adress', "127.0.0.1")
    self.port = config.getint("listen_port", 4711)
    self.webpath = config.get('web_path', "dwc2/web")
    self.printername = config.get('printer_name', "Klipper")
    #	klippy objects
    self.current_tool = -1
    self.bed_mesh = None
    self.printer = config.get_printer()
    self.reactor = self.printer.get_reactor()
    self.gcode = self.printer.lookup_object('gcode')
    self.configfile = self.printer.lookup_object('configfile').read_main_config()
    self.kinematics = None
    self.heaters = None
    self.toolhead = None
    self.fan = None
    self.extruders = None
    self.heater_bed = None
    self.chamber = None
    self.sdcard = None
    #	gcode execution needs
    self.gcode_queue = []  # containing gcode user pushes from dwc2
    self.gcode_reply = []  # contains the klippy replys
    self.klipper_macros = []
    self.gcode.dwc_lock = False
    self.gcode.register_respond_callback(
      self.gcode_response)  # if thers a gcode reply, phone me -> see fheilmans its missing in master
    #	once klipper is ready start pre_flight function - not happy with this. If klipper fails to launch -> no web if?
    self.printer.register_event_handler("klippy:ready", self.handle_ready)
    self.printer.register_event_handler("klippy:disconnect", self.shutdown)
    self.start_time = time.time()
    #	grab stuff from config file
    self.klipper_config = self.printer.get_start_args()['config_file']
    self.sdpath = self.configfile.getsection("virtual_sdcard").get("path", None)
    self.sdpath = os.path.normpath(os.path.expanduser(self.sdpath))
    if not self.sdpath:
      logging.error("DWC2 failed to start, no sdcard configured")
      return
    self.kin_name = self.configfile.getsection("printer").get("kinematics")
    self.web_root = self.sdpath + "/" + self.webpath
    if not os.path.isfile(self.web_root + "/" + "index.html"):
      logging.error("DWC2 failed to start, no webif found in " + self.web_root)
      return
    # host temperature store
    self.host_temp_sensor = config.get("host_temp_sensor", "cpu-thermal")
    self.host_temp_min = 100
    self.host_temp_max = 0
    # max speed store
    self.max_speed = 0
    self.last_xpos = None
    self.last_ypos = None
    # manage client sessions
    self.sessions = {}
    self.status = {}
    self.file_infos = {}  # just read files once
    self.dwc2()
    logging.basicConfig(level=logging.DEBUG)

  #	function once reactor calls, once klipper feels good
  def handle_ready(self):
    #	klippy related
    self.current_tool = 0
    self.bed_mesh = self.printer.lookup_object('bed_mesh', None)
    self.chamber = self.printer.lookup_object('temperature_fan chamber', None)
    self.heater_bed = self.printer.lookup_object('heater_bed', None)
    self.fan = self.printer.lookup_object('fan', None)
    self.sdcard = self.printer.lookup_object('virtual_sdcard', None)
    self.heaters = self.printer.lookup_object('heater')
    self.toolhead = self.printer.lookup_object('toolhead', None)
    self.kinematics = self.toolhead.get_kinematics()
    self.extruders = kinematics.extruder.get_printer_extruders(self.printer)

    # 	print data for tracking layers during print
    self.print_data = {}  # printdata/layertimes etc
    self.klipper_ready = True
    self.get_klipper_macros()
    #	registering command
    self.gcode.register_command('M292', self.cmd_M292,
                                desc="okay button in DWC2")

  #	reactor calls this on klippy restart
  def shutdown(self):
    #	kill the thread here
    logging.info("DWC2 shuting down - as klippy is shutdown")
    self.ioloop.stop()
    self.http_server.stop()
    self.sessions = {}

  ##
  #	Webserver and related
  ##
  #	launch webserver
  def dwc2(self):
    def tornado_logger(req):
      fressehaltn = []
      fressehaltn = ["/favicon.ico", "/rr_status?type=1", "/rr_status?type=2", "/rr_status?type=3", "/rr_reply"]
      values = [str(time.time())[-8:], req.request.remote_ip, req.request.method, req.request.uri]
      if req.request.uri not in fressehaltn:
        logging.info("DWC2:" + " - ".join(values))  # bind this to debug later

    def launch_tornado(application):
      # time.sleep(10)	#	delay startup so dwc2 can timeout
      logging.info("DWC2 starting at: http://" + str(self.address) + ":" + str(self.port))
      self.http_server = tornado.httpserver.HTTPServer(application, max_buffer_size=500 * 1024 * 1024)
      self.http_server.listen(self.port)
      self.ioloop = tornado.ioloop.IOLoop.current()
      self.ioloop.start()

    def debug_console(self):
      logging.debug("Start debbug console:\n")
      import pdb;
      pdb.set_trace()

    #
    cookie_secret = base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes)  # random cookie
    # define the threading aplication
    application = tornado.web.Application(
      [
        tornado.web.url(r"/css/(.*)", tornado.web.StaticFileHandler, {"path": self.web_root + "/css/"}),
        tornado.web.url(r"/js/(.*)", tornado.web.StaticFileHandler, {"path": self.web_root + "/js/"}),
        tornado.web.url(r"/fonts/(.*)", tornado.web.StaticFileHandler, {"path": self.web_root + "/fonts/"}),
        tornado.web.url(r"/(rr_.*)", self.req_handler, {"web_dwc2": self}),
        tornado.web.url(r"/.*", self.dwc_handler, {"p_": self.web_root}, name="main"),
      ],
      cookie_secret=cookie_secret,
      log_function=tornado_logger)
    self.tornado = threading.Thread(target=launch_tornado, args=(application,))
    self.tornado.daemon = True
    self.tornado.start()

    dbg = threading.Thread(target=debug_console, args=(self,))

  # dbg.start()
  # the main webpage to serve the client browser itself
  class dwc_handler(tornado.web.RequestHandler):

    def initialize(self, p_):
      self.web_root = p_

    def get(self):
      def index():
        rq_path = self.web_root + "/index.html"
        self.render(rq_path)

      if self.request.uri == "/":  # redirect ti index.html(dwc2)
        index()
      elif ".htm" in self.request.uri:  # covers others like dwc1
        self.render(self.web_root + self.request.uri)
      elif ".json" in self.request.uri:  # covers dwc1 settingsload
        if os.path.isfile(self.web_root + self.request.uri):
          pass
        else:
          self.write({"err": 1})
      elif os.path.isfile(self.web_root + self.request.uri):
        with open(self.web_root + self.request.uri, "rb") as f:
          self.write(f.read())
          self.finish()

      else:
        logging.warn("DWC2 - unhandled request in dwc_handler: " + self.request.uri + " redirecting to index.")
        index()

  # for handling request dwc2 is sending
  class req_handler(tornado.web.RequestHandler):

    def initialize(self, web_dwc2):

      self.web_dwc2 = web_dwc2
      self.repl_ = {"err": 1}

    @tornado.gen.coroutine
    def get(self, *args):

      if self.request.remote_ip not in self.web_dwc2.sessions.keys() and "rr_connect" not in self.request.uri and self.request.remote_ip != '127.0.0.1':
        #	response 408 timeout to force the webif reload after klippy restarts us
        self.clear()
        self.set_status(408)
        self.finish()
        return

      # dwc connect request
      if "rr_connect" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_connect(self)
      #	there is no rr_configfile so return empty
      elif "rr_configfile" in self.request.uri:
        self.repl_ = {"err": 0}
      elif "rr_config" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_config()
      #	filehandling - delete files/folders
      elif "rr_delete" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_delete(self)
      #	disconnect
      elif "/rr_disconnect" in self.request.uri:
        self.repl_ = {"err": 0}
      #	filehandling . download
      elif "rr_download" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_download(self)
      #	filehandling - dirlisting
      elif "rr_filelist" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_filelist(self)
      #	filehandling - dirlisting for dwc 1
      elif "rr_files" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_files(self)
      #	filehandling - fileinfo / gcodeinfo
      elif "rr_fileinfo" in self.request.uri:
        self.repl_ = yield self.web_dwc2.rr_fileinfo(self)
      #	gcode request
      elif "rr_gcode" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_gcode(self)
        return
      #	filehandling - dircreation
      elif "rr_mkdir" in self.request.uri:
        self.web_dwc2.rr_mkdir(self)
        return
      elif "rr_move" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_move(self)
      #	gcode reply
      elif "rr_reply" in self.request.uri:
        self.web_dwc2.rr_reply(self)
        return
      #	status replys
      elif "rr_status" in self.request.uri:

        if not self.web_dwc2.klipper_ready:
          self.web_dwc2.rr_status(0)
        else:
          # there are 3 types of status requests:
          t_ = int(self.get_argument('type'))
          self.web_dwc2.rr_status(t_)

        self.repl_ = self.web_dwc2.status

      if self.repl_ == {"err": 1}:
        logging.warn("DWC2 - unhandled ?GET? " + self.request.uri)

      try:
        if self.repl_:
          self.write(json.dumps(self.repl_))
      except Exception as e:
        logging.warn("DWC2 - error in write: " + str(e))
      #	if noones consuming klippers serial data -> flush it
      if self.web_dwc2.serial.in_waiting >= 2000:
        self.web_dwc2.serial.reset_input_buffer()

    def post(self, *args):

      #	filehandling - uploads
      if "rr_upload" in self.request.uri:
        self.repl_ = self.web_dwc2.rr_upload(self)

      try:
        self.write(json.dumps(self.repl_))
      except Exception as e:
        logging.warn("DWC2 - error in write: " + str(e))

    def decode_argument(self, value, name=None):
      return value.encode('UTF-8') if isinstance(value, unicode) else value

  ##
  #	All the crazy shit dc42 fiddled together in c
  ##
  #	dwc rr_connect
  def rr_connect(self, web_):

    #	better error?
    repl_ = {
      "err": 0,
      "sessionTimeout": 8000,  # config value?
      "boardType": "unknown"  # has klippy this data?
    }

    user_cookie = web_.request.headers.get("Cookie")
    user_ip = web_.request.remote_ip

    self.sessions[user_ip] = user_cookie

    return repl_

  #	dwc rr_config
  def rr_config(self):

    try:
      max_acc = self.toolhead.max_accel
      max_vel = self.toolhead.max_velocity
      rails_ = self.kinematics.rails
      extru_ = self.extruders
    except Exception as e:
      max_acc = []
      max_vel = []
      rails_ = []
      extru_ = []
    ax_ = [[], []]
    for r_ in rails_:
      min_pos, max_pos = r_.get_range()
      ax_[0].append(min_pos)
      ax_[1].append(max_pos)

    repl_ = {
      "axisMins": [x for x in ax_[0]],
      "axisMaxes": [x for x in ax_[1]],
      "accelerations": [max_acc for x in ax_[0]],
      "currents": [0 for x in ax_[0]] + [0 for ex_ in extru_ if ex_ is not None],
      # can we fetch data from tmc drivers here ?
      "firmwareElectronics": util.get_cpu_info(),
      "firmwareName": "Klipper",
      "firmwareVersion": self.printer.get_start_args()['software_version'],
      "dwsVersion": self.printer.get_start_args()['software_version'],
      "firmwareDate": "2018-12-24b1",  # didnt get that from klippy
      "idleCurrentFactor": 30,
      "idleTimeout": 30,
      "minFeedrates": [5 for x in ax_[0]] + [5 for ex_ in extru_ if ex_ is not None],
      "maxFeedrates": [max_vel for x in ax_[0]] + [min(75, max_vel) for ex_ in extru_ if ex_ is not None]
      # unitconversion ?
    }

    return repl_

  #	simple dir/fileremover
  def rr_delete(self, web_):

    #	lazymode_
    path_ = self.sdpath + web_.get_argument('name').replace("0:", "")

    if os.path.isdir(path_):
      shutil.rmtree(path_)

    if os.path.isfile(path_):
      os.remove(path_)

    if path_ in self.file_infos.keys():
      self.file_infos.pop(path_, None)

    return {'err': 0}

  #	dwc rr_download - lacks logging
  def rr_download(self, web_):

    path_ = self.sdpath + web_.get_argument('name').replace("0:", "")

    #	override for config file
    if "/sys/" in path_ and "config.g" in web_.get_argument('name').replace("0:", ""):
      path_ = self.klipper_config

    #   override for extension config files
    if "/sys/" in path_ and "config_" in web_.get_argument('name').replace("0:", ""):
      filename = web_.get_argument('name').replace("0:", "").replace("/sys/", "").replace("config_",
                                                                                          "printer_").replace(".g",
                                                                                                              ".cfg")
      path_ = os.path.dirname(self.klipper_config) + "/" + filename

    #	handle heigthmap
    if 'heightmap.csv' in path_:
      repl_ = self.get_heigthmap()
      if repl_:
        with open(path_, "w") as f:
          for line in repl_:
            f.write(line + '\n')

    if os.path.isfile(path_):

      #	handles regular files
      web_.set_header('Content-Type', 'application/force-download')
      web_.set_header('Content-Disposition', 'attachment; filename=%s' % os.path.basename(path_))

      with open(path_, "rb") as f:
        web_.write(f.read())

    else:
      return {"err": 1}

  #	dwc rr_files - dwc1 thing
  def rr_files(self, web_):

    path_ = self.sdpath + web_.get_argument('dir').replace("0:", "")

    repl_ = {
      "dir": web_.get_argument('dir'),
      "first": web_.get_argument('first', 0),
      "files": [],
      "next": 0,
      "err": 0
    }

    #	if rrf is requesting directory, it has to be there.
    if not os.path.exists(path_):
      os.makedirs(path_)

    #	append elements to files list matching rrf syntax
    for el_ in os.listdir(path_):
      el_path = path_ + "/" + el_
      repl_['files'].append("*" + str(el_) if os.path.isdir(el_path) else str(el_))

    return repl_

  #	dwc rr_filelist
  def rr_filelist(self, web_):

    path_ = self.sdpath + web_.get_argument('dir').replace("0:", "")

    #	creating the infoblock
    repl_ = {
      "dir": web_.get_argument('dir'),
      "first": web_.get_argument('first', 0),
      "files": [],
      "next": 0
    }

    #	if rrf is requesting directory, it has to be there.
    if not os.path.exists(path_):
      os.makedirs(path_)

    #	append elements to files list matching rrf syntax
    for el_ in os.listdir(path_):
      el_path = path_ + "/" + str(el_)
      repl_['files'].append({
        "type": "d" if os.path.isdir(el_path) else "f",
        "name": str(el_),
        "size": os.stat(el_path).st_size,
        "date": datetime.datetime.utcfromtimestamp(os.stat(el_path).st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
      })

    #	add klipper macros as virtual files
    if "/macros" in web_.get_argument('dir').replace("0:", ""):
      for macro_ in self.klipper_macros:
        repl_['files'].append({
          "type": "f",
          "name": macro_,
          "size": 1,
          "date": time.strftime("%Y-%m-%dT%H:%M:%S")
        })

    #	virtual config file
    elif "/sys" in web_.get_argument('dir').replace("0:", ""):

      repl_['files'].append({
        "type": "f",
        "name": "config.g",
        "size": os.stat(self.klipper_config).st_size,
        "date": datetime.datetime.utcfromtimestamp(os.stat(self.klipper_config).st_mtime).strftime(
          "%Y-%m-%dT%H:%M:%S")
      })

      configPath = os.path.dirname(self.klipper_config)
      configFiles = [filename for filename in os.listdir(configPath) if filename.startswith("printer_")]
      for file in configFiles:
        repl_['files'].append({
          "type": "f",
          "name": file.replace("printer_", "config_").replace(".cfg", ".g"),
          "size": os.stat(configPath + "/" + file).st_size,
          "date": datetime.datetime.utcfromtimestamp(os.stat(configPath + "/" + file).st_mtime).strftime(
            "%Y-%m-%dT%H:%M:%S")
        })

    return repl_

  #	dwc fileinfo - getting gcode info
  @tornado.gen.coroutine
  def rr_fileinfo(self, web_):

    try:
      path_ = self.sdpath + web_.get_argument('name').replace("0:", "")
    except:
      path_ = self.sdcard.current_file.name

    if not os.path.isfile(path_):
      return {"err": 1}

    if not path_ in self.file_infos.keys():
      dict_ = Queue()
      proc_ = Process(target=self.parse_gcode_file, args=(path_, dict_))
      proc_.start()
      proc_.join(5)
      self.file_infos[path_] = dict_.get()

    return self.file_infos[path_]

  #	dwc rr_gcode - append to gcode_queue
  def rr_gcode(self, web_):
    # handover to klippy as: [ "G28", "M114", "G1 X150", etc... ]
    gcodes = str(web_.get_argument('gcode')).replace('0:', '').replace('"', '').split("\n")

    rrf_commands = {
      'G10': self.cmd_G10,  # set heaters temp
      'M0': self.cmd_M0,  # cancel SD print
      'M24': self.cmd_M24,  # resume sdprint
      'M32': self.cmd_M32,  # start sdprint
      'M98': self.cmd_M98,  # run macro
      'M106': self.cmd_M106,  # set fan
      'M140': self.cmd_M140,  # set bedtemp (limit to 0 mintemp)
      'M290': self.cmd_M290,  # set babysteps
      'M999': self.cmd_M999  # issue restart
    }

    #	allow - set heater, cancelprint, set bed, ,pause, resume, set fan, set speedfactor, set extrusion multipler, babystep, ok in popup
    midprint_allow = [
      'G10', 'M0', 'M24', 'M25', 'M106', 'M140', 'M220', 'M221', 'M290', 'M292',
      'HELP', 'STATUS', 'GET_POSITION',
      'BLTOUCH_DEBUG',
      'PROBE_TEMP',
      'PAUSE', 'RESUME',
      'RESPOND',
      'QUERY_PROBE', 'QUERY_ENDSTOPS', 'QUERY_FILAMENT_SENSOR',
      'SET_PIN', 'SET_HEATER_TEMPERATURE', 'SET_PRESSURE_ADVANCE', 'SET_RETRACTION', 'SET_VELOCITY_LIMIT',
      'SET_GCODE_OFFSET'
      'DUMP_TMC', 'SET_TMC_CURRENT', 'SET_TMC_FIELD'
    ]

    #	Handle emergencys - just do it now
    for code in gcodes:
      if 'M112' in code:
        self.cmd_M112(0)

    #	start to prepare commands
    while gcodes:

      #	parse commands - still magic. Wheres the original function in klipper?
      params = self.parse_params(gcodes.pop(0))

      #	defaulting to original
      handover = params['#original']

      #	handle toolchanges
      if re.match('^T(-)?\d$', params['#command']):
        self.current_tool = abs(int(params['T']))
        if params['#command'] == 'T-1':
          continue

      #	prevent midprint accidents
      stat_ = self.get_printer_status()
      if stat_ in ['P', 'D', 'R'] and params['#command'] not in midprint_allow:
        web_.write(json.dumps({'buff': 0, 'err': 0}))
        # self.set_popup(msg='<b>' + params['#command'] + " not allowed during Print.</b>")
        # self.set_message(msg=params['#command'] + ' not allowed during print.')
        continue

      #	rewrite rrfs specials to klipper readable format
      if params['#command'] in rrf_commands.keys():
        func_ = rrf_commands.get(params['#command'])
        handover = func_(params)
        if handover == 0:
          self.gcode_reply.append("ok\n")

      #	if we set things directly in klipper we dond need to pipe gcodes
      if handover:
        self.gcode_queue.append(handover)

    web_.write(json.dumps({'buff': 1, 'err': 0}))
    web_.finish()
    self.reactor.register_callback(self.gcode_reactor_callback)

  #	dwc rr_move - backup printer.cfg
  def rr_move(self, web_):

    if "/sys/" in web_.get_argument('old').replace("0:", "") and "config.g" in web_.get_argument('old').replace(
      "0:", ""):
      src_ = self.klipper_config
      dst_ = self.klipper_config + ".backup"

    else:
      src_ = self.sdpath + web_.get_argument('old').replace("0:", "")
      dst_ = self.sdpath + web_.get_argument('new').replace("0:", "")

    try:
      shutil.copyfile(src_, dst_)
    except Exception as e:
      return {"err": 1}

    return {"err": 0}

  #	dwc rr_mkdir
  def rr_mkdir(self, web_):

    path_ = self.sdpath + web_.get_argument('dir').replace("0:", "").replace(' ', '_')

    if not os.path.exists(path_):
      os.makedirs(path_)
      return {'err': 0}

    return {'err': 1}

  #	dwc rr_reply - fetces gcodes
  def rr_reply(self, web_):
    while self.gcode_reply:
      msg = self.gcode_reply.pop(0).replace("!!", "Error: ").replace("//", "Warning: ")
      web_.write(msg)

  #	dwc rr_status
  def rr_status(self, rr_status_type):
    now = self.reactor.monotonic() + 0.25
    gcode_stats = self.gcode.get_status(now)

    request_speed = gcode_stats['speed'] / 60 * gcode_stats['speed_factor']
    # calc max speed
    if self.toolhead:
      if self.last_xpos is not None and self.last_ypos is not None:
        max_speed = 0
        wx = self.last_xpos - gcode_stats['move_xpos']
        wy = self.last_ypos - gcode_stats['move_ypos']
        w = math.sqrt(wx ** 2 + wy ** 2)
        if w > 0:
          w = w / 2  # half way to acc
          t = math.sqrt(2 * (w / self.toolhead.max_accel))
          max_speed = t * self.toolhead.max_accel
          if max_speed > request_speed:
            max_speed = request_speed

          if max_speed > self.toolhead.max_velocity:
            max_speed = self.toolhead.max_velocity

        if max_speed > self.max_speed:
          self.max_speed = max_speed

      self.last_xpos = gcode_stats['move_xpos']
      self.last_ypos = gcode_stats['move_ypos']

    #   clear status output
    self.status = {}

    self.status.update({
      "status": self.get_printer_status(),
      "coords": {
        "xyz": [],
        "machine": [],
        "extr": [],
      },
      "speeds": {
        "requested": request_speed,  # Current speed
        "top": self.max_speed  # not available on klipper
      },
      "currentTool": self.current_tool if self.current_tool >= 0 else 0,  # current tool number
      "params": {
        "atxPower": 0,  # powersupply status
        "speedFactor": gcode_stats['speed_factor'] * 100,  # speed multiplier
        "babystep": gcode_stats['homing_zpos'],  # act. babysteps
        # "extrFactors": [gcode_stats['extrude_factor'] * 100],                   # extruder multiplier
        "extrFactors": [],  # extruder multiplier
      },
      "seq": len(self.gcode_reply),
      "sensors": {
        "probeValue": gcode_stats['base_zpos'],  # test value
        # "fanRPM": 0,
      },
      "temps": {  # placeholder for temps
        "current": [],  # placeholder for current temps
        "state": [],  # placeholder for stats
        "names": [],  # placeholder for names
        "tools": {  # placeholder for tools
          "active": [],
          "standby": [],
        },
        "extra": [
          {
            "name": "MCU",
            "temp": self.get_host_temp()
          }
        ]
      },
      "time": time.time() - self.start_time
    })

    if self.toolhead:
      self.status["coords"].update({
        "axesHomed": self.get_axes_homed(),  # home status per axes
        "xyz": self.toolhead.get_position()[:3],  # user coordinates
        "machine": [0, 0, 0],  # machine coordinates
        # "extr": self.toolhead.get_position()[3:]                # extruder coordinates
      })

    fan_stats = []
    if self.fan:
      fan_stats = [self.fan.get_status(now)]  # TODO: better solution

    self.status["params"].update({
      "fanPercent": [fan_['speed'] * 100 for fan_ in fan_stats],  # fan speed
    })

    if (rr_status_type >= 2):
      self.status["params"].update({
        "fanNames": ["" for fan_ in fan_stats],  # TODO: fan names
      })

    temp_currents = []
    temp_states = []
    temp_names = []
    temp_pins = []
    temp_numbers = 0

    if self.heater_bed:
      #	// 0: off, 1: standby, 2: active, 3: fault (same for bed)
      heater_bed_status = self.heater_bed.get_status(now)
      state = 0
      if (heater_bed_status['target'] > 0):
        state = 2

      self.status["temps"].update({
        "bed": {
          "current": heater_bed_status['temperature'],
          "active": heater_bed_status['target'],
          "state": state,
          "heater": temp_numbers
        }
      })

      temp_currents = temp_currents + [heater_bed_status['temperature']]
      temp_states = temp_states + [state]
      temp_names = temp_names + ["Bed"]
      temp_numbers = temp_numbers + 1

    if self.extruders:
      exNr_ = 0
      for ex_ in self.extruders:
        ex_status = ex_.heater.get_status(now)
        state = 0
        if (ex_status['target'] > 0):
          state = 2

        temp_currents = temp_currents + [ex_status['temperature']]
        temp_states = temp_states + [state]
        temp_names = temp_names + [ex_.name]
        temp_numbers = temp_numbers + 1
        exNr_ = exNr_ + 1

        self.status["temps"]["tools"]["active"].append([ex_status['target']])
        self.status["temps"]["tools"]["standby"].append([0])  # Klipper cannot use standby
        self.status["coords"]["extr"].append(ex_.extrude_pos)
        self.status["params"]["extrFactors"].append(gcode_stats['extrude_factor'] * 100)

    if self.chamber:
      chamber_temp, chamber_target = self.chamber.get_temp(now)

      state = 0
      if (chamber_target > 0 and self.chamber.last_speed_value > 0):
        state = 2
      elif (chamber_target > 0):
        state = 1

      self.status['temps'].update({
        "chamber": {
          "current": chamber_temp,
          "active": chamber_target,
          "state": state,
          "heater": temp_numbers,
        },
        "extra": self.status['temps']['extra'] + [
          {
            "name": "CFS",
            "temp": self.chamber.last_speed_value * 100
          }
        ]
      })

      temp_currents = temp_currents + [chamber_temp]
      temp_states = temp_states + [state]
      temp_names = temp_names + ["Chamber"]

    if self.heaters is not None:
      sensors = sorted(self.heaters.get_gcode_sensors())
      for i in range(temp_numbers, len(sensors)):
        gcode_id, sensor = sensors[i]
        cur, target = sensor.get_temp(now)
        self.status['temps'].update({
          "extra": self.status['temps']['extra'] + [
            {
              "name": gcode_id,
              "temp": cur
            }
          ]
        })

    for current_ in temp_currents:
      self.status["temps"]["current"].append(current_)

    for state_ in temp_states:
      self.status["temps"]["state"].append(state_)

    if (rr_status_type >= 2):
      for name_ in temp_names:
        self.status["temps"]["names"].append(name_)

    if self.message:
      self.status.update(
        self.message
      )

    if self.popup:
      self.status.update(
        self.popup
      )

    if (rr_status_type == 2):
      ex_min_extrude_temp = max(ex_.heater.min_extrude_temp if ex_ is not None else 0 for ex_ in
                                self.extruders) if self.extruders else 0
      max_temp = max(ex_.heater.max_temp if ex_ is not None else 0 for ex_ in
                     self.extruders) if self.extruders else 0

      self.status.update({
        "coldExtrudeTemp": ex_min_extrude_temp,
        "coldRetractTemp": ex_min_extrude_temp,
        "compensation": "None",
        "controllableFans": len(fan_stats),
        "tempLimit": max_temp,
        "endstops": 4088,  # TODO: calc entstops
        "firmwareName": "Klipper",
        "geometry": self.kin_name,
        "axes": len(self.get_axes_homed()),
        "totalAxes": len(self.get_axes_homed()) + len(self.extruders),
        "axisNames": "XYZ",
        "volumes": 1,
        "mountedVolumes": 1,
        "name": self.printername,
        "probe": {
          "threshold": 100,
          "height": 0,
          "type": 8
        },
        "tools": [],
      })

      if self.extruders:
        index_ = 0
        for ex_ in self.extruders:
          # if ex_.shared_heater:
          #    heaterIndex = index_ + 1
          # else:
          heaterIndex = index_ + 1

          self.status["tools"].append({
            "number": index_,
            "name": ex_.name,
            "heaters": [heaterIndex],  # TODO: Can Klipper has more heaters per tool
            "drives": [index_],  # TODO: Can Klipper has more drives per tool
            "axisMap": [1],
            "fans": 1,
            "filament": "",
            "offsets": [0, 0, 0]
          })
          index_ = index_ + 1

      if self.get_host_temp() > 0:
        self.status.update({
          "mcutemp": {
            "min": self.host_temp_min,
            "cur": self.get_host_temp(),
            "max": self.host_temp_max
          },
        })

      # TODO: Power in voltages
      # "vin": {
      #    "min": 23.9,
      #    "cur": 24.1,
      #    "max": 24.3
      # }

    elif (rr_status_type == 3):
      extrRaw = 0
      for ex_ in self.extruders:
        extrRaw = extrRaw + ex_.extrude_pos

      extrRaw = extrRaw - self.print_data.get('extr_start', 1)

      self.status.update({
        "currentLayer": self.print_data.get('curr_layer', 1),
        "currentLayerTime": self.print_data.get('curr_layer_dur', 1),
        "extrRaw": [extrRaw],
        "fractionPrinted": round(self.sdcard.get_status(now).get('progress', 0), 1),  # percent done
        "filePosition": self.sdcard.file_position,
        "firstLayerDuration":
          self.print_data.get('firstlayer_dur', 1) if self.print_data.get('firstlayer_dur', 0) > 0
          else self.print_data.get('curr_layer_dur', 1),
        "firstLayerHeight": self.file_infos.get('running_file', {}).get('firstLayerHeight', 0.2),
        "printDuration": round(self.print_data.get('print_dur', 1), 1),
        "warmUpDuration": round(self.print_data.get('heat_time', 1), 1),
        "timesLeft": {
          "file": round(self.print_data['tleft_file'], 1) if 'tleft_file' in self.print_data else 0,
          "filament": round(self.print_data['tleft_filament'], 1) if 'tleft_filament' in self.print_data else 0,
          "layer": round(self.print_data['tleft_layer'], 1) if 'tleft_layer' in self.print_data else 0,
        },
      })

  #	dwc rr_upload - uploading files to sdcard
  def rr_upload(self, web_):

    path_ = self.sdpath + web_.get_argument('name').replace("0:", "").replace(' ', '_')
    dir_ = os.path.dirname(path_)

    ret_ = {"err": 1}

    if not os.path.exists(dir_):
      os.makedirs(dir_)

    #	klipper config ecxeption
    if "/sys/" in path_ and "config.g" in web_.get_argument('name'):
      path_ = self.klipper_config

    #	klipper extend config ecxeption
    if "/sys/" in path_ and "config_" in web_.get_argument('name'):
      filename = web_.get_argument('name').replace("0:", "").replace("/sys/", "").replace("config_",
                                                                                          "printer_").replace(".g",
                                                                                                              ".cfg")
      path_ = os.path.dirname(self.klipper_config) + "/" + filename

    with open(path_.replace(" ", "_"), 'w') as out:
      out.write(web_.request.body)

    if os.path.isfile(path_):
      ret_ = {"err": 0}

    return ret_

  ##
  #	Gcode execution related stuff
  ##

  #	rrf G10 command - set heaterstemp
  def cmd_G10(self, params):

    temp = max(max(self.gcode.get_float('S', params, 0.), self.gcode.get_float('R', params, 0.)), 0)
    command_ = str("M104 T%d S%0.2f" % (int(params['P']), float(temp)))
    return command_

  #	rrf M0 - cancel print from sd
  def cmd_M0(self, params):

    self.sdcard.must_pause_work = True  # pause print -> sdcard postion is saved in virtual sdcard
    self.sdcard.file_position = 0  # reset fileposition
    self.sdcard.work_timer = None  # reset worktimer
    self.sdcard.current_file = None  #
    self.printfile = None
    self.cancel_macro()
    #	let user define a cancel/pause print macro`?
    return 0

  # 	rrf M24 - start/resume print from sdcard
  def cmd_M24(self, params):
    if self.sdcard.file_position > 0:
      self.resume_macro()
    else:
      self.print_data = {
        "print_start": time.time(),
        "print_dur": 0,
        "extr_start": sum(self.toolhead.get_position()[3:]),
        "firstlayer_dur": 0,
        "curr_layer": 1,
        "curr_layer_start": 0,
        "curr_layer_dur": 0,
        "heat_time": 0,
        "last_zposes": [self.toolhead.get_position()[3] for n_ in range(10)],
        "last_switch_z": 0,
        "tleft_file": 99999999999,
        "tleft_filament": 99999999999,
        "tleft_layer": 99999999999,
        "layercount": self.file_infos.get('running_file', {}).get('layercount', 1),
        "filament": self.file_infos.get('running_file', {}).get("filament", 1)
      }
      self.reactor.register_callback(self.update_printdata, waketime=self.reactor.monotonic() + 2)
    self.sdcard.cmd_M24(params)
    return 0

  #	rrf M32 - start print from sdcard
  def cmd_M32(self, params):

    #	file dwc1 - 'zzz/simplify3D41.gcode'
    #	file dwc2 - '/gcodes/zzz/simplify3D41.gcode'

    file = '/'.join(params['#original'].split(' ')[1:])
    if '/gcodes/' not in file:  # DWC 1 work arround
      fullpath = self.sdpath + '/gcodes/' + params['#original'].split()[1]
    else:
      fullpath = self.sdpath + file

    #	load a file to scurrent_file if its none
    if not self.sdcard.current_file:
      if os.path.isfile(fullpath):
        self.printfile = open(fullpath, 'rb')  # get file object as klippy would do
        self.printfile.seek(0, os.SEEK_END)
        self.printfile.seek(0)
        self.sdcard.current_file = self.printfile  # set it as current file
        self.sdcard.file_position = 0  # postions / size
        self.sdcard.file_size = os.stat(fullpath).st_size
      else:
        import pdb;
        pdb.set_trace()
        raise 'gcodefile' + fullpath + ' not found'

    self.file_infos['running_file'] = self.rr_fileinfo('knackwurst').result()
    return self.cmd_M24(params)

  #	rrf run macro
  def cmd_M98(self, params):

    path = self.sdpath + "/" + "/".join(params['#original'].split("/")[1:])

    if not os.path.exists(path):
      #	now we know its no macro file
      klipma = params['#original'].split("/")[-1].replace("\"", "")
      if klipma in self.klipper_macros:
        return klipma
      else:
        return 0
    else:
      #	now we know its a macro from dwc
      with open(path) as f:
        lines = f.readlines()

      for line in [x.strip() for x in lines]:
        self.gcode_queue.append(line)

      return 0

  #	rrf M106 translation to klipper scale
  def cmd_M106(self, params):

    if float(params['S']) < .05:
      command = str("M107")
    else:
      command = str(params['#command'] + " S" + str(int(float(params['S']) * 255)))

    return command

  #	fo ecxecuting m112 now!
  def cmd_M112(self, params):
    self.printer.invoke_shutdown('Emergency Stop from DWC 2')

  #	set heatbed
  def cmd_M140(self, params):

    temp = max(self.gcode.get_float('S', params, 0.), 0)
    command_ = str("M140 S%d" % (int(temp)))
    return command_

  #	setting babysteps:
  def cmd_M290(self, params):

    if self.get_axes_homed()[2] == 0:
      self.gcode_reply.append('!! Only idiots try to babystep withoung homing !!')
      return 0

    mm_step = self.gcode.get_float('Z', params, None)
    if not mm_step: mm_step = self.gcode.get_float('S', params, None)  # DWC 1 workarround
    params = self.parse_params('SET_GCODE_OFFSET MOVE=1 Z_ADJUST%0.2f' % mm_step)
    self.gcode.cmd_SET_GCODE_OFFSET(params)
    self.gcode_reply.append('Z adjusted by %0.2f' % mm_step)

    return 0

  #	Ok button in DWC webif
  def cmd_M292(self, params):
    self.popup = None

  #	rrf restart command
  def cmd_M999(self, params):
    # needs0 otherwise the printer gets restarted after emergency buttn is pressed
    return "RESTART"

  #	launch custom cancel macro
  def cancel_macro(self):
    macro_path = self.sdpath + '/macros/' + 'cancel.g'

    if os.path.isfile(macro_path):

      with open(macro_path) as f:
        lines = f.readlines()

      for line in [x.strip() for x in lines]:
        self.gcode_queue.append(line)

    elif 'CANCEL_PRINT' in self.klipper_macros:
      self.gcode_queue.append('CANCEL_PRINT')

    if self.gcode_queue:
      self.reactor.register_callback(self.gcode_reactor_callback)

  #	getting response by callback
  def gcode_response(self, msg):

    if self.klipper_ready:
      if re.match('(B|T\d):\d+.\d\s/\d+.\d+', msg): return  # filters tempmessages during heatup

    self.gcode_reply.append(msg)

  #	recall for gcode ecxecution is needed ( threadsafeness )
  def gcode_reactor_callback(self, eventtime):
    #	if user adds commands return the callback
    if self.gcode.dwc_lock:
      return

    ack_needers = ["G0", "G1", "G28", "G90", "G91", "M0", "M24", "M25", "M83", "M84", "M104", "M112", "M117",
                   "M140", "M141", "DUMP_TMC", "FIRMWARE_RESTART" "", "SET_PIN", "STEPPER_BUZZ"]
    lowers = ["DUMP_TMC", "ENDSTOP_PHASE_CALIBRATE", "FORCE_MOVE", "PID_CALIBRATE", "SET_HEATER_TEMPERATURE",
              "SET_PIN", "SET_PRESSURE_ADVANCE", "STEPPER_BUZZ"]

    self.gcode.dwc_lock = self.gcode.is_processing_data = True

    while self.gcode_queue:

      handle_ = self.gcode_queue.pop(0)
      params = self.parse_params(handle_)

      if params['#command'] in lowers:
        params = self.parse_params(handle_, low_=True)

      try:
        handler = self.gcode.gcode_handlers.get(params['#command'], self.gcode.cmd_default)
        handler(params)
      except Exception as e:
        self.gcode_reply.append("")
        logging.error("failed: " + params['#command'] + str(e))
        # self.set_popup(msg=params['#command'] + ' resulted with: ' + str(e))
        # self.set_message(msg="Warning: " + params['#command'] + ' resulted with: ' + str(e))
        time.sleep(1)  # not beautiful but webif ignores errors on button commands otherwise
        self.gcode_reply.append("!! " + str(e) + "\n")
      else:
        logging.error("passed: " + params['#command'])
        if params['#command'] in ack_needers or params['#command'] in self.klipper_macros:
          self.gcode_reply.append("")  # pseudo ack

    self.gcode.dwc_lock = self.gcode.is_processing_data = False

  #	launch individual pause macro
  def pause_macro(self):
    #	store old XYZ position somewhere ?
    macro_path = self.sdpath + '/macros/' + 'pause.g'

    if os.path.isfile(macro_path):

      with open(macro_path) as f:
        lines = f.readlines()

      for line in [x.strip() for x in lines]:
        self.gcode_queue.append(line)

    elif 'PAUSE_PRINT' in self.klipper_macros:
      self.gcode_queue.append('PAUSE_PRINT')

    if self.gcode_queue:
      self.reactor.register_callback(self.gcode_reactor_callback)

  #	parses gcode commands into params -took from johns work
  def parse_params(self, line, low_=False):
    logging.error(line)
    args_r = re.compile('([A-Z_]+|[A-Z*/])')
    if low_:
      line = origline = line.strip().lower()
    else:
      line = origline = line.strip()
    cpos = line.find(';')
    if cpos >= 0:
      line = line[:cpos]
    # Break command into parts
    parts = args_r.split(line.upper())[1:]
    params = {parts[i]: parts[i + 1].strip()
              for i in range(0, len(parts), 2)}
    params['#original'] = origline
    if parts and parts[0] == 'N':
      # Skip line number at start of command
      del parts[:2]
    if not parts:
      # Treat empty line as empty command
      parts = ['', '']
    params['#command'] = cmd = parts[0] + parts[1].strip()

    return params

  #	launch individual resume macro
  def resume_macro(self):

    macro_path = self.sdpath + '/macros/' + 'resume.g'

    if os.path.isfile(macro_path):

      with open(macro_path) as f:
        lines = f.readlines()

      for line in [x.strip() for x in lines]:
        self.gcode_queue.append(line)

    elif 'RESUME_PRINT' in self.klipper_macros:
      self.gcode_queue.append('RESUME_PRINT')

    if self.gcode_queue:
      self.reactor.register_callback(self.gcode_reactor_callback)

  ##
  #	Helper functions getting/parsing data
  ##

  #	transforming klippers heigthmap into dwc readable format
  def get_heigthmap(self):
    #	translates the klipper heighthmap to dwc format
    #	lets asume user is intelegent enough to probe with correct probe offset
    def calc_mean(matrix_):

      matrix_tolist = []
      for line in matrix_:
        matrix_tolist += line

      return float(sum(matrix_tolist)) / len(matrix_tolist)

    def calc_stdv(matrix_):
      from math import sqrt
      matrix_tolist = []
      for line in matrix_:
        matrix_tolist += line

      mean = float(sum(matrix_tolist)) / len(matrix_tolist)
      return sqrt(float(reduce(lambda x, y: x + y, map(lambda x: (x - mean) ** 2, matrix_tolist))) / len(
        matrix_tolist))  # Stackoverflow - liked that native short solution

    #

    if self.bed_mesh:

      hmap = []
      self.configfile.getsection("virtual_sdcard").get("path", None)
      z_matrix = self.bed_mesh.calibrate.probed_z_table
      mesh_data = self.bed_mesh.z_mesh  # see def print_mesh in bed_mesh.py line 572

      meane_ = round(calc_mean(z_matrix), 3)
      stdev_ = round(calc_stdv(z_matrix), 3)

      hmap.append('RepRapFirmware height map file v2 generated at ' + str(
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M')) + ', mean error ' + str(
        meane_) + ', deviation ' + str(stdev_))
      hmap.append('xmin,xmax,ymin,ymax,radius,xspacing,yspacing,xnum,ynum')
      xspace_ = (mesh_data.mesh_x_max - mesh_data.mesh_x_min) / mesh_data.mesh_x_count
      yspace_ = (mesh_data.mesh_y_max - mesh_data.mesh_y_min) / mesh_data.mesh_y_count
      hmap.append(str(mesh_data.mesh_x_min) + ',' + str(mesh_data.mesh_x_max) + ',' + str(
        mesh_data.mesh_y_min) + ',' + str(mesh_data.mesh_y_max) + \
                  ',-1.00,' + str(xspace_) + ',' + str(yspace_) + ',' + str(mesh_data.mesh_x_count) + ',' + str(
        mesh_data.mesh_y_count))

      for line in z_matrix:
        red_by_offset = map(lambda x: x - meane_, line)
        hmap.append('  ' + ',  '.join(map(str, red_by_offset)))

      return hmap

    return

  #	delivering printer states, webif can use
  def get_printer_status(self):

    #	case 'F': return 'updating';
    #	case 'O': return 'off';
    #	case 'H': return 'halted';
    #	case 'D': return 'pausing';
    #	case 'S': return 'paused';
    #	case 'R': return 'resuming';
    #	case 'P': return 'processing';	?printing?
    #	case 'M': return 'simulating';
    #	case 'B': return 'busy';
    #	case 'T': return 'changingTool';
    #	case 'I': return 'idle';

    state = 'I'

    if 'Printer is ready' != self.printer.get_state_message():
      self.klipper_ready = False
      return 'O'

    if self.gcode.is_processing_data:
      state = 'B'

    if self.sdcard and self.sdcard.current_file:
      if self.sdcard.must_pause_work:
        state = 'D' if self.sdcard.work_timer else 'S'
      elif self.sdcard.current_file and self.sdcard.work_timer:
        state = 'P'

    #	handle switching from pausing/processing to paused
    if (self.last_state == 'D' or self.last_state == 'P') and state == 'S':
      self.pause_macro()

    self.last_state = state
    return state

  #	import klipper macros as virtual files
  def get_klipper_macros(self):

    for key_ in self.gcode.gcode_help.keys():

      if self.gcode.gcode_help[key_] == "G-Code macro":
        self.klipper_macros.append(key_.upper())

  #	same what gcode.py is doing
  def get_axes_homed(self):
    #	self.toolhead.get_next_move_time() - self.reactor.monotonic()
    homed = []
    if self.kinematics:
      for rail in self.kinematics.rails:

        if rail.is_motor_enabled():
          homed.append(1)
        else:
          homed.append(0)
    if not homed:
      homed = [0, 0, 0]
    return homed

  def get_host_temp(self):
    sensors = psutil.sensors_temperatures()
    if (len(sensors) > 0 and
      sensors[self.host_temp_sensor] and
      sensors[self.host_temp_sensor][0] and
      sensors[self.host_temp_sensor][0].current):
      t = float(sensors[self.host_temp_sensor][0].current)
      if self.host_temp_min > t:
        self.host_temp_min = t

      if self.host_temp_max < t:
        self.host_temp_max = t

      return t
    else:
      return 0

  #	read and parse gcode files
  def parse_gcode_file(self, path_, dict_):

    #	looks complicated but should be good maintainable
    #	the heigth of all objects - regex
    objects_h = [
      '\sZ\\d+.\\d*',  # kisslicer
      '',  # Slic3r
      '\sZ\\d+.\\d*',  # S3d
      'G1\sZ\d*\.\d*',  # Slic3r PE
      'G1\sZ\d*\.\d*',  # PrusaSlicer
      '\sZ\\d+.\\d*',  # Cura
      '\sZ\d+.\d{3}'  # ideamaker
    ]

    #	heigth of the first layer
    first_h = [
      'first_layer_thickness_mm\s=\s\d+\.\d+',  # kisslicers setting
      '; first_layer_height =',  # Slic3r
      '\sZ\\d+.\\d*',  # Simplify3d
      'G1\sZ\d*\.\d*',  # Slic3r PE
      '; first_layer_height =',  # PrusaSlicer
      '\sZ\\d+.\\d\s',  # Cura
      ';LAYER:0\n;Z:\d+.\d{3}'  # ideamaker
    ]

    #	the heigth of layers
    layer_h = [
      'layer_thickness_mm\s=\s\d+\.\d+',  # kisslicer
      '',  # Slic3r
      ';\s+layerHeight.*',  # S3d
      '; layer_height = \d.\d+',  # Slic3r PE
      '; layer_height = \d.\d+',  # PrusaSlicer
      ';Layer height: \d.\d+',  # Cura
      ';Z:\d+.\d{3}'  # ideamaker
    ]
    #	slicers estimate print time
    time_e = [
      '\s\s\d*\.\d*\sminutes',  # Kisslicer
      '; estimated printing time',  # Slic3r
      ';\s+Build time:.*',  # S3d
      '\d+h?\s?\d+m\s\d+s',  # Slic3r PE
      '\d+h?\s?\d+m\s\d+s',  # PrusaSlicer
      ';TIME:\\d+',  # Cura
      ';Print Time:\s\d+\.?\d+'  # ideamaker
    ]
    #	slicers filament usage
    filament = [
      'Ext [\#]?1 [ ]?=.*mm',  # Kisslicer
      ';.*filament used =',  # Slic3r
      ';.*Filament length: \d+.*\(',  # S3d
      '.*filament\sused\s=\s.*mm',  # Slic3r PE ; filament used =
      '.*filament\sused\s\[mm\]\s=\s.*',  # PrusaSlicer ; filament used [mm] =
      ';Filament used: \d*.\d+m',  # Cura
      ';Material#1 Used:\s\d+\.?\d+'  # ideamaker
    ]
    #	slicernames
    slicers = [
      'KISSlicer',
      '^Slic3r$',
      'Simplify3D\(R\).*',
      'Slic3r Prusa Edition\s.*\so',
      'PrusaSlicer\s.*\so',
      'Cura_SteamEngine.*',
      'ideaMaker\s([0-9]*\..*,)'
    ]
    #
    meta = {"slicer": "Slicer is not implemented"}

    def calc_time(in_):
      if in_ == -1: return in_
      # import pdb; pdb.set_trace()
      h_str = re.search(re.compile('(\d+(\s)?hours|\d+(\s)?h)'), in_)
      m_str = re.search(re.compile('(([0-9]*\.[0-9]+)\sminutes|\d+(\s)?m)'), in_)
      s_str = re.search(re.compile('(\d+(\s)?seconds|\d+(\s)?s)'), in_)
      dursecs = 0
      if h_str:
        dursecs += float(max(re.findall('([0-9]*\.?[0-9]+)', ''.join(h_str.group())))) * 3600
      if m_str:
        dursecs += float(max(re.findall('([0-9]*\.?[0-9]+)', ''.join(m_str.group())))) * 60
      if s_str:
        dursecs += float(max(re.findall('([0-9]*\.?[0-9]+)', ''.join(s_str.group()))))
      if dursecs == 0:
        dursecs = float(max(re.findall('([0-9]*\.?[0-9]+)', in_)))

      return dursecs

    #	get 4k lines from file
    with open(path_, 'rb') as f:
      cont_ = f.readlines()  # gimme the whole file
    int_ = cont_[:2000] + cont_[-2000:]  # build up header and footer
    pile = " ".join(int_)  # build a big pile for regex
    #	determine slicer
    sl = -1

    for regex in slicers:
      #	resource gunner ?
      if re.compile(regex).search(pile):
        # import pdb; pdb.set_trace()
        meta['slicer'] = re.search(re.compile(regex), pile).group()
        sl = slicers.index(regex)
        break
    #	only grab metadata if we found a slicer
    if sl > -1:
      # import pdb; pdb.set_trace()
      if objects_h[sl] != "":
        try:
          matches = re.findall(objects_h[sl], pile)
          meta['objects_h'] = max([float(mat_) for mat_ in re.findall("\d*\.\d*", ' '.join(matches))])
        except:
          pass
      if layer_h[sl] != "":
        try:
          matches = re.findall(layer_h[sl], pile)
          meta['layer_h'] = min([float(mat_) for mat_ in re.findall("\d*\.\d*", ' '.join(matches))])
        except:
          pass
      if first_h[sl] != "":
        try:
          matches = re.findall(first_h[sl], pile)
          meta['first_h'] = min([float(mat_) for mat_ in re.findall("\d*\.\d*", ' '.join(matches))])
        except:
          pass
      if time_e[sl] != "":
        try:
          matches = re.findall(time_e[sl], pile)
          meta['time_e'] = calc_time(max(matches))  # bring time to seconds
        except:
          pass
      if filament[sl] != "":
        try:
          matches = re.findall(filament[sl], pile)
          meta['filament'] = max([float(mat_) for mat_ in re.findall("\d*\.\d*", ' '.join(matches))])
          meta['filament'] = (meta['filament'], meta['filament'] * 1000)[sl == 5]  # cura is in m -> translate
        except:
          pass

    else:
      self.gcode_reply.append("Your Slicer is not yet implemented.")

    #	put it in rrf format
    repl_ = {
      "size": int(os.stat(path_).st_size),
      "lastModified": str(
        datetime.datetime.utcfromtimestamp(os.stat(path_).st_mtime).strftime("%Y-%m-%dT%H:%M:%S")),
      "height": float(meta.get("objects_h", 1)),
      "firstLayerHeight": meta.get("first_h", 1),
      "layerHeight": float(meta.get("layer_h", 1)),
      "printTime": int(meta.get("time_e", 1)),  # in seconds
      "filament": [float(meta.get("filament", 1))],  # in mm
      "generatedBy": str(meta.get("slicer", "<< Slicer not implemented >>")),
      "fileName": '0:' + str(path_).replace(self.sdpath, ''),
      "layercount": (float(meta.get("objects_h", 1)) - meta.get("first_h", 1)) / float(
        meta.get("layer_h", 1)) + 1,
      "err": 0
    }

    dict_.put(repl_)

  #	setting message
  def set_message(self, msg='msg'):
    self.message = {
      "output": {
        "message": msg
      }
    }

  #	setting up a popup
  def set_popup(self, title='Action failed ', msg='Some command just failed.', timeout=0):
    self.popup = {"output": {
      "msgBox": {
        "mode": 2,
        "title": title + str(time.time()),
        "msg": msg,
        "timeout": timeout,
        "controls": 0
      }
    }  # ok is M292
    }

  #	permanent loop if we are in printing state
  def update_printdata(self, eventtime):
    if self.get_printer_status() in ['S', 'P', 'D']:
      self.reactor.register_callback(self.update_printdata, waketime=self.reactor.monotonic() + 0.6)
    else:
      return
    now = self.reactor.monotonic()

    gcode_stats = self.gcode.get_status(now)
    #	first out, actual in - a rolling list
    self.print_data['last_zposes'].pop(0)
    self.print_data['last_zposes'].append(gcode_stats['last_zpos'])
    self.print_data['filament_used'] = max(sum(self.toolhead.get_position()[3:]) - self.print_data['extr_start'], 1)

    if self.print_data['curr_layer_start'] == 0 \
      and self.print_data['filament_used'] > 50:
      #	now we know firstlayer started + heating ended
      self.print_data.update({
        'curr_layer_start': time.time(),
        'heat_time': time.time() - self.print_data.get('print_start', 0),
        'last_switch_z': gcode_stats['last_zpos']
      })

    else:
      if self.print_data['last_switch_z'] != gcode_stats['last_zpos'] and self.print_data['filament_used'] > 50 \
        and max(self.print_data.get('last_zposes', [2])) / min(
        self.print_data.get('last_zposes', [1])) == 1:

        if self.print_data['firstlayer_dur'] == 0:
          self.print_data['firstlayer_dur'] = self.print_data['curr_layer_dur']
        self.print_data.update({
          'curr_layer_start': time.time(),
          'curr_layer_dur': 0,
          'curr_layer': self.print_data['curr_layer'] + 1,
          'last_switch_z': gcode_stats['last_zpos']
        })

    if self.print_data['curr_layer_start'] == 0:
      self.print_data['curr_layer_dur'] = 0
    else:
      self.print_data['curr_layer_dur'] = time.time() - self.print_data['curr_layer_start']

    self.print_data['print_dur'] = time.time() - self.print_data['print_start']
    #	timeleft calc
    t_elapsed = self.print_data['print_dur']
    file_done = self.sdcard.get_status(now).get('progress', 0)
    self.print_data['tleft_file'] = (1 - file_done) * t_elapsed / max(.0001, file_done)
    #
    layer_done = self.print_data['curr_layer']
    self.print_data['tleft_layer'] = (self.print_data['layercount'] - layer_done) * t_elapsed / layer_done
    #
    f_need = sum(self.print_data['filament'])
    f_used = max(sum(self.toolhead.get_position()[3:]) - self.print_data['extr_start'], 1)
    self.print_data['tleft_filament'] = (f_need - f_used) * t_elapsed / f_used




def load_config(config):
  return DWC2(config)
