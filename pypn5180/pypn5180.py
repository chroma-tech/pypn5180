import time
import struct
import binascii
import asyncio
from . import pypn5180hal


"""
PN5180 main class providing NFC functions to initialise the chip and send/receive NFC frames.
"""


class PN5180(pypn5180hal.PN5180_HIL):

    RF_ON_MODE = {
        "STANDARD": 0x00,
        "IEC_18092_COLLISION_DISABLE": 0x1,  # disable collision avoidance according to ISO/IEC 18092
        "IEC_18092_ACVTIVE_COMMUNICATION": 0x2,  # Use Active Communication mode according to ISO/IEC 18092
    }

    MAX_REGISTER_ADDR = 0x29

    """
    getFirmwareVersion(self)
    response : 2 bytes 
    """

    async def getFirmwareVersion(self):
        firmwareVersion = await self.readEeprom(self.EEPROM_ADDR["FIRMWARE_VERSION"], 2)
        return self._toInt16(firmwareVersion)

    """
    getProductVersion(self)
    response : 2 bytes
    """

    async def getProductVersion(self):
        productVersion = await self.readEeprom(self.EEPROM_ADDR["PRODUCT_VERSION"], 2)
        return self._toInt16(productVersion)

    """
    getEepromVersion(self)
    response : 2 bytes 
    """

    async def getEepromVersion(self):
        eepromVersion = await self.readEeprom(self.EEPROM_ADDR["EEPROM_VERSION"], 2)
        return self._toInt16(eepromVersion)

    """
    getDieIdentifier(self)
    response : 2 bytes 
    """

    async def getDieIdentifier(self):
        dieIdentifier = await self.readEeprom(self.EEPROM_ADDR["DIE_IDENTIFIER"], 16)
        return self._toHex(dieIdentifier)

    """
    selfTest(self)
    Display PN5180 chip versions (HW, SW)
    """

    async def selfTest(self, verbose=False):
        # Get firmware version from EEPROM
        firmwareVersion = await self.getFirmwareVersion()
        productVersion = await self.getProductVersion()
        eepromVersion = await self.getEepromVersion()
        dieIdentifier = await self.getDieIdentifier()
        if verbose:
            print(" Firmware version: %#x" % firmwareVersion)
            print(" Product Version : %#x" % productVersion)
            print(" EEPROM version  : %#x" % eepromVersion)
            print(" Die identifier  : %#r" % dieIdentifier)

    """
    dumpRegisters(self)
    Dumps and display all PN5180 registers
    """

    async def dumpRegisters(self):
        print("======= Register Dump =======")
        for addr in range(0, self.MAX_REGISTER_ADDR):
            registerValue = await self.readRegister(addr)
            print(
                "%s %#x = %#x (%r)"
                % (self.REGISTER_NAME[addr], addr, registerValue, bin(registerValue))
            )
        registerValue = await self.readRegister(0x39)
        print(
            "%s %#x = %#x (%r)"
            % (self.REGISTER_NAME[0x39], 0x39, registerValue, bin(registerValue))
        )
        print("=============================")

    """
    configureIsoIec15693Mode(self)
    Soft reset, configure default parameters for Iso IEC 15693 and enable RF
    """

    async def configureIsoIec15693Mode(self, highspeed=False):
        # TODO :
        #   - do a clean interface selector, not hard coded
        #   - Configure CRC registers
        await self.softwareReset()

        # RF_CFG = {
        # 'TX_ISO_15693_ASK100':0x0D, # 26 kbps
        # 'RX_ISO_15693_26KBPS':0x8D, # 26 kbps
        # 'TX_ISO_15693_ASK10':0x0E,  # 26 kbps
        # 'RX_ISO_15693_53KBPS':0x8E  # 53 kbps
        #  }
        if highspeed:
            await self.loadRfConfig(
                self.RF_CFG["TX_ISO_15693_ASK10"], self.RF_CFG["RX_ISO_15693_53KBPS"]
            )
        else:
            await self.loadRfConfig(
                self.RF_CFG["TX_ISO_15693_ASK100"], self.RF_CFG["RX_ISO_15693_26KBPS"]
            )
        await self.rfOn(self.RF_ON_MODE["STANDARD"])

        # Set SYSTEM regsiter state machine to transceive
        await self.setSystemCommand("COMMAND_IDLE_SET")

    """
    transactionIsoIec15693(cmd)
    Perform RF transaction. Send command to the RFiD device and read device result.
    """

    async def transactionIsoIec15693(self, command):
        await self.clearIrqStatus()
        await self.setSystemCommand("COMMAND_TRANSCEIVE_SET")

        # Check RF_STATUS TRANSCEIVE_STATE value
        # must be WAIT_TRANSMIT
        state = await self.getRfStatusTransceiveState()
        if state != "WAIT_TRANSMIT":
            raise Exception("Error in RF state")

        await self.sendData(8, command)

        # wait for RX to start with a shorter timeout
        deadline = time.ticks_add(time.ticks_ms(), 1)
        irq_status = await self.getIrqStatus()
        while (
            irq_status & self.IRQ_STATUS["RX_SOF_DET_IRQ_STAT"] == 0
        ) and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            irq_status = await self.getIrqStatus()
            await asyncio.sleep(0.001)

        # if RX didn't start, bail early
        if irq_status & self.IRQ_STATUS["RX_SOF_DET_IRQ_STAT"] == 0:
            await self.setSystemCommand("COMMAND_IDLE_SET")
            return 0xFF, []

        # wait for RX to complete
        deadline = time.ticks_add(time.ticks_ms(), 50)
        irq_status = await self.getIrqStatus()
        while (
            irq_status & self.IRQ_STATUS["RX_IRQ_STAT"] == 0
            and time.ticks_diff(deadline, time.ticks_ms()) > 0
        ):
            irq_status = await self.getIrqStatus()
            await asyncio.sleep(0.001)

        nbBytes = await self.getRxStatusNbBytesReceived()
        response = await self.readData(nbBytes)

        if response:
            flags = response[0]
            data = response[1:]
            # print("Received %d bytes from sensor: [flags]: %x, [data]: %r" %(nbBytes, flags, [hex(x) for x in data]))
        else:
            flags = 0xFF
            data = []

        await self.setSystemCommand("COMMAND_IDLE_SET")

        return flags, data

    async def getRfStatusTransceiveState(self):
        regvalue = await self.readRegister(self.REG_ADDR["RF_STATUS"])
        transceiveState = (regvalue >> 24) & 0x3
        return self.RF_STATUS_TRANSCEIVE_STATE[transceiveState]

    async def getRxStatusNbBytesReceived(self):
        regvalue = await self.readRegister(self.REG_ADDR["RX_STATUS"])
        return regvalue & 0x1FF

    async def getIrqStatus(self):
        return await self.readRegister(self.REG_ADDR["IRQ_STATUS"])

    async def clearIrqStatus(self, mask=0xFF):
        await self.writeRegister(self.REG_ADDR["IRQ_CLEAR"], mask)

    async def setSystemCommand(self, mode):
        await self.writeRegisterAndMask(
            self.REG_ADDR["SYSTEM_CONFIG"], self.SYSTEM_CONFIG["COMMAND_CLR"]
        )
        await self.writeRegisterOrMask(
            self.REG_ADDR["SYSTEM_CONFIG"], self.SYSTEM_CONFIG[mode]
        )

    async def softwareReset(self):
        await self.writeRegisterOrMask(
            self.REG_ADDR["SYSTEM_CONFIG"], self.SYSTEM_CONFIG["RESET_SET"]
        )
        await asyncio.sleep(0.05)
        await self.writeRegisterAndMask(
            self.REG_ADDR["SYSTEM_CONFIG"], self.SYSTEM_CONFIG["RESET_CLR"]
        )
        await asyncio.sleep(0.05)
