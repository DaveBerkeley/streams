#
#   Test Class, acts as passive Monitor

class MonitorSim:
    def __init__(self, stream, name="MonitorSim"):
        self.m = stream
        self.name = name
        self._data = [ [] ]
        self._layout = stream.get_layout(flags=True)
        self.t = 0

    def reset(self):
        self._data = [ [] ]

    def poll(self):
        self.t += 1
        r = yield self.m.ready
        v = yield self.m.valid
        f = yield self.m.first
        if r and v:
            if f:
                if len(self._data[0]):
                    self._data += [ [ ] ]
            record = { "_t" : self.t, }
            for name, _ in self._layout: 
                s = getattr(self.m, name)
                d = yield s
                record[name] = d
            self._data[-1].append(record)

    def get_data(self, field=None): 
        if field:
            return [ [ d[field] for d in p ] for p in self._data ]
        return self._data

#
#   Test Class, acts as Sink

class SinkSim(MonitorSim):
    def __init__(self, stream, name="SinkSim", read_data=True):
        MonitorSim.__init__(self, stream, name=name)
        self.read_data = read_data

    def reset(self):
        MonitorSim.reset(self)
        yield self.m.ready.eq(0)

    def poll(self):
        yield from MonitorSim.poll(self)
        r = yield self.m.ready
        v = yield self.m.valid
        if r and v:
            yield self.m.ready.eq(0)
        elif not r:
            if self.read_data:
                yield self.m.ready.eq(1)

#
#   Test Class : acts as source

class SourceSim:

    def __init__(self, stream, verbose=False, name="Source"):
        self.m = stream
        self.verbose = verbose
        self.name = name
        self._data = []
        self.idx = 0
        self.t = 0

    def push(self, t, **kwargs):
        self._data.append((t, kwargs))

    def reset(self):
        self._data = []
        self.idx = 0
        yield self.m.valid.eq(0)

    def poll(self):

        v = yield self.m.valid
        r = yield self.m.ready

        self.t += 1

        if v and r:
            yield self.m.valid.eq(0)
            return

        if v:
            return

        if self.idx >= len(self._data):
            return

        tt, data = self._data[self.idx]
        if tt > self.t:
            return

        # Tx next data (including first/last flags)
        if self.verbose:
            print(self.name, "tx", tt, data)
        v = self.m.cat_dict(data, flags=True)
        for cmd in self.m.payload_eq(v, flags=True):
            yield cmd
        yield self.m.valid.eq(1)
        self.idx += 1

#   FIN
