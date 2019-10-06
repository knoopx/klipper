import logging
import tornado.escape
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import os.path
import uuid
import base64

class WebSocketHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def initialize(self, kwc):
      self.kwc = kwc
      print("initializing WebSocketHandler")
      pc = tornado.ioloop.PeriodicCallback(self.report_status, 1000)
      pc.start()

    def check_origin(self, origin):
        return True

    def open(self):
        self.clients.add(self)

    def on_close(self):
        self.clients.remove(self)

    def on_message(self, message):
        # parsed = tornado.escape.json_decode(message)
        # body = parsed["body"]
        pass

    def report_status(self):
        for client in self.clients:
            try:
                client.write_message({"status": self.kwc.get_status()})
            except:
                logging.error("Error sending message", exc_info=True)


class KlipperWebControl:
    def __init__(self, config):
        self.printer = config.get_printer()
        reactor = self.printer.get_reactor()
        self.status_timer = reactor.register_timer(self.update_status_callback)
        self.get_statuses = []
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.status = dict()
        self.app = tornado.web.Application([
            # (r"/", MainHandler),
            tornado.web.url(r"/ws", WebSocketHandler, {"kwc": self}),
        ], cookie_secret=base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes))

    def get_status(self):
        return self.status

    def handle_ready(self):
        self.get_statuses = [(name, o.get_status) for name, o in self.printer.lookup_objects() if hasattr(o, 'get_status')]
        reactor = self.printer.get_reactor()
        reactor.update_timer(self.status_timer, reactor.NOW)
        # self.app.listen(9090)
        # tornado.ioloop.IOLoop.current().start()

    def update_status_callback(self, eventtime):
        print("updating status")
        for name, get_status in self.get_statuses:
            status = get_status(eventtime)
            self.status[name] = status
            print({"name": status})

        return eventtime + 1.

def load_config(config):
    return KlipperWebControl(config)
