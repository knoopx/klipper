# Control for 602_Selector
#
# Copyright (C) 2018  Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import math
import stepper
import homing
import chelper
import pickle

from os.path import expanduser
TOOL_FILE = expanduser('~') + "/s3l3ctor_tool.pkl"


STEPPERS = {
    'tumbler': 0,
    'drive': 1,
}

DISENGAGE_DIST = 15.
STALL_TIME = 0.100


class error(Exception):
    pass

# TODO: need to log position after pausing a print


class SixOhTwo:
    def __init__(self, config):
        self.homed = False
        self.printer = config.get_printer()
        self.selector_tool = SelectorTool(config)
        self.gcode = self.printer.lookup_object('gcode')
        mcu = self.printer.lookup_object('mcu')
        mcu.register_config_callback(self.build_config)
        idler_offset = config.getfloat('idler_offset', 22., above=0.)
        idler_spacing = config.getfloat('idler_spacing', 100., above=0.)
        self.idler_positions = [
            (idler_offset + i*idler_spacing) for i in range(5, -1, -1)]
        # [117.5, 95.5, 73.5, 51.5, 29.5, 7.5]
        print(self.idler_positions)
        self.tumbler_velocity = config.getfloat('tumbler_velocity', 10.)
        self.change_retract_dist = config.getfloat(
            'change_retract_dist', 45.) * -1.
        self.change_extrude_dist = config.getfloat('change_extrude_dist', 45.)
        self.synced_dist = config.getfloat('synced_dist', 10.)
        self.drive_velocity = config.getfloat('drive_velocity', 50.)
        self.synced_velocity = config.getfloat('synced_velocity', 20.)
        self._init_tool()
        self.engaged = False
        self.printer.register_event_handler("klippy:ready",
                                            self.handle_ready)

        # TODO: add help to the commands
        self.gcode.register_command('HOME_SELECTOR', self.cmd_HOME_SELECTOR)
        self.gcode.register_command(
            'SELECT_FILAMENT', self.cmd_SELECT_FILAMENT)

        self.gcode.register_command(
            'ENGAGE_FILAMENT', self.cmd_ENGAGE_FILAMENT)

    def handle_ready(self):
        logging.info("Active tool: %d, Engaged: %s",
                     self.current_tool, self.engaged)
        self.home()

    def _init_tool(self):
        # fetch current tool from a pickled value
        try:
            t_file = open(TOOL_FILE, 'r')
        except:
            t_file = None
            self.current_tool = 0
            self.save_state()
        if t_file:
            try:
                tool = pickle.load(t_file)['current_tool']
            except:
                tool = None
            if tool is not None and tool >= 0 and tool < 5:
                self.current_tool = tool
                t_file.close()
            else:
                self.current_tool = 0
                t_file.close()
                self.save_state()

    def save_state(self):
        try:
            t_file = open(TOOL_FILE, 'w+')
        except:
            logging.info("sixohtwo: Unable to open file to save tool")
            return
        if t_file:
            pickle.dump({'current_tool': self.current_tool,
                         "engaged": self.engaged}, t_file)
            t_file.close()

    def build_config(self):
        self.selector_tool.build_config()

    def home(self):
        # TODO: query endstop first before attempting to home
        axis = [0]
        self._home_axis(axis)
        # retract to move off of endstop
        self.move_tumbler(10., self.tumbler_velocity)
        self.select_filament(self.current_tool, self.tumbler_velocity)

        # self.engaged = False
        self.homed = False

    def _home_axis(self, axis):
        homing_state = homing.Homing(self.selector_tool)
        homing_state.set_no_verify_retract()
        try:
            homing_state.home_axes(axis)
        except homing.EndstopError as e:
            # TODO: Instead of responding with an error
            # Give user a chance to recover
            self.gcode.respond_error(str(e))

    def _verify_homed(self):
        if not self.homed:
            self.gcode.respond_info("Must home firt")

    def move_tumbler(self, dist, speed):
        pos = self.selector_tool.get_position()
        pos[0] += dist
        try:
            self.selector_tool.move(pos, speed)
        except homing.EndstopError as e:
            self.gcode.respond_error(str(e))
            return
        self.selector_tool.wait_moves()

    def move_drive(self, dist, speed, with_ex=False):
        pos = self.selector_tool.get_position()
        pos[1] += dist
        if with_ex:
            pos[3] += dist
        try:
            self.selector_tool.move(pos, speed)
        except homing.EndstopError as e:
            self.gcode.respond_error(str(e))
            return
        self.selector_tool.wait_moves()

    def select_filament(self, index, speed):
        if index < 0 or index > 5:
            self.gcode.respond_info("Cannot move to index: %d" % index)
            return
        if not self.engaged or self.current_tool != index:
            pos = self.selector_tool.get_position()
            pos[0] = self.idler_positions[index]
            try:
                self.selector_tool.move(pos, speed)
            except homing.EndstopError as e:
                self.gcode.respond_error(str(e))
                return
            self.selector_tool.wait_moves()
            self.gcode.respond_info(
                "Tumbler moved to index[%d], position (%.2f)"
                % (index, pos[0]))
            self.current_tool = index
            self.engaged = True

    def disengage(self):
        if self.engaged:
            self.move_tumbler(DISENGAGE_DIST, self.tumbler_velocity)
            self.selector_tool.motor_off(STEPPERS['drive'])
            self.engaged = False

    def engage_filament(self, index):
        if index < 0 or index > 5:
            self.gcode.respond_error("Invalid Tool Index: %d"
                                     % index)
            return
        if index == self.current_tool:
            self.gcode.respond_info("Tool %d already loaded")
            return
        self.selector_tool.wait_moves()
        self.selector_tool.save_extruder_positon()
        self.home()
        self.select_filament(self.current_tool, self.tumbler_velocity)
        # TODO: - retract in sync?
        self.move_drive(self.synced_dist*-1,
                        self.tumbler_velocity, with_ex=True)
        self.move_drive(self.change_retract_dist, self.drive_velocity)
        self.select_filament(index, self.tumbler_velocity)
        self.move_drive(self.change_extrude_dist, self.drive_velocity)
        self.move_drive(self.synced_dist, self.tumbler_velocity, with_ex=True)
        self.selector_tool.reset_extruder_pos()
        self.disengage()
        self.save_state()

    def cmd_SELECT_FILAMENT(self, params):
       idx = self.gcode.get_int('INDEX', params)
       if idx >= 0:
           self.select_filament(idx, self.tumbler_velocity)
       elif idx == -1:
           self.disengage()

    def cmd_ENGAGE_FILAMENT(self, params):
        # Change Tool
        idx = self.gcode.get_int('INDEX', params)
        self.engage_filament(idx)

    def cmd_DISENGAGE_FILAMENT(self, params):
        if self.engaged:
            self.disengage()
        else:
            self.gcode.respond_info(
                "Filament not engaged")

    def cmd_HOME_SELECTOR(self, params):
        self.home()

