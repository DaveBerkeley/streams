#!/bin/env python3

from enum import IntEnum, unique

from amaranth import *

from amaranth.lib.cdc import FFSynchronizer

from streams import Stream, StreamInit, to_packet

#
#

class Phy:
    def __init__(self):
        self.sck = Signal()
        self.scs = Signal(reset=1)
        self.cipo = Signal()
        self.copi = Signal()

@unique
class State(IntEnum):
    IDLE, BUSY, PAUSE, STOP = range(4)

class SpiController(Elaboratable):

    def __init__(self, width, init=[], cpol=0, cpha=0, last_cs=False, name="SpiController"):
        self.width = width
        self.last_cs = last_cs
        self.cpol = Signal(reset=cpol)
        self.cpha = Signal(reset=cpha)

        self.phy = Phy()

        self.cipo = Signal() # synchronised in
        self.sck = Signal()

        self.enable = Signal() # 2clock
        self.transition = Signal() # delayed 2clock
        self.half = Signal()

        self.p1 = Signal()
        self.p2 = Signal()
        self.shift = Signal()
        self.sample = Signal()
        self.wait = Signal()
        self.ilast = Signal()
        self.odata = Signal(width)

        layout = [ ("data", width), ]
        self.i = Stream(layout, name=f"{name}_i")
        self._i = Stream(layout, name=f"{name}_int")
        self.o = Stream(layout, name=f"{name}_o")
        if init:
            self.init = StreamInit(init, layout)
            self.starting = Signal(reset=1)
        else:
            self.init = None
            self.starting = Signal()

        self.sro = Signal(width)
        self.sri = Signal(width)

        self.bit = Signal(range(width+1))

        self.state = Signal(State, reset=State.IDLE)

    def is_idle(self):
        return self.state == State.IDLE

    def elaborate(self, platform):
        m = Module()

        m.submodules += FFSynchronizer(self.phy.cipo, self.cipo)
        m.submodules += FFSynchronizer(self.enable, self.transition)

        if self.init:
            m.submodules += self.init

        if self.init:
            with m.If(self.starting):
                m.d.comb += Stream.connect(self.init.o, self._i)
            with m.Else():
                m.d.comb += Stream.connect(self.i, self._i)

            m.d.comb += self.starting.eq(~self.init.done)
        else:
            m.d.comb += Stream.connect(self.i, self._i)

        m.d.comb += [
            self.phy.copi.eq(self.sro[self.width - 1]),
            self.phy.sck.eq(self.half ^ self.cpol),
        ]

        m.d.comb += [
            self.p1.eq(0),
            self.p1.eq(0),
        ]

        with m.If(self.state == State.BUSY):
            m.d.comb += [
                self.p1.eq(self.transition & ~self.half),
                self.p2.eq(self.transition & self.half),
            ]

        with m.If(self.cpha):
            m.d.comb += [
                self.sample.eq(self.p2),
                self.shift.eq(self.p1 & ~self.wait),
            ]
        with m.Else():
            m.d.comb += [
                self.sample.eq(self.p1),
                self.shift.eq(self.p2 & ~self.wait),
            ]

        with m.If(self._i.ready):
            m.d.sync += self._i.ready.eq(0)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += [
                self.o.valid.eq(0),
                self.o.first.eq(0),
            ]

        def read():
            return [
                self.sro.eq(self._i.data),
                self.ilast.eq(self._i.last),
                self._i.ready.eq(1),
                self.bit.eq(self.width),
            ]

        def stop():
            return [
                self.phy.scs.eq(1),                    
                self.half.eq(0),
                self.state.eq(State.STOP)
            ]
 
        with m.If(self.state == State.IDLE):

            m.d.sync += [
                self._i.ready.eq(0),
                self.phy.scs.eq(1),
                self.half.eq(0),
                self.o.first.eq(1),
            ]

            with m.If(self._i.valid & self.transition):
                # Start Tx
                m.d.sync += read()
                m.d.sync += [
                    self.phy.scs.eq(0),
                    self.wait.eq(1),
                    self.state.eq(State.BUSY),
                ]

        with m.If(self.state == State.BUSY):

            with m.If(self.transition):
                m.d.sync += self.half.eq(~self.half)
                with m.If(self.half):
                    m.d.sync += self.bit.eq(self.bit - 1)

            with m.If(self.sample):
                m.d.sync += [
                    self.sri.eq(Cat(self.phy.cipo, self.sri)),
                    self.wait.eq(0),
                ]

            with m.If(self.shift):
                m.d.sync += [
                    self.sro.eq(Cat(0, self.sro)),
                ]

            with m.If(self.transition & (self.bit == 0)):

                #   Tx data
                m.d.sync += [
                    self.o.data.eq(self.sri),
                    self.o.valid.eq(1),
                    self.o.last.eq(self.ilast),
                ]

                if self.last_cs:
                    # needs 'last' on input stream, to transition to 'STOP'
                    with m.If(self.ilast):
                        # Only STOP when the 'last' flag is set
                        m.d.sync += stop()
                    with m.Else():
                        # restart the bit counter, get next word
                        m.d.sync += [
                            self.bit.eq(self.width),
                            self.state.eq(State.PAUSE),
                            self.half.eq(0),
                            self.wait.eq(self.cpha),
                            self._i.ready.eq(1),
                        ]

                else:
                    m.d.sync += stop()

        with m.If(self.state == State.PAUSE):

            with m.If(self.i.valid & self.i.ready):
                m.d.sync += read()
                m.d.sync += self.state.eq(State.BUSY)

        with m.If(self.state == State.STOP):

            with m.If(self.transition):
                m.d.sync += [
                    self.state.eq(State.IDLE),
                ]

        return m

    def ports(self):
        return [
            self.phy.sck, 
            self.phy.scs, 
            self.phy.copi, 
            self.phy.cipo, 
        ]

