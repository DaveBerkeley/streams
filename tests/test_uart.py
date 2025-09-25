#!/bin/env python

import sys

from amaranth import *
from amaranth.sim import Simulator, Tick

sys.path.append(".")
sys.path.append("../streams")

from streams import Stream
from streams.sim import SinkSim, SourceSim

from streams.uart import UART_Tx

def load_packet(s, t, packet):
    for i, data in enumerate(packet):
        s.push(t, first=(i==0), last=(i == (len(packet)-1)), data=data)

#
#

def sim_uarttx(m, mod):
    print('run simulation', m.__class__.__name__)
    sim = Simulator(m)

    src = SourceSim(m.i)

    streams = [ src ]

    info = {
        't' : 0,
    }

    def tick(n=1):
        for i in range(n):
            yield Tick()
            for s in streams:
                yield from s.poll()
            # baud rate gen
            info['t'] += 1
            yield m.en.eq((info['t'] % mod) == 0)

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

        test = [ 
            0x5555,
            0xffff, 0xE122, 0x0000, 0xaaaa, 
            0x5a5a, 0x1122, 0x0f0f, 0x8090,
            0xc1d2,
            0xaaaa,
        ]

        yield from tick(5)
        load_packet(src, 30, test)

        yield from wait_sources([ src ])

        yield from tick((mod+1) * (16+2))
        yield from tick(10)

    sim.add_clock(12e-6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/uarttx.vcd"):
        sim.run()

#
#

def test(verbose=False):
    test_all = True
    name = None
    if len(sys.argv) > 1:
        name = sys.argv[1]
        test_all = False

    sys_ck = 50e6

    if (name == "UART_Tx") or test_all:
        mod = 5
        dut = UART_Tx(bits=16)
        sim_uarttx(dut, mod)

    from streams import dot
    dot_path = "/tmp/test.dot"
    png_path = "test.png"
    dot.graph(dut, dot_path, png_path)
 
if __name__ == '__main__':
    test()

#   FIN 
