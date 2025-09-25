
from amaranth import *

from streams import Stream

#
#   Simple Tx Stream to UART

class UART_Tx(Elaboratable):

    def __init__(self, bits=8):
        self.bits = bits
        self.i = Stream(layout=[("data", bits)], name="i")
        self.o = Signal(reset=1)
        self.en = Signal() # baud rate enable signal

        self.bit = Signal(range(bits))
        self.sr = Signal(bits)

    def elaborate(self, platform):
        m = Module()

        with m.FSM(reset="IDLE"):

            with m.State("IDLE"):
                with m.If(~self.i.ready):
                    m.d.sync += self.i.ready.eq(1)

                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += [
                        self.i.ready.eq(0),
                        self.sr.eq(self.i.data),
                        self.bit.eq(0),
                    ]
                    m.next = "START"

            with m.State("START"):
                with m.If(self.en):
                    m.d.sync += [
                        self.o.eq(0), # Start Bit
                    ]
                    m.next = "TX"

            with m.State("TX"):
                with m.If(self.en):
                    m.d.sync += [
                        self.o.eq(self.sr), # Data bit
                        self.sr.eq(self.sr >> 1),
                        self.bit.eq(self.bit + 1),
                    ]
                    with m.If(self.bit == (self.bits-1)):
                        m.next = "STOP"

            with m.State("STOP"):
                with m.If(self.en):
                    m.d.sync += [
                        self.o.eq(1), # Stop Bit
                        self.i.ready.eq(1),
                    ]
                    m.next = "IDLE"

        return m

#   FIN
