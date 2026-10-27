"""Planted for AC-13: business code reading the system clock."""

import time
from datetime import date, datetime


def due_on():
    return date.today()


def stamped():
    return datetime.now(), datetime.utcnow(), time.time()
