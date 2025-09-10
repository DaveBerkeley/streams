#!/bin/env python3

import sys

from amaranth import *

from amaranth.sim import *

sys.path.append(".")
sys.path.append("streams/streams")

from streams.stream import Stream, to_packet, Arbiter
from streams.sim import SinkSim, SourceSim

from streams.route import Head, Router, StreamSync, Packetiser, Event, Sequencer, Select, Collator, MuxDown, MuxUp

#
#

def sim_head(m, n):
    print("test head")
    sim = Simulator(m)

    sink = SinkSim(m.o)
    src = SourceSim(m.i)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()
            yield from src.poll()

    def proc():

        packets = [
            [ 0, [ 1, 2, 3, 4, 5, 6 ], ],
            [ 20, [ 32, 2, 123, ], ],
            [ 35, [ 8, 9, 10, 11, 12 ], ],
            [ 40, [ 1, 0, 1, 7 ], ],
            [ 40, [ 16, 4, 5, 6, 7, 8 ], ],
            [ 80, [ 32, 2, 123, 345, ], ],
            [ 100, [ 32, 2, ], ],
            [ 100, [ 123, ], ],
            [ 100, [ 1, 2, 3, 4, ], ],
        ]

        yield from tick(5)

        for t, packet in packets:
            for i, data in enumerate(packet):
                src.push(t, data=data, first=(i==0), last=(i == (len(packet)-1)))

        def check_head(packet):
            v = yield m.valid
            if not v: return

            # check the 'head' data is correct

            h = []
            for i, d in enumerate(packet):
                if i >= n:
                    break
                x = yield m.head[i]
                h.append(x)

            #print(h, packet)
            assert h == packet[:len(h)], (h, packet)

        def wait_packet(packet):
            while True:

                # wait for the end of the packet
                r = yield m.i.ready
                v = yield m.i.valid
                l = yield m.i.last

                yield from tick(1)
                yield from check_head(packet)

                if r and v and l:
                    break

        for _,packet in packets:
            yield from wait_packet(packet)

        yield from tick(10)

        d = sink.get_data("data")
        print(d)
        idx = 0
        for i, (t, p) in enumerate(packets):
            if len(p) > 3:
                # packet should have head stripped
                assert d[idx] == p[n:], (d, p)
                idx += 1

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/head.vcd", traces=[]):
        sim.run()

#
#

def sim_router(m, addrs):
    print("test router", addrs)
    sim = Simulator(m)

    esink = SinkSim(m.e)
    src = SourceSim(m.i)
    sinks = {}
    for addr in addrs:
        s = SinkSim(m.o[addr])
        sinks[addr] = s

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from esink.poll()
            yield from src.poll()
            for addr in addrs:
                yield from sinks[addr].poll()

    def proc():

        packets = [
            [ 0, [ 1, 2, 3, 4, ], ],
            [ 20, [ 3, 4, 5 ], ],
            [ 40, [ 1, 0, 1 ], ],
            [ 40, [ 16, 4, 5, 6, 7, 8 ], ],
            [ 80, [ 32, 2 ], ],
        ]

        yield from tick(5)

        for t, packet in packets:
            for i, data in enumerate(packet):
                src.push(t, data=data, first=(i==0), last=(i == (len(packet)-1)))

        while True:
            yield from tick(1)
            if src.done():
                break

        yield from tick(5)

        # route the packets manually into a dict
        route = {}
        for t,packet in packets:
            addr, packet = packet[0], packet[1:]
            s = sinks.get(addr, esink)
            route[s] = route.get(s, []) + [ packet ]

        for s in route.keys():
            assert route[s] == s.get_data("data"), (s, route[s], s.get_data("data"))

        print("pass")
            
    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/router.vcd", traces=[]):
        sim.run()

#
#

def sim_sync(m):
    print("test sync")
    sim = Simulator(m)

    sink = SinkSim(m.o)
    src = SourceSim(m.i)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()
            yield from src.poll()

    def proc():

        packets = [
            [ 0, [ 1, 2, 3, 4, ], ],
            [ 20, [ 3, 4, 5 ], ],
            [ 40, [ 1, 0, 1 ], ],
            [ 40, [ 16, 4, 5, 6, 7, 8 ], ],
            [ 80, [ 32, 2 ], ],
        ]

        yield from tick(5)

        for t, packet in packets:
            for i, data in enumerate(packet):
                src.push(t, data=data, first=(i==0), last=(i == (len(packet)-1)))

        while True:
            yield from tick(1)
            if src.done():
                break

        yield from tick(5)

        ps = [ p for t,p in packets ]

        assert ps == sink.get_data("data")
        print("pass")

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/sync.vcd", traces=[]):
        sim.run()

