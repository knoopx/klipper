#
# This module is handling request from DuetWebControl (http://reprap.org/wiki/Duet_Web_Control)
#     Tornado webserver is needed to run page
#       Note: Tornado version 4.5 is required!
#         - install Tornado using pip ( $pip install tornado==4.5 )
#         - or download from https://github.com/tornadoweb/tornado/tree/branch4.5
#           and use environment variable 'export TORNADO_PATH=<path to tornado folder>'
#     Create SSL cert:
#         - openssl req -newkey rsa:2048 -new -nodes -x509 -days 3650 -keyout <path>/key.pem -out <path>/cert.pem
#

import analyse_gcode
import tornado.ioloop
import tornado.web
import time
import sys
import os
import errno
import threading
import json
import re
import logging
import util


class GuiStats:
    def __init__(self, config):
        self.printer = printer = config.get_printer()
        self.logger = logging
        # required modules
        self.reactor = printer.get_reactor()
        self.gcode = gcode = printer.lookup_object('gcode')
        self.toolhead = printer.lookup_object('toolhead')
        self.babysteps = printer.try_load_module(config, 'babysteps')
        self.sd = printer.try_load_module(config, "virtual_sdcard")
        # variables
        self.starttime = time.time()
        self.curr_state = 'PNR'
        self.name = config.getsection('printer').get(
            'name', default="Klipper printer")
        self.cpu_info = util.get_cpu_info()
        self.sw_version = printer.get_start_arg('software_version', 'Unknown')
        self.auto_report = False
        self.auto_report_timer = None
        # Print statistics
        self.layer_stats = []
        self.warmup_time = None
        self.print_time = self.last_time = .0
        self.first_layer_start = None
        self.firstLayerHeight = .0
        # register callbacks
        printer.register_event_handler('vsd:status', self.sd_status)
        printer.register_event_handler(
            'gcode:layer_changed', self.layer_changed)
        printer.register_event_handler("klippy:ready", self.handle_ready)
        printer.register_event_handler("klippy:connect", self._handle_connect)
        printer.register_event_handler(
            "klippy:shutdown", self._handle_shutdown)
        printer.register_event_handler("klippy:halt", self._handle_shutdown)
        printer.register_event_handler(
            "klippy:disconnect", self._handle_disconnect)
        # register control commands
        for cmd in ["GUISTATS_GET_ARGS",
                    "GUISTATS_GET_CONFIG", "GUISTATS_GET_STATUS",
                    "GUISTATS_GET_SD_INFO",
                    "GUISTATS_AUTO_REPORT"]:
            gcode.register_command(
                cmd, getattr(self, 'cmd_' + cmd), when_not_ready=True)
        printer.add_object("gui_stats", self)
        self.logger.info("GUI STATS LOADED!")

    def get_current_state(self):
        return self.curr_state

    # ================================================================================
    # Commands
    def cmd_GUISTATS_GET_ARGS(self, params):
        dump = json.dumps(self.printer.get_start_args())
        self.gcode.respond(dump)

    def cmd_GUISTATS_GET_CONFIG(self, params):
        dump = json.dumps(self.get_config_stats())
        self.gcode.respond(dump)

    def cmd_GUISTATS_GET_STATUS(self, params):
        _type = self.gcode.get_int("TYPE", params,
                                   default=1, minval=1, maxval=3)
        stats = self.get_status_stats(_type)
        dump = json.dumps(stats)
        self.gcode.respond(dump)

    def cmd_GUISTATS_GET_SD_INFO(self, params):
        dump = json.dumps(self.sd.get_status(0, True))
        self.gcode.respond(dump)

    def cmd_GUISTATS_AUTO_REPORT(self, params):
        self.auto_report = self.gcode.get_int("ENABLE", params,
                                              default=self.auto_report, minval=0, maxval=1)
        if self.auto_report and self.auto_report_timer is None:
            self.auto_report_timer = self.reactor.register_timer(
                self._auto_temp_report_cb, self.reactor.NOW)
        elif not self.auto_report and self.auto_report_timer is not None:
            self.reactor.unregister_timer(self.auto_report_timer)
            self.auto_report_timer = None
        self.gcode.respond("Auto reporting %s ok" %
                           ['diabled', 'enabled'][self.auto_report])

    # ================================================================================
    # Callbacks
    def _auto_temp_report_cb(self, eventtime):
        #self.logger.debug("AUTO Report @ %s" % eventtime)
        stats = self.get_status_stats(3)
        dump = json.dumps(stats)
        self.gcode.respond('GUISTATS_REPORT='+dump)
        return eventtime + .250

    def _handle_shutdown(self):
        self.curr_state = "H"

    def _handle_disconnect(self):
        self.curr_state = "C"

    def handle_ready(self):
        self.curr_state = "I"
        if self.auto_report and self.auto_report_timer is None:
            self.auto_report_timer = self.reactor.register_timer(
                self._auto_temp_report_cb, self.reactor.NOW)
        elif not self.auto_report and self.auto_report_timer is not None:
            self.reactor.unregister_timer(self.auto_report_timer)
            self.auto_report_timer = None

    def _handle_connect(self):
        self.curr_state = "B"

    def sd_status(self, status):
        if status == 'pause':
            self.curr_state = "S"
        elif status == 'start':
            self.curr_state = "P"
            self.last_time = self.toolhead.get_estimated_print_time()
        elif status == 'error' or status == "stop":
            self.curr_state = "I"
        elif status == 'done':
            toolhead = self.toolhead
            toolhead.wait_moves()  # TODO: remove?
            self.curr_state = "I"
        elif status == 'loaded':
            self.layer_stats = []
            self.warmup_time = None
            self.print_time = .0

    def layer_changed(self, change_time, layer, height, *args):
        # 1st call is "heating ready"
        self.logger.debug("Layer changed cb: time %s, layer %s, h=%s" % (
            change_time, layer, height))
        try:
            start_time = self.layer_stats[-1]['end time']
        except IndexError:
            # 1st layer change
            start_time = change_time
            self.warmup_time = self.print_time  # warmup ready
        self.layer_stats.append(
            {'start time': start_time,
             'layer time': (change_time - start_time),
             'end time': change_time})

    # ================================================================================
    # Statistics
    def get_config_stats(self):
        printer = self.printer
        _extrs = printer.extruder_get()
        toolhead = self.toolhead
        kinematic = toolhead.get_kinematics()
        rails = kinematic.get_rails()
        motor_off_time = printer.lookup_object('idle_timeout').idle_timeout
        currents = []
        max_feedrates = []
        accelerations = []
        axisMins = []
        axisMaxes = []
        for rail in rails:
            _min, _max = rail.get_range()
            steppers = rail.get_steppers()
            for idx, stp in enumerate(steppers):
                axisMins.append(_min)
                axisMaxes.append(_max)
                get_current = getattr(stp.driver, "get_current", None)
                if get_current is not None:
                    currents.append(int(get_current()))
                else:
                    currents.append(-1)
                _vel, _accel = stp.get_max_velocity()
                max_feedrates.append(int(_vel))
                accelerations.append(int(_accel))
        for idx, e in _extrs.items():
            _vel, _accel = e.get_max_velocity()
            max_feedrates.append(int(_vel))
            accelerations.append(int(_accel))
            get_current = getattr(e.stepper.driver, "get_current", None)
            if get_current is not None:
                currents.append(int(get_current()))
            else:
                currents.append(-1)
        config = {
            "err": 0,
            "axisMins": axisMins,
            "axisMaxes": axisMaxes,
            "accelerations": accelerations,
            "currents": currents,
            "firmwareElectronics": self.cpu_info,
            "firmwareName": "Klipper",
            "firmwareVersion": self.sw_version,
            "idleCurrentFactor": 0.0,
            "idleTimeout": motor_off_time,
            "minFeedrates": [0.00] * (len(max_feedrates) + len(_extrs)),
            "maxFeedrates": max_feedrates
            }
        return config

    def get_status_stats(self, _type=1):
        toolhead = self.toolhead
        states = {
            False: 0,
            True: 2
        }
        curr_extruder = toolhead.get_extruder()
        curr_pos = toolhead.get_position()
        fans = [fan.last_fan_value * 100.0 for n, fan in
                self.printer.lookup_objects("fan")]
        heatbed = self.printer.lookup_object('heater bed', None)
        _heaters = [h for n, h in self.printer.lookup_objects("heater")]
        #total_htrs = len(_heaters) + 1
        _extrs = self.printer.extruder_get()

        # _type == 1 is always included
        status_block = {
            "status": self.curr_state,
            "seq": 0,
            "coords": {
                "axesHomed": toolhead.kin.is_homed(),
                "extr": [e.extrude_pos
                         for i, e in _extrs.items()],
                "xyz": curr_pos[:3],
            },
            "currentTool": curr_extruder.index,
            "params": {
                "atxPower": 0,
                "fanPercent": fans,
                "speedFactor": self.gcode.speed_factor * 60. * 100.0,
                "extrFactors": [e.get_extrude_factor(procent=True) for i, e in _extrs.items()],
                "babystep": float("%.3f" % self.babysteps.babysteps),
            },
            "sensors": {
                # "fanRPM": 0,
            },
            "time": (time.time() - self.starttime),
            "temps": {}
        }

        #bed_tilt = self.printer.lookup_object('bed_tilt', default=None)
        #if bed_tilt:
        #    probe_x, probe_y, probeValue = bed_tilt.get_adjust()
        #    status_block['sensors']['probeValue'] = probeValue
        #    status_block['sensors']['probeSecondary'] = [probe_x, probe_y]

        heatbed_add = 1 if heatbed is not None else 0
        num_extruders = len(_extrs)
        total_heaters = num_extruders + heatbed_add
        htr_current = [.0] * total_heaters
        # HS_off = 0, HS_standby = 1, HS_active = 2, HS_fault = 3, HS_tuning = 4
        htr_state = [3] * total_heaters
        extr_states = {
            "active": [],
            "standby": [[.0]] * num_extruders
        }
        for name, extr in _extrs.items():
            htr = extr.get_heater()
            status = htr.get_status(0)
            index = extr.get_index() + heatbed_add
            htr_current[index] = float("%.2f" % status['temperature'])
            htr_state[index] = states[(status['target'] > 0.0)]
            extr_states['active'].append([float("%.2f" % htr.target_temp)])
        # Tools target temps
        status_block["temps"].update({'tools': extr_states})

        if heatbed is not None:
            status = heatbed.get_status(0)
            htr_current[0] = float("%.2f" % status['temperature'])
            htr_state[0] = states[(status['target'] > 0.0)]
            # Heatbed target temp
            status_block["temps"].update({
                "bed": {
                    "active": float("%.2f" % status['target']),
                    "heater": 0,
                },
            })

        chamber = self.printer.lookup_object('chamber', default=None)
        if chamber is not None:
            current, target = chamber.get_temp()
            status_block["temps"].update({
                "chamber": {
                    "active": float("%.2f" % target),
                    "heater": len(htr_current),
                },
            })
            htr_current.append(float("%.2f" % current))
            htr_state.append(states[chamber.is_fan_active()])
        '''
        cabinet = self.printer.lookup_object('cabinet', default=None)
        if cabinet is not None:
            current, target = cabinet.get_temp()
            status_block["temps"].update( {
                "cabinet": {
                    "active"  : float("%.2f" % target),
                    "heater"  : len(htr_current),
                },
            } )
            htr_current.append(current)
            htr_state.append(states[target > 0.0])
        '''

        status_block["temps"].update({
            "current": htr_current,
            # 0: off, 1: standby, 2: active, 3: fault (same for bed)
            "state": htr_state,
        })

        if _type >= 2:
            max_temp = 0.0
            cold_temp = 0.0
            if hasattr(curr_extruder, "get_heater"):
                heater = curr_extruder.get_heater()
                max_temp = heater.max_temp
                cold_temp = heater.min_extrude_temp
                if heater.min_extrude_temp_disabled:
                    cold_temp = 0.0
            endstops_hit = 0
            for idx, state in enumerate(toolhead.get_kinematics().is_homed()):
                endstops_hit |= (state << idx)
            status_block.update({
                "coldExtrudeTemp": cold_temp,
                "coldRetractTemp": cold_temp,
                "tempLimit": max_temp,
                "endstops": endstops_hit,
                "firmwareName": "Klipper",
                "geometry": toolhead.kin.name,  # cartesian, coreXY, delta
                "axes": 3,                # Subject to deprecation - may be dropped in RRF 1.20
                "volumes": 1,                # Num of SD cards
                "mountedVolumes": 1,                # Bitmap of all mounted volumes
                "name": self.name,
                #"probe": {
                #    "threshold" : 500,
                #    "height"    : 2.6,
                #    "type"      : 1
                #},
                #"mcutemp": { # Not available on RADDS
                #    "min": 26.4,
                #    "cur": 30.5,
                #    "max": 43.4
                #},
                #"vin": { # Only DuetNG (Duet Ethernet + WiFi)
                #    "min": 10.4,
                #    "cur": 12.3,
                #    "max": 12.5
                #},
            })

            tools = []
            for key, extr in _extrs.items():
                values = {
                    "number": extr.index,
                    "name": extr.name,
                    "heaters": [extr.heater.index + 1],
                    "drives": [3+extr.index],
                    #"filament" : "N/A",
                }
                tools.append(values)
            status_block["tools"] = tools

        if _type >= 3:
            lstat = self.layer_stats
            current_time = toolhead.get_estimated_print_time()
            printing_time = self.print_time
            if self.curr_state == "P":
                # Update time while printing
                printing_time += current_time - self.last_time
                self.last_time = current_time
                self.print_time = printing_time
            curr_layer = len(lstat)
            try:
                layer_time_curr = current_time - lstat[-1]['end time']
            except IndexError:
                layer_time_curr = printing_time
            try:
                first_layer_time = lstat[1]['layer time']
            except IndexError:
                first_layer_time = layer_time_curr

            warmup_time = self.warmup_time
            if warmup_time is None:
                # Update warmup time
                warmup_time = printing_time

            # Print time estimations
            progress = self.sd.get_progress()
            remaining_time_file = 0.
            if progress > 0:
                remaining_time_file = (
                    printing_time / progress) - printing_time

            # Used filament amount
            remaining_time_fila = 0.
            '''
            fila_total = sum(e for e in info['filament'])
            if fila_total > 0:
                fila_used = sum(e.raw_filament for i, e in _extrs.items())
                fila_perc = (fila_used / fila_total)
                remaining_time_fila = (printing_time / fila_perc) - printing_time
            '''

            # Layer statistics
            remaining_time_layer = 0.
            '''
            num_layers = 0
            layerHeight = info['layerHeight']
            firstLayerHeight = info['firstLayerHeight']
            if layerHeight > 0:
                num_layers = int( (info["height"] - firstLayerHeight +
                                  layerHeight) / layerHeight )
            if num_layers:
                proc = curr_layer / num_layers
                if proc > 0:
                    remaining_time_layer = (printing_time / proc) - printing_time
            '''

            '''
            self.logger.debug(
                "TYPE3: layer %s, time: %s, 1st time: %s, warmup: %.2f, progress: %.2f, "
                "file_time: %.2f, printing_time: %f" % (
                curr_layer, layer_time_curr, first_layer_time, warmup_time, progress,
                remaining_time_file, printing_time))
            #'''

            # Fill status block
            status_block.update({
                "progressType": 0,  # 1 = layer, else file progress
                "currentLayer": curr_layer,
                "currentLayerTime": layer_time_curr,
                # How much filament would have been printed without extrusion factors applied
                "extrRaw": [float("%0.1f" % e.raw_filament)
                            for i, e in _extrs.items()],
                "fractionPrinted": float("%.1f" % (progress * 100.)),

                "firstLayerDuration": first_layer_time,
                "SKIP_ firstLayerHeight": float("%.1f" % self.firstLayerHeight),
                "printDuration": printing_time,
                "warmUpDuration": float("%.1f" % warmup_time),

                "timesLeft": {
                    "file": float("%.1f" % remaining_time_file),
                    "filament": [float("%.1f" % remaining_time_fila)],
                    "layer": float("%.1f" % remaining_time_layer),
                }
            })
        # self.logger.debug("%s", json.dumps(status_block, indent=4))
        return status_block