# Selector's version of Toolhead


class SelectorTool:
    def __init__(self, config):
        self.printer = config.get_printer()
        # TODO: add default values?
        self.max_velocity = config.getfloat('max_velocity', above=0.)
        self.max_accel = config.getfloat('max_accel', above=0.)
        self.commanded_pos = [0., 0., 0., 0.]
        self.extrude_pos = None
        self.kin = SelectorKinematics(self, config)
        self.extruder = None
        # Setup iterative solver
        ffi_main, ffi_lib = chelper.get_ffi()
        self.cmove = ffi_main.gc(ffi_lib.move_alloc(), ffi_lib.free)
        self.move_fill = ffi_lib.move_fill

    def build_config(self):
        self.toolhead = self.printer.lookup_object('toolhead')
        self.max_accel_to_decel = self.toolhead.max_accel_to_decel
        self.update_move_time = self.toolhead.update_move_time
        self.get_next_move_time = self.toolhead.get_next_move_time
        self.get_last_move_time = self.toolhead.get_last_move_time
        # TODO: will resetting printtime adversely affect if it happens during a print?
        # it shouldn't, in fact it may be necessary
        self.reset_print_time = self.toolhead.reset_print_time
        self.get_extruder = self.toolhead.get_extruder
        self.dwell = self.toolhead.dwell
        self.wait_moves = self.toolhead.wait_moves

    def lookup_object(self, name):
        return self

    def send_event(self, event, *params):
        # eat the homing event, we aren't doing phased endstops
        return [False]

    def save_extruder_positon(self):
        self.extrude_pos = self.toolhead.get_extruder().extrude_pos

    def reset_extruder_pos(self):
        if self.extrude_pos is not None:
            extruder = self.toolhead.get_extruder()
            if self.extrude_pos != extruder.extrude_pos:
                extruder.extrude_pos = self.extrude_pos
                extruder.stepper.set_position([self.extrude_pos, 0., 0.])
            self.extrude_pos = None

    def extruder_motor_off(self):
        print_time = self.get_last_move_time()
        extruder = self.toolhead.get_extruder()
        extruder.motor_off(print_time)

    def get_position(self):
        return list(self.commanded_pos)

    def set_position(self, newpos, homing_axes=()):
        self.commanded_pos[:] = newpos
        self.kin.set_position(newpos, homing_axes)

    def move(self, newpos, speed):
        speed = min(speed, self.max_velocity)
        move = Move(self, self.commanded_pos, newpos, speed)
        if not move.move_d:
            return
        self.kin.check_move(move)
        if move.max_cruise_v2 > (move.delta_v2 / 2):
            # Can't accelerate to cruise velocity, limit speed
            move.max_cruise_v2 = move.delta_v2 / 2
        if move.sync_extrude_move:
            self.toolhead.get_extruder().check_move(move)
        move.set_junction(0, move.max_cruise_v2, 0)
        move.move()
        self.commanded_pos[:] = newpos

    def motor_off(self, motor=None):
        self.dwell(STALL_TIME)
        last_move_time = self.get_last_move_time()
        self.kin.motor_off(last_move_time, motor)
        self.dwell(STALL_TIME)

    def get_kinematics(self):
        return self.kin

    def get_max_velocity(self):
        return self.max_velocity, self.max_accel