#
#

def sim_packetiser(m):
    print("test packetiser")
    sim = Simulator(m)

    sink = SinkSim(m.o)
    src = SourceSim(m.i)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()
            yield from src.poll()

    def proc():

        packets = [
            [ 0, [ 1, 2, 3, 4, ], ],
            [ 20, [ 3, 4, 5 ], ],
            [ 40, [ 1, 0, 1 ], ],
            [ 40, [ 16, 4, 5, 6, 7, 8 ], ],
            [ 80, [ 32, 2 ], ],
            [ 120, [ 123 ], ],
            [ 140, [ 16, 4, 5, 6, 7, ], ],
        ]

        all_data = []
        for _, packet in packets:
            all_data += packet
        def chop(n):
            p = []
            for i in range(0, len(all_data), n):
                p.append(all_data[i:i+n])
            return p

        def start():
            src.reset()
            yield from sink.reset()
            src.t = 0
            for t, packet in packets:
                for i, data in enumerate(packet):
                    src.push(t, data=data)

        def run(n):
            yield from start()
            yield m.max_idx.eq(n-1)
            yield from tick(1)

            while True:
                yield from tick(1)
                if src.done():
                    break

            yield from tick(5)        
            # check the result
            p = sink.get_data("data")
            assert p == chop(n)

        yield from tick(5)
        for n in [ 4, 1, 8, 3 ]:
            yield from run(n)

        print("pass")

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/packetise.vcd", traces=[]):
        sim.run()

#
#

def sim_event(m):
    print("test event")
    sim = Simulator(m)

    sinks = [
        SinkSim(m.o_first),
        SinkSim(m.o_last),
        SinkSim(m.o_data),
    ]
    src = SourceSim(m.i)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            for sink in sinks:
                yield from sink.poll()
            yield from src.poll()

    def proc():

        packets = [
            [ 5, [ 1, 2, 3, 4, ], ],
            [ 20, [ 3, 4, 5 ], ],
            [ 40, [ 1, 0, 1 ], ],
            [ 60, [ 16, 4, 5, 6, 7, 8 ], ],
            [ 80, [ 32, 2 ], ],
            [ 120, [ 123 ], ],
            [ 140, [ 16, 4, 5, 6, 7, ], ],
        ]

        for t, packet in packets:
            for i, data in enumerate(packet):
                src.push(t, data=data, first=i==0, last=i==(len(packet)-1))

        yield m.i.ready.eq(1)

        while True:
            yield from tick(1)
            if src.done():
                break

        yield from tick(20)

        # the timestamp of each event should be the start time of the packet plus 2 * len(packet)
        r = []
        for t, packet in packets:
            r.append(t + (2 * len(packet)))

        # extract the time stamp for each item in the (single) packet
        p = sinks[1].get_data()[0]

        def get_t(idx):
            p = sinks[idx].get_data()[0]
            return [ x['_t'] for x in p ]

        # last
        p = get_t(1)
        r = []
        for t, packet in packets:
            r.append(t + (2 * len(packet)))
        assert p==r, (p, r)

        # first
        p = get_t(0)
        r = []
        for t, packet in packets:
            r.append(t + 2)
        assert p == r, (p)

        # data
        p = get_t(2)
        r = []
        for t, packet in packets:
            for i, data in enumerate(packet):
                r.append(t + (2 * (i+1)))
        assert p == r, (p)
        print("pass")

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/event.vcd", traces=[]):
        sim.run()

#
#

def sim_seq(m):
    print("test seq")
    sim = Simulator(m)

    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()

    def proc():

        def run(base, n, incr):
            yield m.base.eq(base)
            yield m.incr.eq(incr)
            yield m.count.eq(n)

            yield from tick(5)
            yield m.enable.eq(1)
            yield from tick(1)
            yield m.enable.eq(0)

            while True:
                yield from tick(1)
                a = sink.get_data("data")[-1]
                if len(a) == n:
                    break

            yield from tick(10)

        bursts = [
            [ 0, 10, 1, ],
            [ 0, 5, -2, ],
            [ 0, 1, 100, ],
            [ -5, 8, 1, ],
            [ 123, 4, 0, ],
        ]

        def make_seq(start, n, incr):
            d = []
            for i in range(n):
                d.append(start & 0xffffffff)
                start += incr
            return d

        for start, n, incr in bursts:
            yield from run(start, n, incr)

        for i, packet in enumerate(sink.get_data("data")):
            start, n, incr = bursts[i]
            s = make_seq(start, n, incr)
            assert s == packet, (i, s, packet)

        print("pass")

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/seq.vcd", traces=[]):
        sim.run()

