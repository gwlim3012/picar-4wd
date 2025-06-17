#!/usr/bin/env python3
from .i2c import I2C

class ADC(I2C):
    """Access the SunFounder ADC module via I2C."""

    # Default I2C address of the ADC module. Some boards respond on 0x14
    # while others use 0x15. Probe both during initialisation and pick
    # whichever answers.
    ADDR = 0x14

    def __init__(self, chn):    # adc channel:"A0, A1, A2, A3, A4, A5, A6, A7"
        super().__init__()
        if isinstance(chn, str):
            if chn.startswith("A"):
                chn = int(chn[1:])
            else:
                raise ValueError(
                    "ADC channel should be between [A0, A7], not {}".format(chn)
                )
        if chn < 0 or chn > 7:
            self._error('Incorrect channel range')
        chn = 7 - chn
        self.chn = chn | 0x10
        self.reg = 0x40 + self.chn

        # Detect which address is active.
        for addr in (0x14, 0x15):
            if self.is_ready(f"{addr:02x}"):
                self.ADDR = addr
                break

    def read(self):
        self.send([self.chn, 0, 0], self.ADDR)
        value_h = self.recv(1, self.ADDR)[0]
        value_l = self.recv(1, self.ADDR)[0]
        value = (value_h << 8) + value_l
        return value


def test():
    import time
    adc = ADC(0)
    while True:
        print(adc.read())
        time.sleep(1)

if __name__ == '__main__':
    test()
