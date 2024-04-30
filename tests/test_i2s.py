
import sys

if not "." in sys.path:
    sys.path.append(".")

from amaranth import *
from amaranth.sim import *

from streams.sim import SinkSim, SourceSim
from streams.i2s import I2SOutput, I2SInput

#
#

def sim_o(m, verbose):
    print("test i2s output")

    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)

    info = { "t" : 0 }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()

            info['t'] += 1
            if ((info['t'] % 10) == 0):
                yield m.enable.eq(1)
            else:
                yield m.enable.eq(0)

    def proc():

        data = [
            [ 0xaaaa, 0x5555, ],
            [ 0x1111, 0x2222, ],
            [ 0x0000, 0xffff, ],
            [ 0xffff, 0x0000, ],
            [ 0x1234, 0x1234, ],
            [ 0x8000, 0x7fff, ],
        ]

        for left, right in data:
            src.push(10, left=left, right=right)

        yield from tick(5000)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/i2s.vcd", traces=m.ports()):
        sim.run()

#
#

def sim_i(m, verbose):
    print("test i2s input")

    class Both(Elaboratable):
        def __init__(self, m, width):
            self.tx = I2SOutput(width)
            self.rx = m
            self.enable = Signal()
        def elaborate(self, platform):
            m = Module()
            m.submodules += self.tx
            m.submodules += self.rx
            m.d.comb += self.tx.enable.eq(self.enable)

            # Connect the PHYs together
            for name in [ "sd", "sck", "ws" ]:
                o = getattr(self.tx.phy, name)
                i = getattr(self.rx.phy, name)
                m.d.comb += i.eq(o)

            return m
        def ports(self): return []

    both = Both(m, m.width)
    sim = Simulator(both)

    m = both
    src = SourceSim(m.tx.i, verbose=verbose)
    sink = SinkSim(m.rx.o)

    info = { "t" : 0 }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()

            info['t'] += 1
            if ((info['t'] % 10) == 0):
                yield m.enable.eq(1)
            else:
                yield m.enable.eq(0)

    def proc():

        data = [
            [ 0xaaaa, 0x5555, ],
            [ 0x1111, 0x2222, ],
            [ 0x0000, 0xffff, ],
            [ 0xffff, 0x0000, ],
            [ 0x1234, 0x1234, ],
            [ 0x8000, 0x7fff, ],
        ]

        for left, right in data:
            src.push(10, left=left, right=right)

        yield from tick(5000)

        r = [ [d['left'], d['right']] for d in sink.get_data()[0] ]
        # discard the first two frames 
        r = r[2:]
        assert data == r, r

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/i2s_i.vcd", traces=m.ports()):
        sim.run()

#
#

def test(verbose):
    dut = I2SOutput(16)
    sim_o(dut, verbose)

    dut = I2SInput(16)
    sim_i(dut, verbose)

    print("done")

if __name__ == "__main__":
    test(True)

#   FIN
