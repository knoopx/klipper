import eventlet
import bottle
import logging
import json
import functools
import threading
from multiprocessing import Queue, JoinableQueue

from eventlet import wsgi
from bottle import Bottle, request, response

def subscribable(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        response.set_header("Access-Control-Allow-Origin", "*")
        response.set_header("Access-Control-Allow-Methods", "*")
        response.set_header("Access-Control-Allow-Headers", "*")

        q = Queue()

        def callback(eventtime):
            logging.info("callback")
            q.put(func(self, *args, **kwargs), False)
            return eventtime + .25

        if "text/event-stream" in request.headers.get('Accept'):
            logging.info("event stream request")
            response.set_header('Content-Type', 'text/event-stream')
            response.set_header('Cache-Control', 'no-cache')
            timer = self.reactor.register_timer(callback, self.reactor.NOW)

            # self.reactor.unregister_timer(self.work_timer)
            while True:
                logging.info(request.environ)
                try:
                    obj = q.get()
                    yield "data: %s\n\n" % self.json(obj)
                except:
                    logging.exception("error")

        else:
            logging.info("regular request")
            response.set_header('Content-Type', 'application/json')
            yield self.json(func(self, *args, **kwargs))

    return wrapper

class HTTPServer(Bottle):
    def __init__(self, config):
        super(HTTPServer, self).__init__()
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.port = config.getint("port", 1234)

        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.gcode = self.printer.lookup_object("gcode")
        self.heat = self.printer.lookup_object('heater')
        self.virtual_sdcard = None
        self.toolhead = None

    def handle_ready(self):
        self.virtual_sdcard = self.printer.lookup_object("virtual_sdcard", None)
        self.toolhead = self.printer.lookup_object('toolhead')
        self.heaters = self.heat.heaters.items()

        bottle.debug(True)

        self.get("/status", callback=self.get_status)

        self.thread = threading.Thread(target=self.start)
        self.thread.start()

    def start(self):
        logging.info("starting http server...")
        wsgi.server(eventlet.listen(('', self.port)), self.wsgi)

    def json(self, obj):
        logging.info("json")
        return json.dumps(obj, default=lambda x: None)

    def default_error_handler(self, res):
        super(HTTPServer, self).default_error_handler(res)
        logging.exception(res)

    def get_state(self):
        status = "idle"
    	if self.printer.is_shutdown:
    		return 'off'

    	if self.gcode.is_processing_data:
    		status = 'busy'

    	if self.virtual_sdcard.current_file:
    		status = 'printing'

    	return status

    def get_job(self):
        if self.virtual_sdcard and self.virtual_sdcard.current_file:
            return dict(self.virtual_sdcard.get_status(self.reactor.monotonic()), name=os.path.basename(self.virtual_sdcard.current_file.name))
        return None

    def get_position(self):
        return self.gcode.last_position

    def get_heaters(self):
        return {name: heater.get_status(self.reactor.monotonic()) for name, heater in self.heaters}

    def get_files(self):
        if self.virtual_sdcard:
            return self.virtual_sdcard.get_file_list()
        return []

    @subscribable
    def get_status(self):
        return {
            "state": self.get_state(),
            "position": self.get_position(),
            "heaters": self.get_heaters(),
            "job": self.get_job()
        }

def load_config(config):
    return HTTPServer(config)
