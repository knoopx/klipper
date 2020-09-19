# A utility class to test resonances of the printer
#
# Copyright (C) 2020  Dmitry Butyugin <dmbutyugin@google.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math, os, time
from . import shaper_calibrate

def _parse_probe_points(config):
    points = config.get('probe_points').split('\n')
    try:
        points = [line.split(',', 2) for line in points if line.strip()]
        return [[float(coord.strip()) for coord in p] for p in points]
    except:
        raise config.error("Unable to parse probe_points in %s" % (
            config.get_name()))

class VibrationSineTest:
    def __init__(self, config):
        printer = config.get_printer()
        self.gcode = printer.lookup_object('gcode')
        self.seg_sec = config.getfloat('seg_sec', 0.0005, above=0.0)
        self.min_freq = config.getfloat('min_freq', 5., minval=1.)
        self.max_freq = config.getfloat('max_freq', 120.,
                                        minval=self.min_freq, maxval=200.)
        self.accel_per_hz = config.getfloat('accel_per_hz', 75.0, above=0.)
        self.hz_per_sec = config.getfloat('hz_per_sec', 1.,
                                          minval=0.1, maxval=2.)

        self.probe_points = _parse_probe_points(config)
    def get_supported_axes(self):
        return ['x', 'y']
    def get_start_test_points(self):
        return self.probe_points
    def prepare_test(self, toolhead, gcmd):
        self.freq_start = gcmd.get_float("FREQ_START", self.min_freq, minval=1.)
        self.freq_end = gcmd.get_float("FREQ_END", self.max_freq,
                                       minval=self.freq_start, maxval=200.)
        self.hz_per_sec = gcmd.get_float("HZ_PER_SEC", self.hz_per_sec,
                                         above=0., maxval=2.)
        # Attempt to adjust maximum acceleration and acceleration to
        # deceleration based on the maximum test frequency.
        max_accel = self.freq_end * self.accel_per_hz
        toolhead.cmd_SET_VELOCITY_LIMIT(self.gcode.create_gcode_command(
            "SET_VELOCITY_LIMIT", "SET_VELOCITY_LIMIT",
            {"ACCEL": max_accel, "ACCEL_TO_DECEL": max_accel}))
    def run_test(self, toolhead, axis, gcmd):
        X, Y, Z, E = toolhead.get_position()
        start = (X, Y)
        if axis not in self.get_supported_axes():
            raise gcmd.error("Test axis '%s' is not supported", axis)
        vib_dir = (1, 0) if axis == 'x' else (0., 1.)
        # Generate moves
        t_seg = self.seg_sec
        i = 0
        pX, pY = X, Y
        freq = self.freq_start
        gcmd.respond_info("Testing frequency %.0f Hz" % (freq,))
        while freq <= self.freq_end + 0.000001:
            i += 1
            accel = min(self.accel_per_hz * freq,
                        toolhead.requested_accel_to_decel)
            omega = 2 * math.pi * freq
            A = accel / omega**2
            t = t_seg * i
            vib_pos = A * math.sin(omega * t)
            X = start[0] + vib_dir[0] * vib_pos
            Y = start[1] + vib_dir[1] * vib_pos
            V = math.sqrt((X-pX)**2 + (Y-pY)**2) / t_seg
            toolhead.move([X, Y, Z, E], V)
            pX, pY = X, Y
            old_freq = freq
            freq = self.freq_start + t * self.hz_per_sec
            if math.floor(freq) > math.floor(old_freq):
                gcmd.respond_info("Testing frequency %.0f Hz" % (freq,))
        toolhead.move([start[0], start[1], Z, E], V)