#
#

def sim_select(m, with_sink, ignore_packets=False):
    print("test select", ["", "sink"][with_sink])
    sim = Simulator(m)

    sink = SinkSim(m.o)
    src = []
    for s in m.i:
        src.append(SourceSim(s))

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()
            for s in src:
                yield from s.poll()
            if ignore_packets:
                for s in src:
                    yield s.m.first.eq(1)
                    yield s.m.last.eq(1)

    def proc():

        packets = [
            [   0, 5, [ 0, 1, 2, 3, 4, ] ],
            [   1, 10, [ 1, 7, 8, 9, 10, 11, ] ],
            [   0, 5, [ 0,  4, 5, ] ],
            [   2, 35, [ 2, ] ],
            [   2, 35, [ 2, 6, 7, 8, 9, ] ],
        ]

        def start():
            sink.reset()
            for idx, t, packet in packets:
                for i, data in enumerate(packet):
                    first = i==0
                    last = i==(len(packet)-1)
                    src[idx].push(t, data=data, first=first, last=last)
 
        chans = [ 0, 1,  0, 2,  0 ]
        ticks = [ 4, 25, 5, 25, 20 ]

        def run():
            for i, t in enumerate(ticks):
                yield m.select.eq(chans[i])
                yield from tick(t)

        start()
        yield from run()
        yield from tick(10)

        r = []
        if with_sink:
            for i in [ 1, 3, 4 ]:
                r.append(packets[i][2])
        else:
            for i in [ 1, 0, 3, 4, 2 ]:
                r.append(packets[i][2])

        d = sink.get_data("data")
        #print(d)
        #print(r)

        if ignore_packets:
            # flatten d
            d = [ x[0] for x in d ] 
            while d:
                for i, x in enumerate(r):
                    if len(x) and (d[0] == x[0]):
                        #print("match", i, d[0], r)
                        d = d[1:]
                        r[i] = r[i][1:]
            for x in r:
                assert len(x) == 0
            print("pass")
            return

        assert r == d, (with_sink, r, d)
        print("pass")

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/select.vcd", traces=[]):
        sim.run()

#
#

def sim_arbiter(m, verbose):
    print("test arbiter")
    sim = Simulator(m)

    src_a = SourceSim(m.i[0], verbose=verbose, name="a")
    src_b = SourceSim(m.i[1], verbose=verbose, name="b")
    src_c = SourceSim(m.i[2], verbose=verbose, name="c")
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src_a.poll()
            yield from src_b.poll()
            yield from src_c.poll()
            yield from sink.poll()

    def proc():

        data = [
            [ 10, src_a, [ 1, 6, 3, ], ],
            [ 20, src_b, [ 2, 5, 6, ], ],
            [ 35, src_a, [ 1, 8, 9, ], ],
            [ 35, src_b, [ 2, 8, 9, ], ],
            [ 60, src_a, [ 1, ], ],
            [ 61, src_b, [ 2, ], ],
            [ 70, src_a, [ 1, ], ],
            [ 70, src_b, [ 2, ], ],
            [ 70, src_c, [ 3, ], ],
            [ 80, src_c, [ 3, 8, 9, ], ],
            [ 80, src_b, [ 2, 8, 9, ], ],
            [ 81, src_a, [ 1, 6, 10, ], ],
            [ 82, src_b, [ 2, 11, 12, ], ],
        ]

        for i, (t, s, d) in enumerate(data):
            p = to_packet(d)
            print(p)
            for x in p:
                s.push(t, **x)

        #while len(sink.get_data()) < len(data):
        #   yield from tick()

        yield from tick(5)
        yield from tick(5000)

        d = sink.get_data("data")
        print(d)

        # packets from each source should be in order in the output
        a = []
        b = []
        c = []
        for _, s, p in data:
            if s == src_a:
                a.append(p)
            elif s == src_b:
                b.append(p)
            elif s == src_c:
                c.append(p)
            else:
                assert 0, ("bad packet", p)

        #for s in [ a, b, c ]:
        #    for p in s:
        #        found = False
        #        for i, pp in enumerate(d):
        #            if p[0] == pp[0]:
        #                # this source, so remove the packet
        #                found = True
        #                del d[i]
        #                break
        #        assert found, (s, p)

        #assert len(d) == 0

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd(f"gtk/arb.vcd", traces=[]):
        sim.run()