class ParseError(Exception):
    pass


ANALYSED_GCODE_FILES = {}


def analyse_gcode_file(filepath):
    # Set initial values
    info = {
        "slicer": "unknown",
        "height": 0,
        "layerHeight": 0,
        "firstLayerHeight": 0,
        "filament": [],
        "buildTime": 0
    }
    if filepath is None:
        return info
    if filepath in ANALYSED_GCODE_FILES:
        return ANALYSED_GCODE_FILES[filepath]
    elif os.path.join("gcode", filepath) in ANALYSED_GCODE_FILES:
        return ANALYSED_GCODE_FILES[filepath]
    absolutecoord = True
    last_position = .0
    try:
        with open(filepath, 'rb') as f:
            #f.seek(0, os.SEEK_END)
            #fsize = f.tell()
            f.seek(0)
            # find used slicer
            slicer = None
            for idx in range(100):
                line = f.readline().strip()
                if "Simplify3D" in line:  # S3D
                    slicer = "Simplify3D"
                elif "Slic3r" in line:  # slic3r
                    slicer = "Slic3r"
                elif ";Sliced by " in line:  # ideaMaker
                    slicer = "ideaMaker"
                elif "; KISSlicer" in line:  # KISSlicer
                    slicer = "KISSlicer"
                elif ";Sliced at: " in line:  # Cura(old)
                    slicer = "Cura (OLD)"
                elif ";Generated with Cura" in line:  # Cura(new)
                    slicer = "Cura"
                elif "IceSL" in line:
                    slicer = "IceSL"
                elif "CraftWare" in line:
                    slicer = "CraftWare"
                if slicer is not None:
                    break
            # Stop if slicer is not detected!
            if slicer is None:
                raise ParseError("Cannot detect slicer")
            info["slicer"] = slicer
            # read header
            layerHeight = None
            firstLayerHeightPercentage = None
            firstLayerHeight = None
            # read footer and find object height
            f.seek(0)
            args_r = re.compile('([A-Z_]+|[A-Z*/])')
            build_info_r = re.compile('([0-9\.]+)')
            for line in f:
                line = line.strip()
                cpos = line.find(';')
                if cpos == 0:
                    # Try to parse slicer infos
                    if slicer is "Simplify3D":
                        if "Build time" in line:
                            parts = build_info_r.split(line)
                            buildTime = .0
                            offset = 1
                            if " hour " in parts:
                                buildTime += 60. * float(parts[offset])
                                offset += 2
                            if " minutes" in parts:
                                buildTime += float(parts[offset])
                            info["buildTime"] = buildTime * 60.
                        elif "Filament length: " in line:
                            parts = build_info_r.split(line)
                            info["filament"].append(float(parts[1]))
                        elif "layerHeight" in line:
                            parts = build_info_r.split(line)
                            layerHeight = float(parts[1])
                        elif "firstLayerHeightPercentage" in line:
                            parts = build_info_r.split(line)
                            firstLayerHeightPercentage = float(parts[1]) / 100.
                    elif slicer is "Slic3r":
                        if "filament used" in line:
                            parts = build_info_r.split(line)
                            info["filament"].append(float(parts[1]))
                        elif "first_layer_height" in line:
                            # first_layer_height = 100%
                            parts = build_info_r.split(line)
                            firstLayerHeight = float(parts[1])
                            if "%" in line:
                                firstLayerHeightPercentage = firstLayerHeight / 100.
                                firstLayerHeight = None
                        elif "layer_height" in line:
                            parts = build_info_r.split(line)
                            layerHeight = float(parts[1])
                    elif slicer is "Cura":
                        if "Filament used" in line:
                            parts = build_info_r.split(line)
                            info["filament"].append(
                                float(parts[1]) * 1000.)  # Convert m to mm
                        elif "Layer height" in line:
                            parts = build_info_r.split(line)
                            layerHeight = float(parts[1])
                            firstLayerHeight = layerHeight
                    elif slicer is "IceSL":
                        if "z_layer_height_first_layer_mm" in line:
                            parts = build_info_r.split(line)
                            firstLayerHeight = float(parts[1])
                        elif "z_layer_height_mm" in line:
                            parts = build_info_r.split(line)
                            layerHeight = float(parts[1])
                    elif slicer is "KISSlicer":
                        if ";    Ext " in line:
                            parts = build_info_r.split(line)
                            info["filament"].append(float(parts[3]))
                        elif "first_layer_thickness_mm" in line:
                            parts = build_info_r.split(line)
                            firstLayerHeight = float(parts[1])
                        elif "layer_thickness_mm" in line:
                            parts = build_info_r.split(line)
                            layerHeight = float(parts[1])
                    elif slicer is "CraftWare":
                        # encoded settings in gcode file, need to extract....
                        pass
                    continue

                # Remove comments
                if cpos >= 0:
                    line = line[:cpos]
                # Parse args
                parts = args_r.split(line.upper())[1:]
                params = {parts[i]: parts[i+1].strip()
                          for i in range(0, len(parts), 2)}
                # Find object height
                if "G" in params:
                    gnum = int(params['G'])
                    if gnum == 0 or gnum == 1:
                        if "Z" in params:
                            if absolutecoord:
                                last_position = float(params['Z'])
                            else:
                                last_position += float(params['Z'])
                    elif gnum == 90:
                        absolutecoord = True
                    elif gnum == 91:
                        absolutecoord = False

            info["height"] = last_position
            # first layer height
            if layerHeight is not None:
                info["layerHeight"] = float("%.3f" % layerHeight)
            if layerHeight is not None and firstLayerHeightPercentage is not None:
                info["firstLayerHeight"] = float(
                    "%.3f" % (layerHeight * firstLayerHeightPercentage))
            if firstLayerHeight is not None:
                info["firstLayerHeight"] = float("%.3f" % firstLayerHeight)
    except (IOError, ParseError):
        pass
    ANALYSED_GCODE_FILES[filepath] = info
    # logging.info("PARSED: %s" % info)
    return info


