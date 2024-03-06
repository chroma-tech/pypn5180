from . import pypn5180, iso_iec_15693


def init(spi, cs, busy):
    device = pypn5180.PN5180(spi=spi, cs=cs, busy=busy)
    reader = iso_iec_15693.iso_iec_15693(device)
    return reader
