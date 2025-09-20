#!/bin/env python

import sys

from amaranth import *
from amaranth.sim import Simulator, Tick

sys.path.append(".")
sys.path.append("../streams")

from streams import Stream
from streams.sim import SinkSim, SourceSim

from streams.sk9822 import Tx, SK9822

def load_packet(s, t, packet):
    for i, data in enumerate(packet):
        s.push(t, first=(i==0), last=(i == (len(packet)-1)), **data)

#
#

def rgbi(r, g, b, i):
    assert (r >= 0) and (r < 256)
    assert (g >= 0) and (g < 256)
    assert (b >= 0) and (b < 256)
    assert (i >= 0) and (i < 32)
    return (i << 24) + (b << 16) + (g << 8) + r

#
#

def led_rx(m):
    # read the serial data back
    d = 0
    for i in range(32):
        # wait for a rising edge of the co
        while not (yield m.co):
            yield Tick()
        x = yield m.do
        d <<= 1
        d += x
        # wait for a falling edge of the co
        while (yield m.co):
            yield Tick()

    return d

def led_tx(m, data):
    # wait for ready
    while not (yield m.rdy):
        yield Tick()

    # load data
    yield m.tx_data.eq(data)
    yield m.ack.eq(1)
    yield Tick()
    yield m.ack.eq(0)

    yield Tick()

    d = yield from led_rx(m)
    return d

#
#

def sim_tx(m):
    print('run simulation', m.__class__.__name__)
    sim = Simulator(m)

    def proc():

        for i in range(10):
            yield Tick()

        test = [ 
            0xffffffff, 0xE1223344, 0x00000000, 0xaaaaaaaa, 
            0x5a5a5a5a, 0x11223344, 0x0f0f0f0f, 0x8090a0b0,
            0xc1d2e3f4,
        ]

        for j in range(3):
            for i, data in enumerate(test):
                x = yield from led_tx(m, data)
                assert x == data, (hex(x), hex(data))
                # put varying delay in before starting a new write
                for x in range(i % 15):
                    yield Tick()

        for i in range(10):
            yield Tick()

    sim.add_clock(12e-6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/tx_led.vcd"):
        sim.run()

#
#

def sim_sk9822(m):
    print('run simulation', m.__class__.__name__)
    sim = Simulator(m)

    src = SourceSim(m.i)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()

    def proc():

        def wait_source(s):
            while True:
                if s.done():
                    break
                yield from tick(1)

        p = [
            [ 10, [ { "addr":0, "r":255, "g":0, "b":0 }, ], ],
            [ 300, [ { "addr":1, "r":0, "g":255, "b":0 }, ], ],
            [ 900, [ { "addr":3, "r":63, "g":63, "b":255 }, ], ],
        ]

        for t, packet in p:
            load_packet(src, t, packet)

        wait_source(src)
        yield from tick(30)

        while True:
            r = yield m.busy
            if not r:
                break
            yield from tick(1)

        yield from tick(30)

    sim.add_clock(12e-6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/sk9822.vcd"):
        sim.run()

#
#

def test(verbose=False):
    test_all = True
    name = None
    if len(sys.argv) > 1:
        name = sys.argv[1]
        test_all = False

    leds = 4
    sys_ck = 50e6

    if (name == "Tx") or test_all:
        dut = Tx(leds)
        sim_tx(dut)

    if (name == "SK9822") or test_all:
        dut = SK9822(sys_ck, leds, ck_freq=10e6)
        sim_sk9822(dut)

    from streams import dot
    dot_path = "/tmp/test.dot"
    png_path = "test.png"
    dot.graph(dut, dot_path, png_path)
    
if __name__ == '__main__':
    test()

#   FIN 