# Selector Kinematics.   Will use extruder Kinematics for both steppers initially.
# In the future it would be beneficial to create our own kinematics.
# TODO: Might should implement check_move to check limits


class SelectorKinematics:
    def __init__(self, toolhead, config):
        self.printer = config.get_printer()
        self.rails = [stepper.PrinterRail(config.getsection('stepper_' + n))
                      for n in ['t', 'd']]
        # add additional endstop to drive
        ppins = self.printer.lookup_object('pins')
        extruder_es = config.get('extruder_endstop', None)
        if extruder_es is not None:
            ex_pin = ppins.setup_pin('endstop', extruder_es)
            self.rails[1].add_to_endstop(ex_pin)
        self.drive_endstop = self.rails[1].get_endstops()[0]
        self.need_motor_enable = True
        self.max_velocity, self.max_accel = toolhead.get_max_velocity()
        self.limits = [(1.0, -1.0)] * 3
        for axis, rail in zip('xyz', self.rails):
            rail.setup_itersolve('cartesian_stepper_alloc', axis)

    def get_rails(self):
        return list(self.rails[:2])

    def calc_position(self):
        return [rail.get_commanded_position() for rail in self.rails[:2]]

    def set_drive_endstop(self, index):
        endstops = self.rails[1].get_endstops()
        if index >= 0 and index < len(endstops):
            self.drive_endstop = endstops[index]
        else:
            self.drive_endstop = endstops[0]

    def check_drive_endstop(self):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        self.drive_endstop[0].query_endstop(print_time)
        t = self.drive_endstop[0].query_endstop_wait()
        return bool(t)

    def set_position(self, newpos, homing_axes):
        for i, rail in enumerate(self.rails):
            rail.set_position(newpos)
            if i in homing_axes:
                self.limits[i] = rail.get_range()

    def home(self, homing_state):
        for axis in homing_state.get_axes():
            self._home_axis(homing_state, axis, self.rails[axis])

    def motor_off(self, print_time, motor=None):
        if motor is None:
            self.limits = [(1.0, -1.0)] * 3
            for rail in self.rails[:2]:
                rail.motor_enable(print_time, 0)
        else:
            self.rails[motor].motor_enable(print_time, 0)

    def _check_motor_enable(self, print_time, move):
        need_motor_enable = False
        for i, rail in enumerate(self.rails):
            if move.axes_d[i]:
                rail.motor_enable(print_time, 1)
            need_motor_enable |= not rail.is_motor_enabled()
        self.need_motor_enable = need_motor_enable

    def _home_axis(self, homing_state, axis, rail):
        # TODO: Home pos will depend on which direction I need to home
        # Determine moves
        position_min, position_max = rail.get_range()
        hi = rail.get_homing_info()
        homepos = [None, None, None, None]
        homepos[axis] = hi.position_endstop
        forcepos = list(homepos)
        if hi.positive_dir:
            forcepos[axis] -= 1.5 * (hi.position_endstop - position_min)
        else:
            forcepos[axis] += 1.5 * (position_max - hi.position_endstop)

        if axis == 1:
            if self.check_drive_endstop():
                logging.info("Drive Endstop already triggered, aborting home")
                # Drive endstop already triggered, no need to move
                return
            endstops = [self.drive_endstop]
        else:
            endstops = rail.get_endstops()
        homing_state.home_rails([rail], forcepos, homepos, None)

    def check_move(self, move):
        if move.axes_d[0]:
            t_pos = move.end_pos[0]
            if t_pos < self.limits[0][0] or t_pos > self.limits[0][1]:
                if self.limits[0][0] > self.limits[0][1]:
                    raise homing.EndstopMoveError(
                        move.end_pos, "Must home axis first")
                raise homing.EndstopMoveError(move.end_pos)
            # make sure its within limits

    def move(self, print_time, move):
        if self.need_motor_enable:
            self._check_motor_enable(print_time, move)
        for i, rail in enumerate(self.rails):
            if move.axes_d[i]:
                rail.step_itersolve(move.cmove)


