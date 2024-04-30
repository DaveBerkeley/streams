#!/bin/env python3

#   TODO : work in progress

from amaranth import *

from streams import Stream

#
#

class Phy:
    def __init__(self):
        self.ws = Signal()
        self.sck = Signal()
        self.sd = Signal()

#
#

class I2SOutput(Elaboratable):

    def __init__(self, width):
        self.width = width
        layout = [ ("left", width), ("right", width) ]
        self.i = Stream(layout=layout, name="i")
        self.enable = Signal()

        self.phy = Phy()
        self.bit = Signal(range(width * 2))
        self.sro = Signal(width * 2)
        self.left  = Signal(width)
        self.right = Signal(width)

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.phy.sd.eq(self.sro[self.width-1]),
            self.phy.ws.eq(self.bit[-1]),
        ]

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
                self.left.eq(self.i.left),
                self.right.eq(self.i.right),
            ]

        half = Signal()

        with m.If(self.enable):
            m.d.sync += half.eq(~half)

        with m.If(self.enable & ~half):
            m.d.sync += self.phy.sck.eq(1)

        with m.If(self.enable & half):

            m.d.sync += [
                self.bit.eq(self.bit + 1),
                self.sro.eq(Cat(0, self.sro)),
                self.phy.sck.eq(0),
            ]

            with m.If(self.bit == 0):
                m.d.sync += self.sro.eq(self.left)

            with m.If(self.bit == self.width):
                m.d.sync += self.sro.eq(self.right)
                m.d.sync += self.i.ready.eq(1)

        return m

    def ports(self): return []

#
#   Read WS/SCK data and generate timing signals

class I2SRxClock(Elaboratable):

    def __init__(self, width):
        self.width = width

        # Inputs
        self.ws = Signal()
        self.sck = Signal()

        self.bit = Signal(width * 2)

        # outputs used by I2SRx units
        self.sample = Signal()  # read the data in line
        self.word = Signal()      # word complete, shift_in data is valid

    def elaborate(self, platform):
        m = Module()
        sck_0 = Signal()
        sck_1 = Signal()
        m.d.sync += sck_0.eq(self.sck)
        m.d.sync += sck_1.eq(sck_0)

        # Sample on the rising edge of SCK
        m.d.comb += self.sample.eq(sck_0 & ~sck_1)
        m.d.comb += self.word.eq(self.sample & (self.bit == 0))

        ws_0 = Signal()
        with m.If(self.sample):

            m.d.sync += self.bit.eq(self.bit + 1)
            m.d.sync += ws_0.eq(self.ws)

            with m.If(ws_0 & ~self.ws):
                # falling edge of WS
                m.d.sync += self.bit.eq(0)

        return m

#
#

class I2SInput(Elaboratable):

    def __init__(self, width, rx_clock=None):
        self.width = width
        self.phy = Phy()

        self.rx_clock = rx_clock

        self.sri = Signal(width * 2)

        layout = [ ("left", width), ("right", width) ]
        self.o = Stream(layout=layout, name="o")

    def elaborate(self, platform):
        m = Module()

        if not self.rx_clock:
            self.rx_clock = I2SRxClock(self.width)
            m.submodules += self.rx_clock

            # connect the rx_clock to the input signals
            m.d.comb += [
                self.rx_clock.ws.eq(self.phy.ws),
                self.rx_clock.sck.eq(self.phy.sck),
            ]

        with m.If(self.o.ready & self.o.valid):
            m.d.sync += self.o.valid.eq(0)

        with m.If(self.rx_clock.sample):

            m.d.sync += self.sri.eq(Cat(self.phy.sd, self.sri))

            with m.If(self.rx_clock.word):
                m.d.sync += [
                    self.o.left.eq(self.sri >> self.width),
                    self.o.right.eq(self.sri),
                    self.o.valid.eq(1),
                ]

        return m

    def ports(self): return []

#   FIN
