#!/usr/bin/env python3

import time
from ev3link import EV3Link, set_other_uart_mode, DIR_FWD, DIR_REV, DIR_STOP,motor1,motor2,servo1,servo2,servo3

# 1) Put sensor port 1 into raw UART mode (one time, per boot/reconnect)
set_other_uart_mode("in1")

# 2) Open the Oneky.
#    IMPORTANT: verify the tty path for your ev3dev image with:
#       ls -la /dev/tty*        (before setting other-uart mode)
#       ls -la /dev/tty*        (after setting other-uart mode)
#    and use whichever new device node appeared. Common values seen:
#    /dev/tty_in1 (newer images) or /dev/ttyS1 (older images, in1 -> ttyS1).
with EV3Link(tty="/dev/tty_in1") as Oneky:
    #Main program start here

    fw = Oneky.ping()
    print("STM32 firmware version:", fw)

    ok, uptime_ms = Oneky.get_status()
    print("status ok=%s uptime=%dms" % (ok, uptime_ms))

    # --- Drive motors (dual-PWM, works with plain DC or encoder motors) ---
    print("motor0 forward, motor1 reverse")
    Oneky.set_motor(motor1, DIR_FWD, 200)
    Oneky.set_motor(motor2, DIR_REV, 200)
    time.sleep(1.0)
    Oneky.set_motor(motor1, DIR_STOP, 0)
    Oneky.set_motor(motor2, DIR_STOP, 0)

    # --- Encoders (only meaningful if that motor actually has one wired) ---
    Oneky.reset_encoder(0)
    Oneky.reset_encoder(1)
    Oneky.set_motor(motor1, DIR_FWD, 150)
    time.sleep(0.5)
    Oneky.set_motor(motor1, DIR_STOP, 0)
    print("motor1 encoder count after 0.5s spin:", Oneky.read_encoder(0))
    print("motor2 encoder count (no encoder wired -> stays 0):", Oneky.read_encoder(1))

    # --- Servos (6 available) ---
    for servo_id in range(6):
        Oneky.set_servo(servo_id, 90)
    time.sleep(0.3)
    Oneky.set_servo(servo1, 0)
    Oneky.set_servo(servo2, 180)
    Oneky.set_servo(servo3, 90)

    # --- Analog sensors (0-3) ---
    values = Oneky.read_analog_all()
    print("analog sensors (raw 0-4095):", values)

    # --- I2C example: read 6 bytes from a device at address 0x1D on I2C1 ---
    try:
        data = Oneky.i2c_read(channel=0, addr=0x1D, length=6)
        print("i2c1 @0x1D ->", list(data))
    except Exception as e:
        print("i2c read failed (check wiring/address):", e)

    # Oneky.close() runs automatically here (stops motors) via `with`
