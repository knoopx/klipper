import logging
import tornado.escape
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import os.path
import uuid
import base64
import json
import threading

class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def initialize(self, kwc):
      self.kwc = kwc
      self.kwc.gcode.register_respond_callback(self.respond_callback)
      print("initializing WebSocketHandler")
      pc = tornado.ioloop.PeriodicCallback(self.report_status, 200)
      pc.start()

    def broadcast(self, payload):
        print(("Clients", len(self.clients)))
        for client in self.clients:
            try:
                client.write_message(json.dumps(payload, default=lambda x: x.__dict__))
            except:
                logging.error("Error sending message", exc_info=True)

    def check_origin(self, origin):
        return True

    def open(self):
        print("New client")
        self.clients.add(self)

    def on_close(self):
        print("client disconnected")
        self.clients.remove(self)

    def on_message(self, message):
        # parsed = tornado.escape.json_decode(message)
        # body = parsed["body"]
        pass

    def respond_callback(self, msg):
        self.broadcast({"message": msg})

    def report_status(self):
        self.broadcast({"status": self.kwc.status})


class KlipperWebControl:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        reactor = self.printer.get_reactor()
        self.status_timer = reactor.register_timer(self.update_status_callback)
        self.objects = []
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.status = dict()
        self.app = tornado.web.Application([
            # (r"/", MainHandler),
            (r"/ws", WebSocketHandler, {"kwc": self}),
        ], cookie_secret=base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes))

    def handle_ready(self):
        self.objects = [(name, o) for name, o in self.printer.lookup_objects() if hasattr(o, 'get_status')]
        reactor = self.printer.get_reactor()
        reactor.update_timer(self.status_timer, reactor.NOW)

        self.app_thread = threading.Thread(target=self.start_app, args=(self.app,))
        self.app_thread.daemon = True
        self.app_thread.start()

    def start_app(self, app):
        logging.info("starting tornado app")
        app.listen(9090)
        tornado.ioloop.IOLoop.current().start()

    def update_status_callback(self, eventtime):
        for name, object in self.objects:
            try:
                # logging.info("%s status", name)
                self.status[name] = object.get_status(eventtime)
                # print({name: status})
            except:
                logging.exception("Could not get status for " + name)

        return eventtime + .2

def load_config(config):
    return KlipperWebControl(config)