class VibrationPulseTest:
    def __init__(self, config):
        printer = config.get_printer()
        self.gcode = printer.lookup_object('gcode')
        self.min_freq = config.getfloat('min_freq', 5., minval=1.)
        self.max_freq = config.getfloat('max_freq', 120.,
                                        minval=self.min_freq, maxval=200.)
        self.accel_per_hz = config.getfloat('accel_per_hz', 75.0, above=0.)
        self.hz_per_sec = config.getfloat('hz_per_sec', 1.,
                                          minval=0.1, maxval=2.)

        self.probe_points = _parse_probe_points(config)
    def get_supported_axes(self):
        return ['x', 'y']
    def get_start_test_points(self):
        return self.probe_points
    def prepare_test(self, toolhead, gcmd):
        self.freq_start = gcmd.get_float("FREQ_START", self.min_freq, minval=1.)
        self.freq_end = gcmd.get_float("FREQ_END", self.max_freq,
                                       minval=self.freq_start, maxval=200.)
        self.hz_per_sec = gcmd.get_float("HZ_PER_SEC", self.hz_per_sec,
                                         above=0., maxval=2.)
        # Attempt to adjust maximum acceleration and acceleration to
        # deceleration based on the maximum test frequency.
        max_accel = self.freq_end * self.accel_per_hz
        toolhead.cmd_SET_VELOCITY_LIMIT(self.gcode.create_gcode_command(
            "SET_VELOCITY_LIMIT", "SET_VELOCITY_LIMIT",
            {"ACCEL": max_accel, "ACCEL_TO_DECEL": max_accel}))
    def run_test(self, toolhead, axis, gcmd):
        X, Y, Z, E = toolhead.get_position()
        if axis not in self.get_supported_axes():
            raise gcmd.error("Test axis '%s' is not supported", axis)
        vib_dir = (1, 0) if axis == 'x' else (0., 1.)
        sign = 1.
        freq = self.freq_start
        gcmd.respond_info("Testing frequency %.0f Hz" % (freq,))
        while freq <= self.freq_end + 0.000001:
            t_seg = .25 / freq
            accel = min(self.accel_per_hz * freq,
                        toolhead.requested_accel_to_decel)
            V = accel * t_seg
            toolhead.cmd_M204(self.gcode.create_gcode_command(
                "M204", "M204", {"S": accel}))
            L = .5 * accel * t_seg**2
            nX = X + sign * vib_dir[0] * L
            nY = Y + sign * vib_dir[1] * L
            toolhead.move([nX, nY, Z, E], V)
            toolhead.move([X, Y, Z, E], V)
            sign = -sign
            old_freq = freq
            freq += 2. * t_seg * self.hz_per_sec
            if math.floor(freq) > math.floor(old_freq):
                gcmd.respond_info("Testing frequency %.0f Hz" % (freq,))