class Move:
    def __init__(self, toolhead, start_pos, end_pos, speed):
        self.toolhead = toolhead
        self.start_pos = tuple(start_pos)
        self.end_pos = tuple(end_pos)
        self.accel = toolhead.max_accel
        self.cmove = toolhead.cmove
        self.axes_d = axes_d = [end_pos[i] - start_pos[i]
                                for i in (0, 1, 2, 3)]
        self.move_d = move_d = math.sqrt(sum([d*d for d in axes_d[:3]]))
        self.sync_extrude_move = False
        if axes_d[3]:
            extrude_d = abs(self.axes_d[3])
            if axes_d[3] != axes_d[1] or extrude_d != move_d:
                raise error(
                    "Extrude Move distance must identical to selector drive move")
            self.sync_extrude_move = True
        # Although selector moves are "kinematic" they aren't relative to the printer.
        # This allows this move class to move in sync with the extruder during
        # extrude/retraction moves
        self.is_kinematic_move = False
        self.min_move_t = move_d / speed
        # Junction speeds are tracked in velocity squared.  The
        # delta_v2 is the maximum amount of this squared-velocity that
        # can change in this move.
        self.max_start_v2 = 0.
        self.max_cruise_v2 = speed**2
        self.delta_v2 = 2.0 * move_d * self.accel
        self.max_smoothed_v2 = 0.
        self.smooth_delta_v2 = 2.0 * move_d * toolhead.max_accel_to_decel

    def limit_speed(self, speed, accel):
        speed2 = speed**2
        if speed2 < self.max_cruise_v2:
            self.max_cruise_v2 = speed2
            self.min_move_t = self.move_d / speed
        self.accel = min(self.accel, accel)
        self.delta_v2 = 2.0 * self.move_d * self.accel
        self.smooth_delta_v2 = min(self.smooth_delta_v2, self.delta_v2)

    def set_junction(self, start_v2, cruise_v2, end_v2):
        # Determine accel, cruise, and decel portions of the move distance
        inv_delta_v2 = 1. / self.delta_v2
        self.accel_r = accel_r = (cruise_v2 - start_v2) * inv_delta_v2
        self.decel_r = decel_r = (cruise_v2 - end_v2) * inv_delta_v2
        self.cruise_r = cruise_r = 1. - accel_r - decel_r
        # Determine move velocities
        self.start_v = start_v = math.sqrt(start_v2)
        self.cruise_v = cruise_v = math.sqrt(cruise_v2)
        self.end_v = end_v = math.sqrt(end_v2)
        # Determine time spent in each portion of move (time is the
        # distance divided by average velocity)
        self.accel_t = accel_r * self.move_d / ((start_v + cruise_v) * 0.5)
        self.cruise_t = cruise_r * self.move_d / cruise_v
        self.decel_t = decel_r * self.move_d / ((end_v + cruise_v) * 0.5)

    def move(self):
        # Generate step times for the move
        next_move_time = self.toolhead.get_next_move_time()
        self.toolhead.move_fill(
                self.cmove, next_move_time,
                self.accel_t, self.cruise_t, self.decel_t,
                self.start_pos[0], self.start_pos[1], self.start_pos[2],
                self.axes_d[0], self.axes_d[1], self.axes_d[2],
                self.start_v, self.cruise_v, self.accel)
        self.toolhead.kin.move(next_move_time, self)
        if self.sync_extrude_move:
            # Reset axes_d so Klipper thinks this is an extrude only move
            self.axes_d[0] = self.axes_d[1] = 0.
            extruder = self.toolhead.get_extruder()
            extruder.move(next_move_time, self)
        self.toolhead.update_move_time(
            self.accel_t + self.cruise_t + self.decel_t)


def load_config(config):
    return SixOhTwo(config)
