"""Explicit, bounded domains; regional products never overwrite China's catalog."""
import re
import math
from .models import WeatherMapDomain


def region_domain(name, bounds, china):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', name):
        raise ValueError('Region names must contain lowercase letters, digits or hyphens')
    if name == 'china':
        if bounds is not None:
            raise ValueError('Use a different region name for custom bounds')
        return china
    if name == 'world':
        if bounds is not None:
            raise ValueError('The world domain is fixed; use a custom region name')
        bounds = [-180,-80,180,80]
    if bounds is None or len(bounds) != 4:
        raise ValueError('Custom regions require WEST SOUTH EAST NORTH bounds')
    west,south,east,north=bounds
    if not all(math.isfinite(x) for x in bounds) or not (-180<=west<180 and 5<=east-west<=360 and -80<=south<north<=80 and north-south>=5):
        raise ValueError('Invalid domain: longitude width 5–360°, latitude -80–80° and height >=5°')
    return WeatherMapDomain(west=west,east=east,south=south,north=north,
        resolution_degrees=1 if name=='world' else .25,projection='plate-carree')
