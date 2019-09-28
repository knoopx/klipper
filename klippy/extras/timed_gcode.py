# Extended Gcode Commands
#
# Copyright (C) 2018  Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

class GCodeTimer:
  def __init__(self, reactor, gcode, script, delay):
    self.reactor = reactor
    self.gcode = gcode
    self.script = script
    delay_time = reactor.monotonic() + delay
    self.timer = reactor.register_timer(self.invoke, delay_time)

  def invoke(self, _):
    self.reactor.unregister_timer(self.timer)
    self.gcode.run_script_from_command(self.script)
    return self.reactor.NEVER


class TimedGcode:
  def __init__(self, config):
    self.printer = config.get_printer()
    self.reactor = self.printer.get_reactor()
    self.gcode = self.printer.lookup_object('gcode')
    self.gcode.register_command("TIMED_GCODE", self.cmd_TIMED_GCODE, desc="Run GCODE script from a timer")

  def cmd_TIMED_GCODE(self, params):
    script = self.gcode.get_str('GCODE', params)
    delay_time = self.gcode.get_int('DELAY', params, 0, minval=0)
    # TODO: Instead of a simple underscore, replace with ability
    # to use escape chars (possibly regex)
    script = script.replace('_', " ")
    GCodeTimer(self.reactor, self.gcode, script, delay_time)


def load_config(config):
  return TimedGcode(config)
