import requests
from time import sleep
from typing import Callable
from configparser import ConfigParser
import colorlib
import numpy as np
from scipy.optimize import fsolve
import threading

class QueryManager:
    def __init__(self, config: ConfigParser):
        # store these for resource requesting methods
        self.user = config["Philips Hue"]["user"]
        self.key = config["Philips Hue"]['key']
        self.base_request_url = f"https://{config['Philips Hue']['bridge_address']}/clip/v2/resource"

        # get the light_ids for the given group
        self.group_type = config["Philips Hue"]['group_type']
        self.group_id = config["Philips Hue"]['group_id']
        group_objects = self.get_resource(f"/{self.group_type}")
        group_query = [group for group in group_objects if group['id'] == self.group_id]
        if len(group_query) != 1:
            self.__log_error(Exception("Could not find a unique group matching the configured id."))
        group = group_query[0]

        for child in group['children']:
            if child['rtype'] == 'device':
                deviceGet = self.get_resource(f"/device/{child['rid']}")
                lightGet = [device for device in deviceGet[0]["services"] if device['rtype'] == 'light']
                light_id = lightGet[0]['rid']
                child['rid'] = light_id
                child['rtype'] = 'light'
        self.light_ids = [child['rid'] for child in group['children']]


    def get_light_states(self, light_ids=None):
        if light_ids is None:
            light_ids = self.light_ids

        states = {}
        for light_id in light_ids:
            state = self.get_resource(f"/light/{light_id}")

            body = {
                "color": {
                    "xy": state["color"]["xy"]
                },
                "dimming": {
                    "brightness": state["dimming"]["brightness"]
                }
            }
            states[light_id] = body
        return states

    def apply_light_states(self, states: dict):
        for light_id in states.keys():
            state = states[light_id]
            self.put_resource(f"/light/{light_id}", json=state)


    def set_color(self, *light_ids, x: float = 0.31271, y: float = 0.32902,
                  duration_ms = 400, brightness=None, **kwargs):
        if len(light_ids) == 0:
            light_ids = self.light_ids
        json = {
            "color": self._color(x, y),
            "dynamics": {
                "duration": duration_ms
            }
        }
        if brightness is not None:
            json["dimming"] = {"brightness": brightness}
        for light_id in light_ids:
            self.put_resource(f"/light/{light_id}", json=json, **kwargs)


    def rainbow(self, recall_scene_id: str, time_per_cycle = 5, cycles = 5):
        """
        Does a rainbow on each of the lights, then recalls a scene dynamically.
        return_to: the id of a scene to return to.
        """
        request_duration_s = time_per_cycle / 6
        request_duration_ms = int(request_duration_s * 1000)
        gamut = [[0.6915, 0.3038],
                 [0.17, 0.7],
                 [0.1532, 0.0475]]
        hex_gamut = [[0.6915, 0.3038],
                     [0.4308, 0.5019],
                     [0.17, 0.7],
                     [0.1616, 0.3737],
                     [0.1616, 0.1],
                     [0.42235, 0.17565]]
        # self.set_color(x=gamut[0][0],
        #                y=gamut[0][1],
        #                duration_ms=400)
        # sleep(5)


        class Device(threading.Thread):
            def __init__(self, queryman, light_id):
                self.queryman = queryman
                self.light_id = light_id
                threading.Thread.__init__(self)

            def run(self):
                for cycle in range(cycles):
                    for corner in range(6):
                        self.queryman.set_color(self.light_id,
                                       x=hex_gamut[corner][0],
                                       y=hex_gamut[corner][1],
                                       duration_ms=request_duration_ms)
                        sleep(request_duration_s)

        threads = [Device(self, light_id) for light_id in self.light_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        exit()


        for cycle in range(cycles):
            for corner in range(6):
                self.set_color(x=hex_gamut[corner][0],
                               y=hex_gamut[corner][1],
                               duration_ms=request_duration_ms)
                sleep(2*request_duration_s)

        # for cycle in range(cycles):
        #     for corner in range(3):
        #         self.set_color(x=gamut[corner][0],
        #                        y=gamut[corner][1],
        #                        duration_ms=request_duration_ms)
        #
        #         sleep(request_duration_s)

        self.recall_dynamic_scene(recall_scene_id)

    def post_scene(self, sceneName: str, x: list, y: list) -> str:
        """
        Truncates the parameters to meet the following conditions:
            skinName: 1 <= len(skinName) <= 32
            x: 2 <= len(x) <= 9
            y: 2 <= len(y) <= 9
        Returns the scene_id
        """

        # First, iterate through the lights and choose a starting color for each
        sceneName = sceneName[:32]
        base_x = []
        base_y = []
        i_light = 0
        i_color = 0
        while i_light < len(self.light_ids):
            base_x.append(x[i_color])
            base_y.append(y[i_color])
            i_light = i_light + 1
            i_color = (i_color + 1) % len(x)

        body = {
            "metadata": {
                "name": sceneName
            },
            "group": {
                "rid": self.group_id,
                "rtype": self.group_type
            },
            "actions": [
                {
                    "action": {
                        "on": {
                            "on": True
                        },
                        "color": self._color(base_x[i], base_y[i]),
                        # "dimming": {  # TODO do we need "dimming"?
                        #     "brightness": 100
                        # },
                        "dynamics": {  # TODO is this useful?
                            "duration": 400
                        }
                    },
                    "target": {
                        "rid": light_id,
                        "rtype": "light"
                    }
                } for i, light_id in enumerate(self.light_ids)
            ],
            "palette": {
                "color": [
                    {
                        "color": self._color(x[i], y[i]),
                        "dimming": {
                            "brightness": 100  # TODO make this an actual thing by color
                        }
                    } for i in range(len(x))
                ],
                "color_temperature": [],
                "dimming": [
                    {
                        "brightness": 100  # TODO figure out if this needs to be anything
                    }
                ]
            },
            "speed": 0.8,
            "type": "scene"
        }

        res = self.post_resource(path="/scene", json=body)
        rid = res[0]['rid']
        return rid

    def recall_dynamic_scene(self, scene_id: str) -> None:
        body = {
            "recall": {
                "action": "dynamic_palette"
            }
        }
        self.put_resource(f"/scene/{scene_id}", json=body)  # TODO what if you recall a scene that doesn't exist?

    def delete_scene(self, scene_id: str) -> None:
        self.delete_resource(f"/scene/{scene_id}")


    def get_resource(self, path: str):
        return self.__query_resource(path, requests.get)

    def post_resource(self, path: str, json: dict):
        return self.__query_resource(path, requests.post, json=json)

    def put_resource(self, path: str, json: dict, **kwargs):
        return self.__query_resource(path, requests.put, json=json, **kwargs)

    def delete_resource(self, path: str):
        return self.__query_resource(path, requests.delete)

    def __query_resource(self, path: str, request: Callable, json=None, **kwargs):
        """request should be a query function in lib requests"""
        request_url = self.base_request_url + path
        request_header = {"hue-application-key": self.user}
        try:
            res = request(url=request_url,
                          headers=request_header,
                          json=json,
                          verify=False,  # TODO figure out SSL stuff
                          **kwargs)
            if res.status_code >= 300:
                raise ConnectionError
            return res.json()['data']
        except Exception as e:
            self.__log_error(e)
            return None



    def __log_error(self, e: Exception):
        """
        TODO implement actual logging.
        """
        print(e)


    def _color(self, x, y):
        """
        Return a JSON object containing {"xy": {"x": x, "y": y}}
        """
        return {
            "xy": {
                "x": x,
                "y": y
            }
        }

if __name__ == "__main__":
    parser = ConfigParser()
    parser.read("config.ini")
    queryman = QueryManager(parser)


    # For rainbow()
    recall_scene_id = "d77ccf4c-93a5-4765-ad09-eeb61b14e315"
    queryman.rainbow(recall_scene_id=recall_scene_id)
    queryman.recall_dynamic_scene(recall_scene_id)
    exit()


    # For HSV stuff
    recall_scene_id = "d77ccf4c-93a5-4765-ad09-eeb61b14e315"

    hsv_gamut = np.array([[0,120,240, 360],
                          [1,1,1, 1],
                          [1,1,1, 1]])
    points = 12
    points = points - 1  # must end where it starts, yeah?
    hsv_gamut = np.array([np.linspace(0,360,points),
                          np.repeat(1,points),
                          np.repeat(1,points)])
    hsv_gamut = hsv_gamut[:,0:-1]

    # corrections go here
    hsv_gamut = hsv_gamut[:,(0,1,2,3,4,5,6,7,8,9)]
    hsv_gamut[1,(6,7)] = 0.6
    hsv_gamut[0][6] = 200
    print(hsv_gamut)
    rgb_gamut = colorlib.hsv_to_rgb(hsv_gamut)
    xy_gamut = colorlib.rgb_to_xyb(rgb_gamut)
    x = xy_gamut[0]
    y = xy_gamut[1]

    i = 0
    while True:
        print(hsv_gamut[0][i])
        queryman.set_color(x=x[i], y=y[i],
        duration_ms=1000, timeout=0.11)
        sleep(0.2)
        i = (i + 1) % np.shape(hsv_gamut)[1]

    exit()


    queryman.recall_dynamic_scene(recall_scene_id)
    exit()





    # For hex one by one
    hex_gamut = [[0.6915, 0.3038],
                 [0.4308, 0.5019],
                 [0.17, 0.7],
                 [0.1616, 0.3737],
                 [0.1616, 0.1],
                 [0.42235, 0.17565]]


    # C
    queryman.set_color(x=hex_gamut[3][0], y=hex_gamut[3][1],
                       duration_ms=2000)
    sleep(3)
    # B
    queryman.set_color(x=hex_gamut[4][0], y=hex_gamut[4][1],
                       duration_ms=2000)
    sleep(3)
    # M
    queryman.set_color(x=hex_gamut[5][0], y=hex_gamut[5][1],
                       duration_ms=2000)
    sleep(3)
    # R
    queryman.set_color(x=hex_gamut[0][0], y=hex_gamut[0][1],
                       duration_ms=2000)
    exit()



    # use this to debug!
    light_id = queryman.light_ids[0]
    body = queryman.get_resource(f"/scene")
    data = body
    queryman.set_color(0.234, 0.1006)


    exit()  # breakpoint here