#
#

def sim_collator(m, verbose):
    print("test collator")
    sim = Simulator(m)

    src_a = SourceSim(m.i[0], verbose=verbose, name="a")
    src_b = SourceSim(m.i[1], verbose=verbose, name="b")
    src_c = SourceSim(m.i[2], verbose=verbose, name="c")
    src_d = SourceSim(m.i[3], verbose=verbose, name="d")
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src_a.poll()
            yield from src_b.poll()
            yield from src_c.poll()
            yield from src_d.poll()
            yield from sink.poll()

    def proc():

        data = [
            [ 10, src_a, [ 1, 2, 3, ], ],
            [ 20, src_b, [ 1, 2, 3, ], ],
            [ 35, src_a, [ 4, 5, 6, ], ],
            [ 35, src_b, [ 4, 5, 6, ], ],
            [ 60, src_a, [ 7, ], ],
            [ 61, src_b, [ 7, ], ],
            [ 70, src_a, [ 8, ], ],
            [ 70, src_b, [ 8, ], ],
            [ 70, src_d, [ 1, 2, 3, 4, 5 ], ],
            [ 70, src_c, [ 1, ], ],
            [ 80, src_c, [ 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 ], ],
            [ 80, src_b, [ 9, 10, 11, ], ],
            [ 100, src_a, [ 9, 10, 11, ], ],
            [ 100, src_d, [ 6, 7, 8, 9, 10, 11,  ], ],
            [ 110, src_b, [ 12, 13, 14, 15, ], ],
            [ 110, src_a, [ 12, 13, 14, 15, ], ],
            [ 110, src_d, [ 12, 13, 14, 15, ], ],
        ]

        for i, (t, s, d) in enumerate(data):
            p = to_packet(d)
            print(p)
            for x in p:
                s.push(t, **x)

        #while len(sink.get_data()) < len(data):
        #   yield from tick()

        yield from tick(5)

        while True:
            yield from tick(1)
            if not src_a.done():
                continue
            if not src_b.done():
                continue
            if not src_c.done():
                continue
            if not src_d.done():
                continue
            break

        yield from tick(20)

        d = sink.get_data("data")
        #print(d)

        # packets from each source should be in order in the output
        for i, p in enumerate(d):
            assert p == [ i+1, i+1, i+1, i+1, ], (i, p)


    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd(f"gtk/collator.vcd", traces=[]):
        sim.run()

#
#

def sim_mux(m, verbose):
    print("test mux")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()

    def proc():

        data = [
            [ 10, [ 0x12345678, 0x11223344, 0x0, 0xffffffff, 0x12345678, ], ],
            [ 40, [ 1, 2, 3, 4 ], ],
            [ 80, [ 0 ], ],
            [ 80, [ 1 ], ],
            [ 120, [ 0xffffffff ], ],
            [ 140, [ 1, 2, 3, 4 ], ],
        ]

        for i, (t, d) in enumerate(data):
            p = to_packet(d)
            print(p)
            for x in p:
                src.push(t, **x)

        yield from tick(5)

        while True:
            yield from tick(1)
            if src.done():
                break

        yield from tick(20)

        r = [
            [   
                0x78, 0x56, 0x34, 0x12, 
                0x44, 0x33, 0x22, 0x11, 
                0, 0, 0, 0, 
                0xff, 0xff, 0xff, 0xff, 
                0x78, 0x56, 0x34, 0x12, 
            ],
            [
                1, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0, 4, 0, 0, 0, 
            ],
            [
                0, 0, 0, 0,
            ],
            [
                1, 0, 0, 0,
            ],
            [
                0xff, 0xff, 0xff, 0xff, 
            ],
            [
                1, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0, 4, 0, 0, 0, 
            ],
        ]

        d = sink.get_data("data")
        #for p in d:
        #    print([ hex(a) for a in p ])
        assert d == r

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd(f"gtk/mux.vcd", traces=[]):
        sim.run()

#
#

from streams.spi import SpiController, SpiClock

class SpiMux(Elaboratable):

    def __init__(self):

        self.spi = SpiController(width=8, last_cs=True)
        self.mux = MuxDown(32, 8)

        self.mods = [
            self.spi,
            self.mux,
        ]

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.mods
        m.d.comb += Stream.connect(self.mux.o, self.spi.i)
        return m

