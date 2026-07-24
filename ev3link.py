import struct
import time

import serial

STX = 0xAA

CMD_PING = 0x10
CMD_SET_MOTOR = 0x11
CMD_SET_SERVO = 0x12
CMD_READ_ANALOG = 0x13
CMD_READ_ANALOG_ALL = 0x14
CMD_I2C_WRITE = 0x15
CMD_I2C_READ = 0x16
CMD_STOP_ALL = 0x17
CMD_GET_STATUS = 0x18
CMD_READ_ENCODER = 0x19
CMD_RESET_ENCODER = 0x1A

ACK_BIT = 0x80
CMD_ONEKY = 0xFF

DIR_STOP = 0
DIR_FWD = 1
DIR_REV = 2

P1 = 0
P2 = 1
P3 = 2
P4 = 3

servo1 = 0
servo2 = 1
servo3 = 2
servo4 = 3
servo5 = 4
servo6 = 5

motor1 = 0
motor2 = 1

_ERROR_NAMES = {
    0x01: "BAD_CHECKSUM",
    0x02: "BAD_LEN",
    0x03: "UNKNOWN_CMD",
    0x04: "I2C_FAIL",
    0x05: "BAD_PARAM",
}


class EV3LinkError(Exception):
    pass


def set_other_uart_mode(port_name="in1"):
    """
    Switch an EV3 input port to raw UART passthrough mode via ev3dev's
    lego-port sysfs class. Run this once before opening the tty.

    port_name: 'in1'..'in4' (maps to /sys/class/lego-port/port0..port3)

    NOTE: after calling this, check `ls -la /dev/tty*` (compare before/after)
    to confirm the actual device node name for your ev3dev image/kernel -
    it has been observed as /dev/tty_in<N> on newer images and /dev/ttyS<N>
    on some older ones. Update the `tty=` argument of EV3Link accordingly.
    """
    port_index = {"in1": 0, "in2": 1, "in3": 2, "in4": 3}[port_name]
    path = "/sys/class/lego-port/port%d/mode" % port_index
    with open(path, "w") as f:
        f.write("other-uart")
    time.sleep(0.5)  # let the port + tty node settle


class EV3Link:
    def __init__(self, tty="/dev/tty_in1", baud=115200, timeout=0.3):
        self._ser = serial.Serial(tty, baudrate=baud, timeout=timeout)
        # STM32 boots and re-inits USART; give it a moment before first frame
        time.sleep(0.2)
        self._ser.reset_input_buffer()

    # ---------------- low-level framing ----------------
    @staticmethod
    def _checksum(cmd, payload):
        s = (cmd + len(payload) + sum(payload)) & 0xFF
        return (256 - s) & 0xFF

    def _send(self, cmd, payload=b""):
        frame = bytes([STX, cmd, len(payload)]) + bytes(payload)
        frame += bytes([self._checksum(cmd, payload)])
        self._ser.write(frame)

    def _recv(self):
        b = self._ser.read(1)
        if len(b) != 1 or b[0] != STX:
            raise EV3LinkError("timeout waiting for STX")
        hdr = self._ser.read(2)
        if len(hdr) != 2:
            raise EV3LinkError("timeout reading header")
        cmd, length = hdr[0], hdr[1]
        payload = self._ser.read(length)
        if len(payload) != length:
            raise EV3LinkError("timeout reading payload")
        cks = self._ser.read(1)
        if len(cks) != 1:
            raise EV3LinkError("timeout reading checksum")
        if self._checksum(cmd, payload) != cks[0]:
            raise EV3LinkError("bad checksum in response")
        if cmd == CMD_ONEKY:
            err = payload[0] if payload else 0
            raise EV3LinkError("STM32 Oneky: %s (0x%02X)" % (_ERROR_NAMES.get(err, "?"), err))
        return cmd, payload

    def _transact(self, cmd, payload=b"", retries=2):
        last_err = None
        for _ in range(retries + 1):
            try:
                self._ser.reset_input_buffer()
                self._send(cmd, payload)
                rcmd, rpayload = self._recv()
                if rcmd != (cmd | ACK_BIT):
                    raise EV3LinkError("unexpected response cmd 0x%02X" % rcmd)
                return rpayload
            except EV3LinkError as e:
                last_err = e
                time.sleep(0.01)
        raise last_err

    # ---------------- high-level API ----------------
    def ping(self):
        payload = self._transact(CMD_PING)
        return payload[0]  # firmware version

    def set_motor(self, motor_id, direction, speed):
        """motor_id: 0 or 1, direction: DIR_STOP/DIR_FWD/DIR_REV, speed: 0-255"""
        speed = max(0, min(255, int(speed)))
        self._transact(CMD_SET_MOTOR, bytes([motor_id, direction, speed]))

    def set_servo(self, servo_id, angle):
        """servo_id: 0-5 (6 servos), angle: 0-180 degrees"""
        angle = max(0, min(180, int(angle)))
        self._transact(CMD_SET_SERVO, bytes([servo_id, angle]))

    def read_analog(self, sensor_id):
        """sensor_id: 0-3, returns raw 12-bit ADC value (0-4095)"""
        payload = self._transact(CMD_READ_ANALOG, bytes([sensor_id]))
        return (payload[0] << 8) | payload[1]

    def read_analog_all(self):
        """returns a tuple of 4 raw 12-bit ADC values"""
        payload = self._transact(CMD_READ_ANALOG_ALL)
        return struct.unpack(">4H", payload)

    def i2c_write(self, channel, addr, data):
        """channel: 0 (I2C1) or 1 (I2C2), addr: 7-bit I2C address, data: bytes/list"""
        data = bytes(data)
        payload = bytes([channel, addr, len(data)]) + data
        self._transact(CMD_I2C_WRITE, payload)

    def i2c_read(self, channel, addr, length):
        """returns `length` bytes read from the given I2C device"""
        payload = self._transact(CMD_I2C_READ, bytes([channel, addr, length]))
        return payload

    def read_encoder(self, motor_id):
        """motor_id: 0 or 1. Returns the signed cumulative encoder count
        for that motor (0 if no encoder is physically wired to it)."""
        payload = self._transact(CMD_READ_ENCODER, bytes([motor_id]))
        (value,) = struct.unpack(">i", payload)  # signed 32-bit, big-endian
        return value

    def reset_encoder(self, motor_id):
        """motor_id: 0 or 1"""
        self._transact(CMD_RESET_ENCODER, bytes([motor_id]))

    def stop_all(self):
        self._transact(CMD_STOP_ALL)

    def get_status(self):
        payload = self._transact(CMD_GET_STATUS)
        ok = payload[0]
        uptime_ms = struct.unpack(">I", payload[1:5])[0]
        return ok, uptime_ms

    def close(self):
        try:
            self.stop_all()
        except EV3LinkError:
            pass
        self._ser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