#
#   SPI Peripheral

class SpiReadPacket(Elaboratable):
    """
    Delay output until first/last status is available
    """

    def __init__(self, layout):
        self.i = Stream(layout, name="SpiReadPacket_i")
        self.o = Stream(layout, name="SpiReadPacket_o")
        # connect to SpiPeripheral internal signals
        self.stop = Signal()
        self.sample = Signal()

        self.wait = Signal() # set on 'i.valid'. Wait for 'sample' or 'stop'

    def elaborate(self, platform):
        m = Module()

        # 'first' is handled by SpiPeripheral Module
        exclude = [ "last", "valid", "ready" ]
        m.d.comb += Stream.connect(self.i, self.o, exclude=exclude)

        with m.If(self.i.valid & ~self.i.ready):
            m.d.sync += [
                self.wait.eq(1),
                self.o.last.eq(0),
            ]

        with m.If(self.stop):
            m.d.sync += self.wait.eq(0)

        def tx(last):
            return [
                self.o.valid.eq(1),
                self.i.ready.eq(self.o.ready),
                self.o.last.eq(last),
                self.wait.eq(0),
            ]

        with m.If(self.wait):
            # Waiting to see if the word is the last in packet
            with m.If(self.stop):
                m.d.sync += tx(last=1)
            with m.If(self.sample):
                m.d.sync += tx(last=0)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += [
                self.o.valid.eq(0),
                self.i.ready.eq(0),
            ]

        return m

