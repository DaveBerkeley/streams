
from amaranth import *
from amaranth.sim import *

from streams.stream import Stream 
from streams.sim import SourceSim, SinkSim
from streams.ram import StreamToRam, RamToStream

#
#

def sim_s2ram():
    print("test Stream 2 RAM")

    m = StreamToRam(width=16, depth=1024)
    sim = Simulator(m)

    src = SourceSim(m.i)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()

    def proc():

        yield m.offset.eq(0x234)
        yield m.incr.eq(1)

        packet = [
            0x1234,
            0xaaaa,
            0x5555,
            0x1111,
            0xffff,
            0x8000,
            0x0001,
        ]

        for i, data in enumerate(packet):
            src.push(0, data=data, first=i==0)

        while not src.done():
            yield from tick(10)

        yield m.offset.eq(0xffd)

        for i, data in enumerate(packet):
            src.push(0, data=data, first=i==0)

        while not src.done():
            yield from tick(10)

        # Test the RAM contents

        def check_mem(addr, data):
            d = yield m.mem[addr & 0x3ff]
            assert d == data

        for i, data in enumerate(packet):
            yield from check_mem(i + 0x234, data)

        for i, data in enumerate(packet):
            yield from check_mem(i + 0xffd, data)

    sim.add_clock(1 / 50e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/s2ram.vcd", traces=[]):
        sim.run()

#
#

def sim_ram2s():
    print("test RAM 2 Stream")

    m = RamToStream(width=16, depth=1024)
    sim = Simulator(m)

    sink = SinkSim(m.o, read_data=False)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()

    def proc():

        for i in range(1024):
            yield m.mem[i].eq(i)

        yield m.offset.eq(0x234)
        yield m.N.eq(12)
        yield m.incr.eq(1)

        def read():
            while True:
                d = sink.get_data("data")
                if d and len(d[-1]) == 12:
                    break
                yield from tick(1)

        def on(n=5):
            sink.read_data = True
            yield from tick(n)

        def off(n=5):
            sink.read_data = False
            yield from tick(n)

        yield from on()
        yield from read()
        yield from off()

        yield from on()
        yield from read()
        yield from off()

        # try reading backwards
        yield m.incr.eq(-1)
        yield from on()
        yield from read()
        yield from off()

        # read from one location
        yield m.incr.eq(0)
        yield m.offset.eq(0x100)
        yield from on()
        yield from read()
        yield from off()

        # should have 2 packets, starting at 0x234, one reverse from 0x234, one constant from 0x100
        d = sink.get_data("data")
        assert len(d) == 4

        p = [ (i+0x234) for i in range(12) ]
        assert d[0] == p, (p, d[0])
        assert d[1] == p, (p, d[1])

        p = [ (0x234-i) for i in range(12) ]
        assert d[2] == p, (p, d[2])

        p = [ 0x100 for i in range(12) ]
        assert d[3] == p, (p, d[3])

    sim.add_clock(1 / 50e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/ram2s.vcd", traces=[]):
        sim.run()

#
#

def test(verbose):
    sim_s2ram()
    sim_ram2s()

#   FIN
