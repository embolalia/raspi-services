#!/usr/bin/env python3

from collections import namedtuple
import json
import logging
import time

import cherrypy
from prometheus_client import CollectorRegistry, Gauge, generate_latest
import requests

import adafruit_dht
import adafruit_scd30
import adafruit_ms8607
import board
import busio

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

i2c = busio.I2C(board.SCL, board.SDA)
time.sleep(2)

quality = adafruit_scd30.SCD30(i2c)
barometer = adafruit_ms8607.MS8607(i2c)
#fridge = adafruit_dht.DHT22(board.D21)


class TempResult:
    def __init__(self, temp_c, humidity, co2=None, pressure_hpa=None):
        self.temp_c = temp_c
        self.humidity = humidity
        self.co2 = round(co2) if co2 else None
        self.pressure_hpa = pressure_hpa

    @property
    def temp_f(self):
        return self.temp_c * (9/5) + 32

    @property
    def pressure_inhg(self):
        return self.pressure_hpa / 33.6585

    def __repr__(self):
        return f'TempResult({self.temp_c}, {self.humidity}, {self.co2}, {self.pressure_hpa})'

    def __str__(self):
        result = f'{self.temp_f:.0f}℉, {self.humidity:.0f}% humidity'
        if self.co2:
            result += f', {self.co2}ppm CO2'
        if self.pressure_hpa:
            result += f', {self.pressure_hpa}hPa ({self.pressure_inhg} inHg)'
        return result


def retryable(function):
    def wrapped(retry=True):
        try:
            result = function()
        except RuntimeError:
            logger.exception('Failed sensor read')
            result = None
        if retry and not result:
            logger.info('Retrying')
            result = wrapped(False)
        return result
    return wrapped


@retryable
def get_quality_data():
    for _ in range(5):
        if not quality.data_available:
            time.sleep(1)
    return TempResult(quality.temperature, quality.relative_humidity, quality.eCO2)


@retryable
def get_barometer_data():
    return TempResult(barometer.temperature, barometer.relative_humidity, pressure_hpa=barometer.pressure)


@retryable
def get_fridge_data():
    time.sleep(1)
    return TempResult(fridge.temperature, fridge.humidity)


@retryable
def get_bedroom_data():
    try:
        response = requests.get('http://smolpi.local:8080')
    except requests.exceptions.ConnectionError:
        return TempResult(0, 0)
    data = response.json()
    return TempResult(data['temp_c'], data['humidity'])


def get_all_data():
    return {
        'quality': get_quality_data(),
        'bedroom': get_bedroom_data(),
        'barometer': get_barometer_data(),
    }


class TempServ:
    @cherrypy.expose
    def index():
        data = get_all_data()

        if 'curl' in cherrypy.request.headers.get('User-Agent', 'curl'):
            return ''.join('{sensor}: {result}\n' for sensor, result in data.items())
        else:
            barometer_data = data['barometer']
            bedroom_data = data['bedroom']
            pressure = round(barometer_data.pressure_inhg, 2)
            if pressure > 30.2:
                pressure_note = 'high'
            elif pressure < 29.8:
                pressure_note = 'low'
            else:
                pressure_note = 'normal'
            return f"""
    <html>
    <head><title>Home Climate</title></head>
    <body>
    <h1>
        {barometer_data.temp_f:.0f}℉
    </h1>
    <h2>
        {barometer_data.humidity:.0f}%
    </h2>
    Bedroom: {bedroom_data.temp_f:.0f}℉, {bedroom_data.humidity:.0f}%
    <br>
    Pressure is <strong>{pressure_note}</strong> ({pressure} inHg)
    </body></html>
    """

    @cherrypy.expose
    def metrics():
        registry = CollectorRegistry()
        c_temp_gauge = Gauge(
            'temperature_c',
            'Temperature in Celsius',
            ['location'],
            registry=registry,
        )

        f_temp_gauge = Gauge(
            'temperature_f',
            'Temperature in Fahrenheit',
            ['location'],
            registry=registry,
        )

        humidity_gauge = Gauge(
            'humidity_pct',
            'Relative humidity',
            ['location'],
            registry=registry,
        )

        co2_gauge = Gauge(
            'co2_ppm',
            'Carbon dioxide concentration',
            ['location'],
            registry=registry,
        )
        pressure_gauge = Gauge(
            'pressure_hpa',
            'Atmospheric pressure',
            ['location'],
            registry=registry,
        )

        for location, data in get_all_data().items():
            if not data:
                continue
            f_temp_gauge.labels(location=location).set(data.temp_f)
            c_temp_gauge.labels(location=location).set(data.temp_c)
            humidity_gauge.labels(location=location).set(data.humidity)
            if data.co2:
                co2_gauge.labels(location=location).set(data.co2)
            if data.pressure_hpa:
                pressure_gauge.labels(location=location).set(data.pressure_hpa)


        cherrypy.response.headers['Content-Type'] = 'text/plain; version=0.0.4'
        return generate_latest(registry)


if __name__ == '__main__':
    cherrypy.config.update({
        'server.socket_host': '0.0.0.0',
        'server.socket_port': 8000,
    })
    cherrypy.quickstart(TempServ)