class SpiPeripheral(Elaboratable):

    def __init__(self, width, cpol=0, cpha=0, last_cs=False, name="SpiPeripheral"):
        self.width = width
        self.cpol = Signal(reset=cpol)
        self.cpha = Signal(reset=cpha)

        self.phy = Phy()

        self.sck = Signal()
        self.scs = Signal()
        self.copi = Signal()
        self.cipo = Signal()

        self.scs_0 = Signal()
        self.sck_0 = Signal()

        self.shift = Signal()
        self.sample = Signal()
        self.p1 = Signal()
        self.p2 = Signal()
        self.start = Signal()
        self.stop = Signal()
        self.bit = Signal(range(width))
        self.sri = Signal(width)
        self.sro = Signal(width)

        layout = [ ("data", width), ]
        self.i = Stream(layout=layout, name=f"{name}_i")
        self.o = Stream(layout=layout, name=f"{name}_o")

        self.odata = Signal(width)
        self.has_tx = Signal()

        if last_cs:
            self.rd_packet = SpiReadPacket(layout)
        else:
            self.rd_packet = None

    def elaborate(self, platform):
        m = Module()

        m.submodules += FFSynchronizer(self.phy.copi, self.copi)
        m.submodules += FFSynchronizer(self.phy.scs, self.scs)
        m.submodules += FFSynchronizer(self.phy.sck, self.sck)

        if self.rd_packet:
            m.submodules += self.rd_packet
            # Insert SpiReadPacket() before the output stream
            ostream = self.o
            m.d.comb += Stream.connect(ostream, self.rd_packet.i)
            self.o = self.rd_packet.o
            # connect the sample/stop signals
            m.d.comb += [
                self.rd_packet.stop.eq(self.stop),
                self.rd_packet.sample.eq(self.sample),
            ]
        else:
            ostream = self.o

        m.d.comb += self.phy.cipo.eq(self.cipo)
        m.d.comb += self.cipo.eq(self.sro[self.width-1])

        m.d.sync += [
            self.scs_0.eq(self.scs),
            self.sck_0.eq(self.sck),

            self.p1.eq(self.sck & ~self.sck_0),
            self.p2.eq(self.sck_0 & ~self.sck),
            self.start.eq(self.scs_0 & ~self.scs),
            self.stop.eq(self.scs & ~self.scs_0),
        ]

        # TODO : use cpha, cpol
        m.d.comb += [
            self.sample.eq(self.p1),
            self.shift.eq(self.p2),
        ]

        with m.If(self.sample):
            m.d.sync += self.sri.eq(Cat(self.copi, self.sri))

        with m.If(~self.has_tx):
            m.d.sync += self.i.ready.eq(1)

        with m.If(self.start):
            m.d.sync += [
                self.bit.eq(0),
                ostream.first.eq(1),
            ]
            with m.If(self.has_tx):
                # odata left over from the end of the last CS block
                # but never shifted out
                m.d.sync += self.sro.eq(self.odata)

        with m.If(self.stop):
            # Don't read any more data
            m.d.sync += self.i.ready.eq(0)

        with m.If(self.shift):
            m.d.sync += [
                self.bit.eq(self.bit + 1),
                self.sro.eq(Cat(0, self.sro)),
            ]
            with m.If(self.bit == 1):
                # can get next odata
                m.d.sync += self.has_tx.eq(0)

            with m.If(self.bit == (self.width - 1)):
                # Send the Rxd word to ostream
                m.d.sync += [
                    self.bit.eq(0),
                    ostream.data.eq(self.sri),
                    ostream.valid.eq(1),
                    self.sro.eq(self.odata),
                ]

        with m.If(ostream.valid & ostream.ready):
            m.d.sync += [
                ostream.valid.eq(0),
                ostream.first.eq(0),
            ]

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
                self.odata.eq(self.i.data),
                self.has_tx.eq(1),
            ]

        return m

    def ports(self): return []

#
#   Class used by simulation to read spi serial data
#
#   TODO : needs cpha/cpol support

class SpiIo:

    def __init__(self, width):
        self.width = width
        self.ck = 0
        self.sr = []
        self.bit = 0
        self.cs = 0
        self.rx = []

    def reset(self):
        # start of word
        self.ck = 0
        self.sr = []
        self.bit = 0

    def poll(self, cs, ck, d):
        if cs != self.cs:
            if cs:
                # start of word
                self.reset()
            else:
                # end of word
                data = 0
                for i in range(self.width):
                    data <<= 1
                    if self.sr[i]:
                        data |= 1
                self.rx.append(data)
                self.reset()
        self.cs = cs

        if cs and (ck != self.ck):
            # -ve edge of clock
            if not ck:
                self.bit += 1
                self.sr.append(d)
        self.ck = ck

#
#   Helper class, used when testing SPI devices to generate timing clocks

class SpiClock:

    def __init__(self, s, period):
        self.s = s
        self.t = 0
        self.period = period

    def poll(self):
        self.t += 1
        if (self.t % self.period) == 0:
            yield self.s.eq(1)
        else:
            yield self.s.eq(0)

#   FIN