"""
Example config sections:

[virtual_sdcard]
path: ~/.octoprint/uploads/

[reprapgui]
name: This is my printer
user: test
password: test
http: 80
; Enable for SSL connection
;https: 443
;cert: ~/ssl/server.crt
;key: ~/ssl/server.key
; Video feed
;feedrate: 1.0
;camera_index: 0
"""

'''
Status info:
? 'C'    // Reading the configuration file - init type
? 'F'    // Flashing a new firmware binary - IGNORE
? 'H'    // Halted
? 'D'    // Pausing / Decelerating - IGNORE?
? 'R'    // Resuming
? 'T'    // Changing tool - IGNORE?
? 'S'    // Paused / Stopped
? 'P'    // Printing
? 'B'    // Busy
: 'I'    // Idle
'''

"""
Usage
  G10 Pnnn Xnnn Ynnn Znnn
Parameters
  Pnnn Tool number - SKIP
  Xnnn X offset - SKIP
  Ynnn Y offset - SKIP
  U,V,Wnnn U, V and W axis offsets - SKIP
  Znnn Z offset - SKIP
"""


try:
    sys.path.append(os.path.normpath(
        os.path.expanduser(os.environ['TORNADO_PATH'])))
except KeyError:
    pass

_PARENT = None
KLIPPER_CFG_NAME = 'klipper_config.cfg'
KLIPPER_LOG_NAME = "klippy.log"


