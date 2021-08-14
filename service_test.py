#!/usr/bin/env python3

import subprocess
import time

from gpiozero import LED

red = LED(20)

services = [
    'autossh-tunnel',
    'grafana-server',
    'tempserver',
    'hue-emulator',
]


def is_down(service):
    result = subprocess.run(['systemctl', 'status', service], capture_output=True)
    return bool(result.returncode)


while True:
    if any(is_down(service) for service in services):
        red.on()
    else:
        red.off()

    time.sleep(600)
