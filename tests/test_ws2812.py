#!/bin/env python3

from amaranth.sim import *

import sys
spath = "../streams"
if not spath in sys.path:
    sys.path.append(spath)


from streams.stream import Stream 
from streams.sim import SinkSim, SourceSim

from streams.ws2812 import LedStream

def sim_leds(m, verbose):
    print("test WS2812")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()

    def proc():

        def wait_idle(state):
            while True:
                yield from tick(1)
                d = yield m.idle
                if d == state:
                    break

        src.push(100, addr=0, r=0, g=0, b=0)
        src.push(100, addr=1, r=0, g=0, b=0xFF)
        src.push(100, addr=2, r=0, g=0, b=0)

        yield from wait_idle(0)
        yield from wait_idle(1)
        yield from tick(100)

        src.push(100, addr=2, r=0xff, g=0xff, b=0xff)
        src.push(100, addr=3, r=0, g=0, b=0)
        
        yield from wait_idle(0)
        yield from wait_idle(1)
        yield from tick(100)

    sim.add_clock(1 / 50e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/ws2812.vcd", traces=[]):
        sim.run()

#
#

def test(verbose):
    dut = LedStream(4, 50e6)
    sim_leds(dut, verbose)

if __name__ == "__main__":
    test(True)

# FIN