def dict_dump_json(data, logger=None):
    if logger is None:
        logger = logging
    logger.info(json.dumps(data,
                           #sort_keys=True,
                           sort_keys=False,
                           indent=4,
                           separators=(',', ': ')))


class MainHandler(tornado.web.RequestHandler):
    path = None

    def initialize(self, path):
        self.path = path

    # @tornado.web.authenticated
    def get(self):
        self.render(os.path.join(self.path, "reprap.htm"))


class rrHandler(tornado.web.RequestHandler):
    parent = printer = sd_path = logger = None

    def initialize(self, sd_path):
        self.parent = _PARENT
        self.printer = self.parent.printer
        self.sd_path = sd_path
        self.logger = self.parent.logger

    def get(self, path, *args, **kwargs):
        logging.info(path)
        sd_path = self.sd_path
        respdata = {"err": 10}

        # rr_connect?password=XXX&time=YYY
        if "rr_connect" in path:
            respdata["err"] = 0
            #_passwd = self.get_argument('password')
            #if self.parent.passwd != _passwd:
            #    respdata["err"] = 1
            # 0 = success, 1 = wrong passwd, 2 = No more HTTP sessions available
            respdata["sessionTimeout"] = 30000  # ms
            # duetwifi10, duetethernet10, radds15, alligator2, duet06, duet07, duet085, default: unknown
            respdata["boardType"] = "unknown"  # "radds15"

        # rr_disconnect
        elif "rr_disconnect" in path:
            respdata["err"] = 0

        # rr_status?type=XXX
        # http://reprap.org/wiki/RepRap_Firmware_Status_responses
        elif "rr_status" in path:
            _type = int(self.get_argument('type'))
            if _type < 1 or _type > 3:
                _type = 1
            # get status from Klippy
            respdata["err"] = 0
            respdata.update(self.parent.gui_stats.get_status_stats(_type))
            respdata['seq'] += len(self.parent.gcode_resps)

        # rr_gcode?gcode=XXX
        elif "rr_gcode" in path:
            respdata["err"] = 0
            respdata["buff"] = 99999

            gcode = self.get_argument('gcode')
            #self.logger.debug("rr_gcode={}".format(gcode))
            # Clean up gcode command
            gcode = gcode.replace("0:/", "").replace("0%3A%2F", "")

            if "M80" in gcode and self.parent.atx_on is not None:
                # ATX ON
                resp = os.popen(self.parent.atx_on).read()
                self.parent.append_gcode_resp(resp)
                self.logger.info("ATX ON: %s" % resp)
            elif "M81" in gcode and self.parent.atx_off is not None:
                # ATX OFF
                resp = os.popen(self.parent.atx_off).read()
                self.parent.append_gcode_resp(resp)
                self.logger.info("ATX OFF: %s" % resp)
            elif "T-1" in gcode:
                # ignore
                pass
            else:
                try:
                    self.parent.printer_write(gcode)
                except self.parent.gcode.error:
                    respdata["err"] = 1

        # rr_download?name=XXX
        elif "rr_download" in path:
            # Download a specified file from the SD card.
            path = self.get_argument('name').replace(
                "0:/", "").replace("0%3A%2F", "")
            if KLIPPER_CFG_NAME in path:
                path = os.path.abspath(
                    self.printer.get_start_arg('config_file'))
            elif KLIPPER_LOG_NAME in path:
                path = os.path.abspath(
                    self.printer.get_start_arg('logfile'))
            else:
                path = os.path.abspath(os.path.join(sd_path, path))
            # Check if file exists and upload
            if not os.path.exists(path):
                raise tornado.web.HTTPError(404)
            else:
                self.set_header('Content-Type', 'application/force-download')
                self.set_header(
                    'Content-Disposition', 'attachment; filename=%s' % os.path.basename(path))
                try:
                    with open(path, "rb") as f:
                        self.write(f.read())
                except IOError:
                    # raise tornado.web.HTTPError(500)
                    raise tornado.web.HTTPError(404)
                self.finish()
                return

        # rr_delete?name=XXX
        elif "rr_delete" in path:
            # resp: `{"err":[code]}`
            respdata["err"] = 0
            directory = self.get_argument('name').replace(
                "0:/", "").replace("0%3A%2F", "")
            if KLIPPER_CFG_NAME in directory or KLIPPER_LOG_NAME in directory:
                pass
            else:
                directory = os.path.abspath(os.path.join(sd_path, directory))
                #self.logger.debug("delete: absolute path {}".format(directory))
                try:
                    for root, dirs, files in os.walk(directory, topdown=False):
                        for name in files:
                            os.remove(os.path.join(root, name))
                        for name in dirs:
                            os.rmdir(os.path.join(root, name))
                    if os.path.isdir(directory):
                        os.rmdir(directory)
                    else:
                        os.remove(directory)
                except OSError as e:
                    self.logger.error("rr_delete: %s" % (e.strerror,))
                    respdata["err"] = 1

        # rr_filelist?dir=XXX
        elif "rr_filelist" in path:
            '''
            resp: `{"type":[type],"name":"[name]","size":[size],"lastModified":"[datetime]"}`
            resp error: `{"err":[code]}`
                where code is
                    1 = the directory doesn't exist
                    2 = the requested volume is not mounted
            '''
            _dir = self.get_argument('dir')
            respdata["dir"] = _dir
            respdata["files"] = []

            _dir = _dir.replace("0:/", "").replace("0%3A%2F", "")
            path = os.path.abspath(os.path.join(sd_path, _dir))

            if not os.path.exists(path):
                respdata["err"] = 1
            else:
                respdata["err"] = 0
                del respdata["err"]  # err keyword need to be deleted
                for _local in os.listdir(path):
                    if _local.startswith("."):
                        continue
                    filepath = os.path.join(path, _local)
                    if os.path.isfile(filepath):
                        data = {
                            "type": "f",
                            "name": os.path.relpath(filepath, path),
                            "size": os.path.getsize(filepath),
                            "date": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                  time.gmtime(os.path.getmtime(filepath))),
                        }
                        respdata["files"].append(data)
                    elif os.path.isdir(filepath):
                        data = {
                            "type": "d",
                            "name": os.path.relpath(filepath, path),
                            "size": os.path.getsize(filepath),
                            "date": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                  time.gmtime(os.path.getmtime(filepath))),
                        }
                        respdata["files"].append(data)

                # Add printer.cfg into sys list
                if "/sys" in path:
                    cfg_file = os.path.abspath(
                        self.printer.get_start_arg('config_file'))
                    respdata["files"].append({
                        "type": "f",
                        "name": KLIPPER_CFG_NAME,
                        "size": os.path.getsize(cfg_file),
                        "date": time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.gmtime(os.path.getmtime(cfg_file))),
                    })
                    logfile = self.printer.get_start_arg('logfile', None)
                    if logfile is not None:
                        respdata["files"].append({
                            "type": "f",
                            "name": KLIPPER_LOG_NAME,
                            "size": os.path.getsize(logfile),
                            "date": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                  time.gmtime(os.path.getmtime(logfile))),
                        })

        # rr_fileinfo?name=XXX
        elif "rr_fileinfo" in path:
            name = self.get_argument('name', default=None)
            #self.logger.debug("rr_fileinfo: {} , name: {}".format(self.request.uri, name))
            if name is None:
                sd = self.printer.lookup_object('virtual_sdcard')
                try:
                    # current file printed
                    if sd.current_file is not None:
                        path = sd.current_file.name
                    else:
                        raise AttributeError
                except AttributeError:
                    path = None
            else:
                path = self.get_argument('name').replace(
                    "0:/", "").replace("0%3A%2F", "")
                path = os.path.abspath(os.path.join(sd_path, path))
            # info about the requested file
            if path is None or not os.path.exists(path):
                respdata["err"] = 1
            else:
                info = analyse_gcode.analyse_gcode_file(path)
                respdata["err"] = 0
                respdata["size"] = os.path.getsize(path)
                respdata["lastModified"] = \
                    time.strftime("%Y-%m-%dT%H:%M:%S",
                                  time.gmtime(os.path.getmtime(path)))
                respdata["generatedBy"] = info["slicer"]
                respdata["height"] = info["height"]
                respdata["firstLayerHeight"] = info["firstLayerHeight"]
                respdata["layerHeight"] = info["layerHeight"]
                respdata["filament"] = info["filament"]
                respdata["printDuration"] = info['buildTime']
                respdata["fileName"] = os.path.relpath(
                    path, sd_path)  # os.path.basename ?

        # rr_move?old=XXX&new=YYY
        elif "rr_move" in path:
            # {"err":[code]} , code 0 if success
            respdata["err"] = 0
            _from = self.get_argument('old').replace(
                "0:/", "").replace("0%3A%2F", "")
            if KLIPPER_CFG_NAME in _from or KLIPPER_LOG_NAME in _from:
                pass
            else:
                _from = os.path.abspath(os.path.join(sd_path, _from))
                _to = self.get_argument('new').replace(
                    "0:/", "").replace("0%3A%2F", "")
                _to = os.path.abspath(os.path.join(sd_path, _to))
                try:
                    os.rename(_from, _to)
                except OSError as e:
                    self.logger.error("rr_move: %s" % (e.strerror,))
                    respdata["err"] = 1

        # rr_mkdir?dir=XXX
        elif "rr_mkdir" in path:
            # {"err":[code]} , 0 if success
            respdata["err"] = 0
            directory = self.get_argument('dir').replace(
                "0:/", "").replace("0%3A%2F", "")
            directory = os.path.abspath(os.path.join(sd_path, directory))
            try:
                os.makedirs(directory)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    self.logger.error("rr_mkdir: %s" % (e.strerror,))
                    respdata["err"] = 1

        # rr_config / rr_configfile
        elif "rr_configfile" in path:
            respdata = {"err": 0}

        elif "rr_config" in path:
            respdata = self.parent.gui_stats.get_config_stats()

        elif "rr_reply" in path:
            try:
                self.write(self.parent.gcode_resps.pop(0))
            except IndexError:
                self.write("")
            return

        else:
            self.logger.error("  get(path={})".format(path))
            self.logger.error("     !! uri: {}".format(self.request.uri))

        # Send response back to client
        respstr = json.dumps(respdata)
        self.write(respstr)

    def post(self, path, *args, **kwargs):
        respdata = {"err": 1}
        if "rr_upload" in self.request.path:
            # /rr_upload?name=xxxxx&time=xxxx
            # /rr_upload?name=0:/filaments/PLA/unload.g&time=2017-11-30T11:46:50

            size = int(self.request.headers['Content-Length'])
            body_len = len(self.request.body)
            if body_len == 0:
                # e.g. filament create
                respdata["err"] = 0
            elif body_len != size or not size:
                self.logger.error("upload size error: %s != %s" %
                                  (body_len, size))
            else:
                target_path = self.get_argument('name').replace("0:/", ""). \
                    replace("0%3A%2F", "")
                if KLIPPER_CFG_NAME in target_path:
                    cfgname = os.path.abspath(
                        self.printer.get_start_arg('config_file'))
                    datestr = time.strftime("-%Y%m%d_%H%M%S")
                    backup_name = cfgname + datestr
                    temp_name = cfgname + "_autosave"
                    if cfgname.endswith(".cfg"):
                        backup_name = cfgname[:-4] + datestr + ".cfg"
                        temp_name = cfgname[:-4] + "_autosave.cfg"
                    try:
                        f = open(temp_name, 'wb')
                        f.write(self.request.body)
                        f.close()
                        os.rename(cfgname, backup_name)
                        os.rename(temp_name, cfgname)
                        respdata['err'] = 0
                    except IOError as err:
                        self.logger.error("Upload, cfg: %s" % err)
                elif KLIPPER_LOG_NAME in target_path:
                    respdata['err'] = 0
                else:
                    target_path = os.path.abspath(
                        os.path.join(self.sd_path, target_path))
                    # Create a dir first
                    try:
                        os.makedirs(os.path.dirname(target_path))
                    except OSError:
                        pass
                    # Try to save content
                    try:
                        with open(target_path, 'w') as output_file:
                            output_file.write(self.request.body)
                            respdata['err'] = 0
                    except IOError as err:
                        self.logger.error("Upload, g-code: %s" % err)
        else:
            self.logger.error("Unknown req path: %s" % self.request.path)
        # Send response back to client
        self.write(json.dumps(respdata))


