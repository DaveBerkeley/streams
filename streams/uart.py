
from amaranth import *

from streams import Stream

#
#   Simple Clock generator : finds nearest dividor of the sys_ck

class ClockGen(Elaboratable):

    def __init__(self, sys_ck, freq, mul=1):
        self.o = Signal()
        sfreq = freq * mul
        self.idiv = int(sys_ck / sfreq)
        self.div = Signal(range(self.idiv+1))
        print("sample req", freq, "ck", sys_ck, 
              "idiv", self.idiv, 
              "mul", mul, 
              "sample", sys_ck / (self.idiv * mul))

    def elaborate(self, _):
        m = Module()
        m.d.sync += self.div.eq(self.div + 1)
        with m.If(self.div == (self.idiv-1)):
            m.d.sync += self.div.eq(0)

        m.d.sync += self.o.eq(self.div == 0)

        return m

#
#   Simple Tx Stream to UART

class UART_Tx(Elaboratable):

    def __init__(self, bits=8, name="UART_Tx"):
        self.name = name
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
