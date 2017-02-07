from __future__ import absolute_import, division, print_function

import time
import json
from collections import defaultdict
import numpy as np
from lcm import LCM
from robotlocomotion import viewer2_comms_t
from director.thirdparty import transformations


def to_lcm(data):
    msg = viewer2_comms_t()
    msg.utime = data["utime"]
    msg.format = "treeviewer_json"
    msg.format_version_major = 1
    msg.format_version_minor = 0
    msg.data = json.dumps(data)
    msg.num_bytes = len(msg.data)
    return msg


def serialize_transform(tform):
    return {
        "translation": list(transformations.translation_from_matrix(tform)),
        "quaternion": list(transformations.quaternion_from_matrix(tform))
    }


class GeometryData:
    __slots__ = ["geometry", "color", "transform"]
    def __init__(self, geometry, color=[1, 0, 0, 0.5], transform=np.eye(4)):
        self.geometry = geometry
        self.color = color
        self.transform = transform

    def serialize(self):
        params = self.geometry.serialize()
        params["color"] = self.color
        params["transform"] = serialize_transform(self.transform)
        return params


class BaseGeometry:
    def serialize(self):
        raise NotImplementedError()


class Box(BaseGeometry):
    __slots__ = ["lengths"]
    def __init__(self, lengths):
        assert len(lengths) == 3
        self.lengths = lengths

    def serialize(self):
        return {
            "type": "box",
            "lengths": self.lengths
        }


class VisData:
    __slots__ = ["geometries", "transform"]
    def __init__(self, geometries=[], transform=np.eye(4)):
        self.geometries = geometries
        self.transform = transform


class LazyTree:
    __slots__ = ["data", "children"]
    def __init__(self, data=None):
        if data is None:
            data = VisData()
        self.children = defaultdict(lambda: LazyTree())

    def __getitem__(self, item):
        return self.children[item]

    def getdescendant(self, path):
        t = self
        for p in path:
            t = t[p]
        return t


class CommandQueue:
    def __init__(self):
        self.draw = set()
        self.load = set()
        self.delete = set()

    def isempty(self):
        return not (self.draw or self.load or self.delete)


class CoreVisualizer:
    def __init__(self, lcm=LCM()):
        self.lcm = lcm
        self.tree = LazyTree()
        self.queue = CommandQueue()
        self.publish_immediately = True
        self.lcm.subscribe("DIRECTOR_TREE_VIEWER_RESPONSE", self.handle_response)

    def handle_response(self, channel, msgdata):
        msg = viewer2_comms_t.decode(msgdata)
        print(msg)

    def load(self, path, geomdata):
        if isinstance(geomdata, GeometryData):
            self._load(path, geomdata)
        else:
            self._load(path, GeometryData(geomdata))

    def _load(self, path, geomdata=None):
        if geomdata is not None:
            self.tree.getdescendant(path).geometries = [geomdata]
        self.queue.load.add(path)
        self._maybe_publish()

    def draw(self, path, tform):
        self.tree.getdescendant(path).transform = tform
        self.queue.draw.add(path)
        self._maybe_publish()

    def delete(self, path):
        if not path:
            self.tree = LazyTree()
        else:
            t = self.tree.getdescendant(path[:-1])
            del t[path[-1]]
        self.queue.delete.add(path)
        self._maybe_publish()

    def _maybe_publish(self):
        if self.publish_immediately:
            self.publish()

    def publish(self):
        if not self.queue.isempty():
            data = self.serialize_queue()
            msg = to_lcm(data)
            self.lcm.publish("DIRECTOR_TREE_VIEWER_REQUEST", msg.encode())

    def serialize_queue(self):
        delete = []
        load = []
        draw = []
        for path in self.queue.delete:
            delete.append({"path": path})
        for path in self.queue.load:
            geoms = self.tree.getdescendant(path).geometries
            if geoms:
                if len(geoms) > 1:
                    raise NotImplementedError("I haven't implemented the ability to have multiple geometries share a path yet. Please give each geometry a unique path")
                load.append({
                    "path": path,
                    "geometry": geoms[0].serialize()
                })
        for path in self.queue.draw:
            draw.append({
                "path": path,
                "transform": serialize_transform(self.tree.getdescendant(path).transform)
            })
        return {
            "utime": int(time.time() * 1e6),
            "delete": delete,
            "load": load,
            "draw": draw
        }


if __name__ == '__main__':
    vis = CoreVisualizer()
    box = Box([1, 1, 1])
    geom = GeometryData(box, [0, 1, 0, 0.5])
    vis.load(("foo", "bar"), geom)

    for i in range(10):
        for theta in np.linspace(0, 2 * np.pi, 100):
            vis.draw(("foo", "bar"), transformations.rotation_matrix(theta, [0, 0, 1]))
            time.sleep(0.01)
