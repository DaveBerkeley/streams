#!/bin/env python

import sys

from amaranth import *
from amaranth.sim import *

sys.path.append(".")
sys.path.append("streams/streams")

from streams.sim import SinkSim, SourceSim
from streams.monitor import MonitorText

#
#

def sim_monitor_text(m):
    print("test monitor_text")
    sim = Simulator(m)

    source = SourceSim(m.i)
    sink = SinkSim(m.o)

    polls = [ source, sink ]

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            for s in polls:
                yield from s.poll()

    def proc():

        def wait_sources(ss):
            loop = True
            while loop:
                busy = False
                for s in ss:
                    if not s.done():
                        busy = True
                loop = busy
                yield from tick(1)

        p = [
            [ 5, { "abc": 0x12345678, "data" : 0x13, "test" : 0x234 } ],
            [ 80, { "abc": 0x100, "data" : 0x22, "test" : 0 } ],
        ]

        for t, x in p:
            source.push(t, **x)

        yield from tick(1)
        yield from wait_sources([ source ])
        yield from tick(100)
        d = sink.get_data("data")
        text = "".join([ chr(x) for x in d[0] ])
        #print(text)
        assert text == "abc 12345678 data 13 test 234\r\nabc 00000100 data 22 test 000\r\n"

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/monitor_text.vcd", traces=[]):
        sim.run()

#
#

def test(verbose):
    if len(sys.argv) > 1:
        test_all = False
        name = sys.argv[1]
    else:
        test_all = True
        name = ""

    if test_all:
        dut = MonitorText(layout=[("abc", 32), ("data", 6), ("test", 12)])
        sim_monitor_text(dut)

    from streams import dot
    dot_path = "/tmp/test.dot"
    png_path = "test.png"
    dot.graph(dut, dot_path, png_path)
    
if __name__ == "__main__":
    test(False)

#   FIN