def sim_spi(m, verbose):
    print("test spi mux")
    sim = Simulator(m)

    src = SourceSim(m.mux.i, verbose=verbose)
    ck = SpiClock(m.spi.enable, 10)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from ck.poll()

    def proc():

        data = [
            [ 10, [ 0x12345678, 0x11223344, 0x0, 0xffffffff, 0x12345678, ], ],
            [ 40, [ 1, 2, 3, 4 ], ],
            [ 7000, [ 0 ], ],
            [ 8000, [ 1 ], ],
            [ 12000, [ 0xffffffff ], ],
            [ 14000, [ 1, 2, 3, 4 ], ],
        ]
        data = [
             [ 100, [ 1, 2 ] ],
             [ 2000, [ 0 ] ],
             [ 4000, [ 3 ] ],
             [ 6000, [ 4, 5, 6, 7 ] ],
        ]

        for i, (t, d) in enumerate(data):
            p = to_packet(d)
            print(p)
            for x in p:
                src.push(t, **x)

        yield from tick(5)

        while True:
            yield from tick(1)
            if src.done():
                break

        while True:
            yield from tick(500)
            cs = yield m.spi.phy.scs
            if cs:
                break

        yield from tick(50)

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd(f"gtk/spimux.vcd", traces=[]):
        sim.run()

#
#

def sim_muxup(m, verbose):
    print("test muxup")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()

    def proc():

        data = [
            [ 10, [ 1, 2, 3, 4 ], ],
            [ 30, [ 0 ], ],
            [ 30, [ 1 ], ],
            [ 50, [ 0xffffffff ], ],
            [ 50, [ 1, 2, 3, 4 ], ],
            [ 80, [ 0x12, 0x23, 0x34 ], ],
            [ 80, [ 0x11, 0x22, 0x33, 0x44 ], ],
            [ 100, [ 0x11, 0x22, 0x33, 0x44, 0x55 ], ],
        ]

        for i, (t, d) in enumerate(data):
            p = to_packet(d)
            for x in p:
                src.push(t, **x)

        yield from tick(5)

        while True:
            yield from tick(1)
            if src.done():
                break

        yield from tick(10)

        r = [
            [ 0x0102, 0x0304, ],
            [ 0 ],
            [ 1 ],
            [ 0xff ],
            [ 0x0102, 0x0304 ],
            [ 0x1223, 0x34 ],
            [ 0x1122, 0x3344 ],
            [ 0x1122, 0x3344, 0x55 ],
        ]

        d = sink.get_data("data")
        #for p in d:
        #    print([ hex(a) for a in p ])
        assert d == r

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd(f"gtk/muxup.vcd", traces=[]):
        sim.run()

#
#

def test(verbose):
    args = sys.argv
    if len(args) == 2:
        name = args[1]
        test_all = False
    else:
        name = ""
        test_all = True

    if test_all or (name=="Head"):
        layout = [("data", 16)]
        n = 3
        dut = Head(layout=layout, data_field="data", n=3)
        sim_head(dut, n)

    if test_all:
        layout = [("data", 16)]
        addrs = [ 1, 0x10, 0x20 ]
        dut = Router(layout=layout, addr_field="data", addrs=addrs)
        sim_router(dut, addrs)

    if test_all:
        layout = [("data", 16)]
        dut = StreamSync(layout)
        sim_sync(dut)

    if test_all:
        layout = [("data", 16)]
        dut = Packetiser(layout, max_psize=1024)
        sim_packetiser(dut)

    if test_all:
        dut = Event(["first", "last", "data"])
        sim_event(dut)

    if test_all:
        dut = Sequencer()
        sim_seq(dut)

    if (name=="Select") or test_all:
        layout = [("data", 16)]
        dut = Select(layout=layout, n=4, sink=False)
        sim_select(dut, with_sink=False)

        dut = Select(layout=layout, n=4, sink=True)
        sim_select(dut, with_sink=True)

        dut = Select(layout=layout, n=4, sink=False)
        sim_select(dut, with_sink=False, ignore_packets=True)

    if test_all:
        dut = Arbiter(n=3, layout=[("data", 16)])
        sim_arbiter(dut, True) 

    if test_all:
        dut = Collator(n=4, layout=[("data", 16)])
        sim_collator(dut, True) 

    if test_all:
        dut = MuxDown(iwidth=32, owidth=8)
        sim_mux(dut, True)

    if test_all:
        dut = SpiMux()
        sim_spi(dut, True)

    if test_all:
        dut = MuxUp(iwidth=8, owidth=16)
        sim_muxup(dut, True)

    from streams import dot
    dot_path = "/tmp/wifi.dot"
    png_path = "test.png"
    dot.graph(dut, dot_path, png_path)
    
if __name__ == "__main__":
    test(True)


# FIN
