"""Sensores virtuales con ruido, deriva y averías inyectables."""

from sensormon.simulator.runner import Simulator, parse_fault_token
from sensormon.simulator.sensors import VirtualSensor

__all__ = ["Simulator", "VirtualSensor", "parse_fault_token"]