# Make the toolhead follow the Moore curve
class MooreCurveTest:
    def __init__(self, config):
        printer = config.get_printer()
        self.gcode = printer.lookup_object('gcode')
        xmin = config.getfloat('xmin')
        xmax = config.getfloat('xmax', above=xmin)
        ymin = config.getfloat('ymin')
        ymax = config.getfloat('ymax', above=ymin)
        self.order = order = config.getint('order', 3, minval=0, maxval=8)
        self.runs = config.getint('runs', 3, minval=1)

        self.xl = (xmax-xmin) / (2**(order+1) - 1)
        self.yl = (ymax-ymin) / (2**(order+1) - 1)
        self.sx = self.xl * (2**(order)-1) + xmin
        self.sy = ymin
        self.z = config.getfloat('z')
        self.prepare_moves()
    def get_supported_axes(self):
        return ['xy']
    def get_start_test_points(self):
        return [[self.sx, self.sy, self.z]]
    def prepare_test(self, toolhead, gcmd):
        self.vel = gcmd.get_float("MOVE_SPEED", 50.)
    def prepare_moves(self):
        move_dir = [0., 1.]
        moves = []
        pos = [self.sx, self.sy]
        logging.info("Preparing Moore curve moves")
        def left():
            move_dir[0], move_dir[1] = -move_dir[1], move_dir[0]
        def right():
            move_dir[0], move_dir[1] = move_dir[1], -move_dir[0]
        def forward():
            pos[0] += self.xl * move_dir[0]
            pos[1] += self.yl * move_dir[1]
            moves.append(tuple(pos))
        def gen_l(order):
            if not order:
                return
            # -RF+LFL+FR-
            left()
            gen_r(order-1)
            forward()
            right()
            gen_l(order-1)
            forward()
            gen_l(order-1)
            right()
            forward()
            gen_r(order-1)
            left()
        def gen_r(order):
            if not order:
                return
            # +LF-RFR-FL+
            right()
            gen_l(order-1)
            forward()
            left()
            gen_r(order-1)
            forward()
            gen_r(order-1)
            left()
            forward()
            gen_l(order-1)
            right()
        order = self.order
        # LFL+F+LFL
        gen_l(order)
        forward()
        gen_l(order)
        right()
        forward()
        right()
        gen_l(order)
        forward()
        gen_l(order)
        # Return to start
        pos[0], pos[1] = self.sx, self.sy
        moves.append(tuple(pos))
        self.moves = moves
    def run_test(self, toolhead, axis, gcmd):
        _, _, Z, E = toolhead.get_position()
        for i in range(self.runs):
            gcmd.respond_info("Moore curve run %d out of %d" % (i+1, self.runs))
            old_percent = 0
            n = len(self.moves)
            for j, move in enumerate(self.moves):
                toolhead.move([move[0], move[1], Z, E], self.vel)
                percent = math.floor((j + 1.) * 100. / n)
                if percent != old_percent:
                    gcmd.respond_info(
                            "Moore curve run progress %d %%" % (percent,))
                old_percent = percent

