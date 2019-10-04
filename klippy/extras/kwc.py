import logging

class KlipperWebControl:
    def __init__(self, config):
        self.printer = config.get_printer()
        reactor = self.printer.get_reactor()
        self.status_timer = reactor.register_timer(self.update_status_callback)
        self.get_statuses = []
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.status = {}

    def handle_ready(self):
        self.get_statuses = [(name, o.get_status) for name, o in self.printer.lookup_objects() if hasattr(o, 'get_status')]
        reactor = self.printer.get_reactor()
        reactor.update_timer(self.status_timer, reactor.NOW)

    def update_status_callback(self, eventtime):
        for name, get_status in self.get_statuses:
            self.status[name] = get_status(eventtime)

        return eventtime + 1.

def load_config(config):
    return KlipperWebControl(config)
