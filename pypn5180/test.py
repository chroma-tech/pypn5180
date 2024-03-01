import time
from machine import Pin, SPI
import fern
from . import nfc

print("Opening reader")
spi = SPI(1, baudrate=7000000, sck=fern.NFC_SCK, mosi=fern.NFC_MOSI, miso=fern.NFC_MISO)
reader = nfc.NfcReader(spi, fern.NFC_NSS, fern.NFC_BUSY, fern.NFC_RST)

print("Starting main loop")
while True:
    reader.tick()
    time.sleep(0.1)