class ResonanceTester:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.move_speed = config.getfloat('move_speed', 50., above=0.)
        test_methods = {'pulse': VibrationPulseTest,
                        'sine': VibrationSineTest,
                        'moore': MooreCurveTest}
        test_method = config.getchoice('method', test_methods, 'pulse')
        self.test = test_method(config)
        if not config.get('accel_chip_x', None):
            self.accel_chip_names = [('xy', config.get('accel_chip').strip())]
        else:
            self.accel_chip_names = [
                ('x', config.get('accel_chip_x').strip()),
                ('y', config.get('accel_chip_y').strip())]
            if self.accel_chip_names[0][1] == self.accel_chip_names[1][1]:
                self.accel_chip_names = [('xy', self.accel_chip_names[0][1])]

        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("MEASURE_AXES_NOISE",
                                    self.cmd_MEASURE_AXES_NOISE)
        self.gcode.register_command("TEST_RESONANCES",
                                    self.cmd_TEST_RESONANCES)
        self.gcode.register_command("SHAPER_CALIBRATE",
                                    self.cmd_SHAPER_CALIBRATE)
        self.printer.register_event_handler("klippy:connect", self.connect)

    def connect(self):
        self.accel_chips = [
                (axis, self.printer.lookup_object(chip_name))
                for axis, chip_name in self.accel_chip_names]

    def cmd_TEST_RESONANCES(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        # Parse parameters
        self.test.prepare_test(toolhead, gcmd)
        if len(self.test.get_supported_axes()) > 1:
            axis = gcmd.get("AXIS").lower()
        else:
            axis = gcmd.get("AXIS", self.test.get_supported_axes()[0]).lower()
        if axis not in self.test.get_supported_axes():
            raise gcmd.error("Unsupported axis '%s'" % (axis,))

        fig_name_tmpl = gcmd.get("FIG_NAME", None)
        csv_name_tmpl = gcmd.get("CSV_NAME", "resonance_data.csv")
        raw_name_tmpl = gcmd.get("RAW_NAME", None)

        # Setup calculation of resonances
        calibrator = shaper_calibrate.ShaperCalibrate(self.printer)
        if fig_name_tmpl is not None:
            calibrator.setup_matplotlib(True)

        currentPos = toolhead.get_position()
        Z = currentPos[2]
        E = currentPos[3]

        calibration_points = self.test.get_start_test_points()
        data = None
        for point in calibration_points:
            toolhead.manual_move(point, self.move_speed)
            if len(calibration_points) > 1:
                gcmd.respond_info(
                        "Probing point (%.3f, %.3f, %.3f)" % tuple(point))
            toolhead.wait_moves()
            toolhead.dwell(0.500)
            gcmd.respond_info("Testing axis %s" % axis.upper())

            for chip_axis, chip in self.accel_chips:
                if axis in chip_axis or chip_axis in axis:
                    chip.start_measurements()
            # Generate moves
            self.test.run_test(toolhead, axis, gcmd)
            raw_values = []
            for chip_axis, chip in self.accel_chips:
                if axis in chip_axis or chip_axis in axis:
                    results = chip.finish_measurements()
                    if raw_name_tmpl:
                        raw_name = self.get_filename(
                                raw_name_tmpl, axis,
                                point if len(calibration_points) > 1 else None)
                        results.write_to_file(raw_name)
                    raw_values.append((chip_axis, results))
            for chip_axis, chip_values in raw_values:
                gcmd.respond_info("%s-axis accelerometer stats: %s" % (
                    chip_axis, chip_values.get_stats(),))
                if not chip_values:
                    raise gcmd.error(
                            "%s-axis accelerometer measured no data" % (
                                chip_axis,))
                new_data = calibrator.process_accelerometer_data(chip_values)
                data = data.join(new_data) if data else new_data
        if fig_name_tmpl is not None:
            self.save_calibration_fig(fig_name_tmpl, calibrator, axis, data)
        self.save_calibration_data(csv_name_tmpl, calibrator, axis, data, None)

    def cmd_SHAPER_CALIBRATE(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        # Parse parameters
        self.test.prepare_test(toolhead, gcmd)
        axis = gcmd.get("AXIS", None)
        if not axis:
            calibrate_axes = self.test.get_supported_axes()
        elif axis.lower() not in self.test.get_supported_axes():
            raise gcmd.error("Unsupported axis '%s'" % (axis,))
        else:
            calibrate_axes = [axis.lower()]

        fig_name_tmpl = gcmd.get("FIG_NAME", None)
        csv_name_tmpl = gcmd.get("CSV_NAME", "calibration_data.csv")

        # Setup shaper calibration
        calibrator = shaper_calibrate.ShaperCalibrate(self.printer)
        if fig_name_tmpl is not None:
            calibrator.setup_matplotlib(True)

        input_shaper = self.printer.lookup_object('input_shaper', None)
        if input_shaper is not None:
            input_shaper.disable_shaping()
            gcmd.respond_info("Disabled [input_shaper] for calibration")

        currentPos = toolhead.get_position()
        Z = currentPos[2]
        E = currentPos[3]
        calibration_data = {axis: None for axis in calibrate_axes}

        calibration_points = self.test.get_start_test_points()
        for point in calibration_points:
            toolhead.manual_move(point, self.move_speed)
            if len(calibration_points) > 1:
                gcmd.respond_info(
                        "Probing point (%.3f, %.3f, %.3f)" % tuple(point))
            for axis in calibrate_axes:
                toolhead.wait_moves()
                toolhead.dwell(0.500)
                gcmd.respond_info("Testing axis %s" % axis.upper())

                for chip_axis, chip in self.accel_chips:
                    if axis in chip_axis or chip_axis in axis:
                        chip.start_measurements()
                # Generate moves
                self.test.run_test(toolhead, axis, gcmd)
                raw_values = [(chip_axis, chip.finish_measurements())
                              for chip_axis, chip in self.accel_chips
                              if axis in chip_axis or chip_axis in axis]
                for chip_axis, chip_values in raw_values:
                    gcmd.respond_info("%s-axis accelerometer stats: %s" % (
                        chip_axis, chip_values.get_stats(),))
                    if not chip_values:
                        raise gcmd.error(
                                "%s-axis accelerometer measured no data" % (
                                    chip_axis,))
                    new_data = calibrator.process_accelerometer_data(chip_values)
                    if calibration_data[axis] is None:
                        calibration_data[axis] = new_data
                    else:
                        calibration_data[axis].join(new_data)

        configfile = self.printer.lookup_object('configfile')

        for axis in calibrate_axes:
            gcmd.respond_info(
                    "Calculating the best input shaper parameters for %s axis"
                    % (axis,))
            calibration_data[axis].normalize_to_frequencies()
            shaper_name, shaper_freq, shapers_vals = calibrator.find_best_shaper(
                    calibration_data[axis], gcmd.respond_info)
            gcmd.respond_info(
                    "Recommended shaper_type_%s = %s, shaper_freq_%s = %.1f Hz"
                    % (axis, shaper_name, axis, shaper_freq))
            calibrator.save_params(configfile, axis, shaper_name, shaper_freq)
            if fig_name_tmpl is not None:
                self.save_calibration_fig(fig_name_tmpl, calibrator, axis,
                                          calibration_data[axis], shapers_vals,
                                          shaper_name)
            self.save_calibration_data(csv_name_tmpl, calibrator, axis,
                                       calibration_data[axis], shapers_vals)

        gcmd.respond_info(
            "The SAVE_CONFIG command will update the printer config file\n"
            "with these parameters and restart the printer.")
        if input_shaper is not None:
            input_shaper.enable_shaping()
            gcmd.respond_info("Re-enabled [input_shaper] after calibration")

    def cmd_MEASURE_AXES_NOISE(self, gcmd):
        meas_time = gcmd.get_float("MEAS_TIME", 2.)
        for _, chip in self.accel_chips:
            chip.start_measurements()
        self.printer.lookup_object('toolhead').dwell(meas_time)
        raw_values = [(axis, chip.finish_measurements())
                      for axis, chip in self.accel_chips]
        calibrator = shaper_calibrate.ShaperCalibrate(self.printer)
        for axis, raw_data in raw_values:
            data = calibrator.process_accelerometer_data(raw_data)
            vx = data.psd_x.mean()
            vy = data.psd_y.mean()
            vz = data.psd_z.mean()
            gcmd.respond_info("Axes noise for %s-axis accelerometer: "
                              "%.6f (x), %.6f (y), %.6f (z)" % (
                                  axis, vx, vy, vz))

    def get_filename(self, name_tmpl, axis=None, point=None):
        # Cleanup name_tmpl and get only the name
        name_tmpl = os.path.split(os.path.normpath(name_tmpl))[1]
        base, ext = os.path.splitext(name_tmpl)
        time_suffix = time.strftime("_%Y%m%d_%H%M%S")
        if axis:
            base += '_' + axis
        if point:
            base += "_%.3f_%.3f" % (point[0], point[1])
        base += time_suffix
        return os.path.join("/tmp", base + ext)

    def save_calibration_fig(self, fig_name_tmpl, calibrator, axis,
                             calibration_data, shapers_vals=None,
                             shaper_name=None):
        fig = calibrator.plot_freq_response(
                calibration_data, shapers_vals, shaper_name)
        fig.set_size_inches(8, 6)
        fig_filename = self.get_filename(fig_name_tmpl, axis)
        try:
            fig.savefig(fig_filename)
        except IOError as e:
            raise self.gcode.error("Error writing to file '%s': %s",
                                   fig_filename, str(e))

    def save_calibration_data(self, csv_name_tmpl, calibrator, axis,
                              calibration_data, shapers_vals=None):
        output = self.get_filename(csv_name_tmpl, axis)
        calibrator.save_calibration_data(output, calibration_data, shapers_vals)

def load_config(config):
    return ResonanceTester(config)