def create_dir(_dir):
    try:
        os.makedirs(_dir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise Exception("cannot create directory {}".format(_dir))


_TORNADO_THREAD = None


class RepRapGuiModule(object):
    warmup_time = .1
    layer_stats = []
    first_layer_start = None
    last_used_file = None
    htmlroot = None

    def __init__(self, config):
        global _TORNADO_THREAD
        global _PARENT
        _PARENT = self
        self.printer = printer = config.get_printer()
        self.logger = logging
        self.logger_tornado = logging
        # self.logger = printer.logger.getChild("DuetWebControl")
        # self.logger_tornado = self.logger.getChild("tornado")
        # self.logger_tornado.setLevel(logging.INFO)
        self.gcode = printer.lookup_object('gcode')
        # logging.info("Initializing RepRap API")

        # self.gui_stats = GuiStats(config)
        self.gcode_resps = []
        self.lock = threading.Lock()
        # Read config
        htmlroot = os.path.normpath(os.path.join(os.path.dirname(__file__)))
        htmlroot = os.path.join(htmlroot, "DuetWebControl")
        if not os.path.exists(os.path.join(htmlroot, 'reprap.htm')):
            raise printer.config_error(
                "DuetWebControl files not found '%s'" % htmlroot)
        self.logger.debug("html root: %s" % (htmlroot,))
        self.user = config.get('user', '')
        self.passwd = config.get('password', '')
        # Camera information
        self.feed_interval = config.getfloat('feedrate', minval=.0, default=.1)
        # self.camera = printer.try_load_module(
        #     config, "videocam", folder="modules")
        # # - M80 / M81 ATX commands
        # self.atx_on = config.get('atx_cmd_on', default=None)
        # self.atx_off = config.get('atx_cmd_off', default=None)
        # ------------------------------
        # Create paths to virtual SD
        sd = printer.try_load_module(config, "virtual_sdcard")
        sdcard_dirname = sd.sdcard_dirname
        create_dir(os.path.join(sdcard_dirname, "gcodes"))
        create_dir(os.path.join(sdcard_dirname, "macros"))
        create_dir(os.path.join(sdcard_dirname, "filaments"))
        create_dir(os.path.join(sdcard_dirname, "sys"))
        # ------------------------------
        # Start tornado webserver
        if _TORNADO_THREAD is None or not _TORNADO_THREAD.isAlive():
            application = tornado.web.Application(
                [
                    tornado.web.url(r"/", MainHandler,
                                    {"path": htmlroot}, name="main"),
                    # tornado.web.url(r'/login', LoginHandler,
                    #                 {"path": htmlroot}, name="login"),
                    # tornado.web.url(r'/logout', LogoutHandler, name="logout"),
                    tornado.web.url(r"/(.*\.xml)", tornado.web.StaticFileHandler,
                                    {"path": htmlroot}),
                    tornado.web.url(r"/fonts/(.*)", tornado.web.StaticFileHandler,
                                    {"path": os.path.join(htmlroot, "fonts")}),
                    tornado.web.url(r"/js/(.*)", tornado.web.StaticFileHandler,
                                    {"path": os.path.join(htmlroot, "js")}),
                    tornado.web.url(r"/css/(.*)", tornado.web.StaticFileHandler,
                                    {"path": os.path.join(htmlroot, "css")}),
                    tornado.web.url(r"/(rr_.*)", rrHandler,
                                    {"sd_path": sdcard_dirname}),
                    # tornado.web.url(r"/jpeg", JpegHandler,
                    #                 {"camera": self.camera}),
                    # tornado.web.url(r"/video", JpegStreamHandler,
                    #                 {"camera": self.camera,
                    #                  "interval": self.feed_interval}),
                ],
                # cookie_secret="16d35553-3331-4569-b419-8748d22aa599",
                log_function=self.Tornado_LoggerCb,
                max_buffer_size=104857600*20,
                # login_url="/login",
                xsrf_cookies=False
                )

            # Put tornado to background thread
            _TORNADO_THREAD = threading.Thread(
                target=self.Tornado_execute, args=(config, application))
            _TORNADO_THREAD.daemon = True
            _TORNADO_THREAD.start()

        # ------------------------------
        # fd_r, self.pipe_write = os.pipe()  # Change to PTY ?
        # self.gcode.register_fd(fd_r)
        #
        # self.gcode.write_resp = self.gcode_resp_handler
        # # Disable auto temperature reporting
        # self.printer_write_no_update("AUTO_TEMP_REPORT AUTO=0")
        # ------------------------------
        self.logger.info("RepRep Web GUI loaded")

    def Tornado_LoggerCb(self, req):
        values = [req.request.remote_ip, req.request.method, req.request.uri]
        self.logger_tornado.debug(" ".join(values))

    def Tornado_execute(self, config, application):
        port = http_port = config.getint('http', default=80)
        https_port = config.getint('https', None)
        ssl_options = None

        if https_port is not None:
            port = https_port
            ssl_options = {
                "certfile": os.path.normpath(os.path.expanduser(config.get('cert'))),
                "keyfile": os.path.normpath(os.path.expanduser(config.get('key'))),
            }
            self.logger.debug("HTTPS port %s" % (https_port,))
        else:
            self.logger.debug("HTTP port %s" % (http_port,))

        http_server = tornado.httpserver.HTTPServer(application,
                                                    ssl_options=ssl_options)
        http_server.listen(port)
        tornado.ioloop.IOLoop.current().start()

    resp = ""
    resp_rcvd = False
    store_resp = False

    def _write(self, cmd):
        # self.logger.debug("GCode send: %s" % (cmd,))
        with self.lock:
            self.resp_rcvd = False
            self.resp = ""
            os.write(self.pipe_write, "%s\n" % cmd)

    def printer_write_no_update(self, cmd):
        self.store_resp = False
        self._write(cmd)

    def printer_write(self, cmd):
        self.store_resp = True
        self._write(cmd)

    def gcode_resp_handler(self, msg):
        self.resp += msg
        if "ok" not in self.resp:
            return
        resp = self.resp
        self.logger.debug("GCode resps: %s" % (repr(resp),))
        if "Klipper state" in resp:
            self.append_gcode_resp(resp)
        elif not self.resp_rcvd or "Error:" in resp or "Warning:" in resp:
            resp = resp.strip()
            if len(resp) > 2:
                resp = resp.replace("ok", "")
            if self.store_resp or "Error:" in resp or "Warning:" in resp:
                self.append_gcode_resp(resp)
            self.resp_rcvd = True
        self.resp = ""

    def append_gcode_resp(self, msg):
        self.gcode_resps.append(msg)


def load_config(config):
    return RepRapGuiModule(config)
