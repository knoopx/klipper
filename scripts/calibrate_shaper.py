#!/usr/bin/env python2
# Shaper auto-calibration script
#
# Copyright (C) 2020  Dmitry Butyugin <dmbutyugin@google.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from __future__ import print_function
import optparse, os, sys
import numpy as np
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                             '..', 'klippy', 'extras'))
from shaper_calibrate import ShaperCalibrate

def parse_log(logname):
    return np.loadtxt(logname, comments='#', delimiter=',')

######################################################################
# Shaper calibration
######################################################################

# Find the best shaper parameters
def calibrate_shaper(datas, lognames, options):
    helper = ShaperCalibrate(printer=None)
    plot_chart = not options.csv or options.output
    if plot_chart:
        helper.setup_matplotlib(output_to_file=options.output is not None)
    # Process accelerometer data
    calibration_data = helper.process_accelerometer_data(datas[0])
    for data in datas[1:]:
        calibration_data.join(helper.process_accelerometer_data(data))
    calibration_data.normalize_to_frequencies()
    shaper_name, shaper_freq, shapers_vals = helper.find_best_shaper(
            calibration_data, print)
    print("Recommended shaper is %s @ %.1f Hz" % (shaper_name, shaper_freq))

    if options.csv is not None:
        helper.save_calibration_data(
                options.csv, calibration_data, shapers_vals)
    # Plot chart
    if plot_chart:
        fig = helper.plot_freq_response(
                calibration_data, shapers_vals, shaper_name)
    if options.output is not None:
        fig.set_size_inches(8, 6)
        fig.savefig(options.output)

######################################################################
# Startup
######################################################################

def main():
    # Parse command-line arguments
    usage = "%prog [options] <logs>"
    opts = optparse.OptionParser(usage)
    opts.add_option("-o", "--output", type="string", dest="output",
                    default=None, help="filename of output graph")
    opts.add_option("-c", "--csv", type="string", dest="csv",
                    default=None, help="filename of output csv file")
    options, args = opts.parse_args()
    if len(args) < 1:
        opts.error("Incorrect number of arguments")

    # Parse data
    datas = [parse_log(fn) for fn in args]

    # Calibrate shaper and generate outputs
    calibrate_shaper(datas, args, options)

if __name__ == '__main__':
    main()
