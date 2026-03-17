from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Location:
    name: str
    type: str
    pose: tuple[float, float, float] | None = None


class WorldModel:
    def __init__(self) -> None:
        self._locations: dict[str, Location] = {}

    def add_location(self, name: str, location_type: str, pose: tuple[float, float, float] | None = None) -> None:
        self._locations[name] = Location(name=name, type=location_type, pose=pose)

    def get_location(self, name: str) -> Location | None:
        return self._locations.get(name)

    def is_valid_location(self, name: str) -> bool:
        return name in self._locations

    def find_nearest(self, location_type: str) -> Location | None:
        for location in self._locations.values():
            if location.type == location_type:
                return location
        return None
