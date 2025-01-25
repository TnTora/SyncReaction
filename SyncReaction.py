import asyncio
import os
import json
import websockets
import signal
import argparse
import time
from datetime import timedelta, datetime
from python_mpv_jsonipc import MPV
import ssl
from urllib.parse import urlparse, parse_qs

# Uncomment the following 4 lines to monitor websocket connection

# import logging

# logger = logging.getLogger("websockets")
# logger.setLevel(logging.DEBUG)
# logger.addHandler(logging.StreamHandler())

parser = argparse.ArgumentParser()
parser.add_argument("-c", "--cache", action="store_true", default=False)
parser.add_argument("-s", "--subprocess", action="store_true", default=False)
parser.add_argument("-d", "--scriptDirectory", default=None)
parser.add_argument("--socket", default=None)
parser.add_argument("--ssl", action="store_true", default=False)

args = parser.parse_args()
useCached = args.cache
subprocess = args.subprocess
directory = args.scriptDirectory
SOCKET = args.socket
use_ssl = args.ssl


def get_id(url):
    # Get video ID from youtube URL
    parsed_url = urlparse(url)
    v_query = parse_qs(parsed_url.query).get('v')
    if v_query:
        return v_query[0]
    path_list = parsed_url.path.split('/')
    if path_list:
        return path_list[-1]


# Get directory of current file directory if not provided as argument
if directory is None:
    directory = os.path.dirname(__file__)

if use_ssl:
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    ssl_cert = os.path.join(directory, "fullchain.pem")
    ssl_key = os.path.join(directory, "cert-key.pem")

    ssl_context.load_cert_chain(ssl_cert, keyfile=ssl_key)
else:
    ssl_context = None


with open(os.path.join(directory, "cache.json")) as f:
    cache = json.load(f)

with open(os.path.join(directory, "options.json")) as f:
    options = json.load(f)

PORT = options["PORT"]  # PORT used for websocket server
pauseToSync = options["pauseToSync"]
cache_size = options["cache_size"]

loop = None

if subprocess:
    # If the script is being run as a subprocess, sync info will be
    # displayed on the player OSD

    async def osd_output(text, duration):
        global current_osd
        current_osd = text
        mpv.osd_overlay(5, "ass-events", "{\\pos(25, 25)}"+text)
        if duration > -1:
            await asyncio.sleep(duration)
            if current_osd == text:
                mpv.osd_overlay(5, "ass-events", "")

    def show_info(text, duration=-1, method="osd"):
        if method == "osd":
            asyncio.create_task(osd_output(text, duration))
        else:
            mpv.show_text(text, duration)

else:

    def show_info(text, duration=-1):
        print(text, flush=True)


if useCached:

    async def findDelay(client):
        if mpv.filename + client.id in cache.keys():
            client.delay = cache[mpv.filename + client.id][0]
        else:
            show_info("delay not found in cache")
            await asyncio.sleep(1)
            stopScript()

else:

    async def findDelay(client):
        client.delay = await client.getProperty("playback-time") - mpv.playback_time
        print(f"client_id:{client.id}, delay:{client.delay}", flush=True)
        updateCache(mpv.filename + client.id, client.delay)
        show_info(f"delay: {timedelta(seconds=client.delay)}", 2)


# If full, delete the oldest entry before updating cache file
def updateCache(current, delay):
    if len(cache) > cache_size:
        # delete oldest entry
        cache.pop(next(iter(cache)))
    cache[current] = [delay, datetime.now().strftime("%Y-%m-%d %H:%M")]
    with open(os.path.join(directory, "cache.json"), "w") as f:
        json.dump(cache, f, indent=4)


clients = {}


async def handler(websocket):
    global mpvPause, player_focus
    # Code executed the first time a client connect to the server
    if websocket not in clients.values():
        clients[websocket.id] = PlayerClient(websocket)

        if len(clients) == 1:
            clients[websocket.id].main_player = True
            player_focus = websocket.id
            mpvPause = mpv.bind_property_observer("core-idle", syncPause)
            mpv.bind_property_observer("speed", syncSpeed)
            mpv.bind_property_observer("eof-reached", handle_eof)

        clients[websocket.id].id = await clients[websocket.id].getProperty("url")
        clients[websocket.id].id = get_id(clients[websocket.id].id)
        print("current: ", mpv.filename + clients[websocket.id].id, flush=True)
        show_info("Connected", 1)

        await findDelay(clients[websocket.id])
        if clients[websocket.id].main_player:
            mpv.bind_property_observer("seeking", syncSeeking)
        mpv.playback_time += 0.001
        await clients[websocket.id].setProperty("speed", 1)

    # Handling incoming messages from client
    async for message in websocket:
        msg = json.loads(message)
        if msg["type"] == "set":
            if msg["property"] == "pause" and clients[websocket.id].delay is not None:
                if msg["value"] == 1:
                    mpv.pause = False
                    clients[websocket.id].buffering_resume_attempts = 0
                elif msg["value"] == 3 and clients[websocket.id].buffering_resume_attempts < 5:
                    clients[websocket.id].setProperty_sync("pause", False)
                    clients[websocket.id].buffering_resume_attempts += 1
                else:
                    mpv.pause = True
                    clients[websocket.id].buffering_resume_attempts = 0
                clients[websocket.id].state = msg["value"]
            elif msg["property"] == "speed":
                mpv.speed = float(msg["value"])
                # clients[websocket.id].speed = float(msg["value"])
        elif msg["type"] == "playbackSync":
            client_sent_time = msg["time"]
            time_adjustment = time.time() - client_sent_time
            clients[websocket.id].playback_time = float(msg["value"]) + time_adjustment
            if clients[websocket.id].main_player:
                await checkSyncMain(clients[websocket.id])
            else:
                await checkSync(clients[websocket.id])
        elif msg["type"] == "notice":
            if msg["value"] == "clientStop":
                if len(clients) > 1:
                    if clients[websocket.id].main_player:
                        clients.pop(websocket.id)
                        clients[next(iter(clients))].main_player = True
                    else:
                        clients.pop(websocket.id)
                    continue
                stopScript(notifyClient=False)
            elif msg["value"] == "focus":
                if player_focus == websocket.id:
                    continue
                player_focus = websocket.id
                show_info(f"focus: {clients[player_focus].id}", 1)


async def monitorMPV(queue):
    while True:
        try:
            msg = await queue.get()
            if "client" in msg[1].keys():
                client = clients[msg[1]["client"]]
                msg[1].pop("client")
                await client.socket.send(json.dumps(msg[1]))
                continue
            for socket_id, client in clients.items():
                await client.socket.send(json.dumps(msg[1]))
        except asyncio.CancelledError:
            raise


class PlayerClient:
    def __init__(self, websocket):
        self.socket = websocket
        self.id = None
        self.delay = None
        self.state = None
        self.playback_time = None
        self.speed = 1
        self.main_player = False
        self.sleeping = False
        self.accuracy = 0.15  # (0.06-0.19) deviation from sync before the script starts small correction
        self.original_accuracy = self.accuracy
        self.buffering_resume_attempts = 0

    async def setProperty(self, name, value):
        msg = {"type": "set", "property": name, "value": value}
        await self.socket.send(json.dumps(msg))

    async def getProperty(self, name):
        msg = {"type": "get", "property": name, "value": None}
        await self.socket.send(json.dumps(msg))
        while True:
            answer = await self.socket.recv()
            loadedAnswer = json.loads(answer)
            if loadedAnswer["type"] == "get-property":
                break
        return loadedAnswer["value"]

    def setProperty_sync(self, name, value, priority=None):
        global queue_priority
        if priority is None:
            priority = queue_priority
        msg = (priority, {"type": "set", "property": name, "value": value, "client": self.socket.id})
        queue_priority += 1
        loop.call_soon_threadsafe(mpvQ.put_nowait, msg)
        # print(mpvQ, flush=True)


async def checkSyncMain(client):
    global mpvPause

    if client.sleeping:
        return

    diff = client.playback_time - mpv.playback_time - client.delay

    if pauseToSync and -3 < diff < -client.accuracy:
        show_info("Syncing...", round(abs(diff)) * 1000)
        if mpvPause in mpv.property_bindings.keys():
            mpv.unbind_property_observer(mpvPause)
        client.sleeping = True
        mpv.pause = True
        await asyncio.sleep(abs(diff))
        mpv.pause = False
        if mpv.property_bindings:
            mpvPause = mpv.bind_property_observer("pause", syncPause)
        client.sleeping = False
        client.accuracy = 0.05
    elif abs(diff) > 2:
        mpv.pause = True
        show_info(f"diff: {round(diff, 6)} seeking")
        await client.setProperty("playback-time", mpv.playback_time + client.delay)
    elif abs(diff) > 0.2:
        speed_modifier = (diff / abs(diff)) * 0.05
        mpv.speed = client.speed + speed_modifier
        show_info(f"diff: {round(diff, 6)};   speed: {mpv.speed}")
        client.accuracy = 0.05
    elif abs(diff) > client.accuracy:
        speed_modifier = (diff / abs(diff)) * 0.01
        mpv.speed = client.speed + speed_modifier
        show_info(f"diff: {round(diff, 6)};   speed: {mpv.speed}")
        client.accuracy = 0.05
    elif client.accuracy != client.original_accuracy:
        mpv.speed = client.speed
        show_info(f"Synced within ~{client.accuracy} sec;  speed: {mpv.speed}", 2)
        client.accuracy = client.original_accuracy
    else:
        await client.setProperty("removeListener", "playback-time")


async def checkSync(client):

    diff = mpv.playback_time + client.delay - client.playback_time

    if abs(diff) > 2:
        mpv.pause = True
        show_info(f"sub_player diff: {round(diff, 6)} seeking")
        await client.setProperty("playback-time", mpv.playback_time + client.delay)
    elif abs(diff) > 0.2:
        speed_modifier = (diff / abs(diff)) * 0.05
        await client.setProperty("speedOffset", speed_modifier)
        show_info(f"sub_player diff: {round(diff, 6)};   speed: {mpv.speed+speed_modifier}")
        client.accuracy = 0.05
    elif abs(diff) > client.accuracy:
        speed_modifier = (diff / abs(diff)) * 0.01
        await client.setProperty("speedOffset", speed_modifier)
        show_info(f"sub_player diff: {round(diff, 6)};   speed: {mpv.speed+speed_modifier}")
        client.accuracy = 0.05
    elif client.accuracy != client.original_accuracy:
        await client.setProperty("speed", client.speed)
        show_info(f"Synced sub_player within ~{client.accuracy} sec;  speed: {client.speed}", 2)
        client.accuracy = client.original_accuracy
    else:
        await client.setProperty("removeListener", "playback-time")


if os.name == "nt":
    pipe = "\\\\.\\pipe\\"
    if SOCKET is None:
        SOCKET = "tmp\\mpvsocket"
else:
    pipe = ""
    if SOCKET is None:
        SOCKET = "/tmp/mpvsocket"

while True:
    try:
        mpv = MPV(start_mpv=False, ipc_socket=SOCKET)
        break
    except Exception:
        input(
            f"Open video with mpv (or mpv based player) using the option --input-ipc-server={pipe+SOCKET}, then press ENTER"
        )

mpv.speed = 1
mpv.keep_open = "always"  # Leave the player on the last frame rather then closing or moving to the next file
mpv.video_sync = "audio"

current_osd = ""

current_speed = 1
queue_priority = 0
player_focus = None
eof = False

mpvQ = asyncio.PriorityQueue()


def changeDelay(offSet, client):
    client.delay += offSet
    client_id = f" {client.id}" if len(clients) > 1 else ""
    show_info(f"delay{client_id}: {str(timedelta(seconds=client.delay))}", 1000, "show-text")
    client.setProperty_sync("addListener", "playback-time")


@mpv.on_key_press("ALT+m")
def addDelay():
    changeDelay(0.05, clients[player_focus])


@mpv.on_key_press("ALT+n")
def lessDelay():
    changeDelay(-0.05, clients[player_focus])


@mpv.on_key_press("ALT+Shift+m")
def addDelayAll():
    for key in clients:
        changeDelay(0.05, clients[key])


@mpv.on_key_press("ALT+Shift+n")
def lessDelayAll():
    for key in clients:
        changeDelay(-0.05, clients[key])


@mpv.on_key_press("ALT+CTRL+x")
def manualSyncCheck():
    for key in clients:
        clients[key].setProperty_sync("addListener", "playback-time")


@mpv.on_key_press("ESC")
def stopScript(notifyClient=True):
    if notifyClient:
        msg = {"type": "notice", "property": None, "value": "stopping server"}
        try:
            loop.call_soon_threadsafe(mpvQ.put_nowait, (0, msg))
        except Exception:
            pass
    with open(os.path.join(directory, "cache.json"), "w") as f:
        json.dump(cache, f, indent=4)
    for task in asyncio.all_tasks(loop=loop):
        task.cancel()


def syncPause(name, value):
    if eof:
        return
    for socket_id, client in clients.items():
        client.setProperty_sync("pause", value)
        if value:
            client.setProperty_sync("removeListener", "playback-time")
        else:
            client.setProperty_sync("addListener", "playback-time")
            client.accuracy = 0.05


def syncSeeking(name, value):
    mpv.pause = True
    for socket_id, client in clients.items():
        client.setProperty_sync("playback-time", mpv.playback_time + client.delay)


def syncSpeed(name, value):
    global current_speed
    # Small difference in speed is allowed in order to properly sync the players
    if abs(value - current_speed) > 0.15:
        # round speed to a value available in the youtube player
        rounded_speed = min(round(value / 0.25) * 0.25, 2)
        mpv.speed = rounded_speed if rounded_speed > 0.20 else 0.25
        current_speed = mpv.speed
        print(f"set speed to {mpv.speed}", flush=True)
        for socket_id, client in clients.items():
            client.setProperty_sync("speed", mpv.speed)
            client.speed = mpv.speed


def handle_eof(name, value):
    global eof
    # Once playback is over remove all listeners except the one for the YouTube Captions
    if value:
        # print("eof", flush=True)
        eof = True
        ids = list(mpv.property_bindings.keys())
        for prop_id in ids:
            mpv.unbind_property_observer(prop_id)
        # print(mpv.property_bindings.keys())
        for socket_id, client in clients.items():
            client.setProperty_sync("pause", False, priority=queue_priority + 100)
            client.setProperty_sync(
                "removeListener", "state", priority=queue_priority + 101
            )
            client.setProperty_sync(
                "removeListener", "playback-time", priority=queue_priority + 102
            )
        stopScript()


async def main():
    global loop

    # loop = asyncio.get_event_loop()
    loop = asyncio.get_running_loop()
    # print(f"main loop: {loop}", flush=True)

    if useCached:
        show_info("Click the Sync button on your Browser")
    else:
        show_info(
            "Manually sync the videos, then click the Sync button on your Browser",
        )

    try:
        async with websockets.serve(handler, "localhost", PORT, ssl=ssl_context):

            def exit_handler(signal, frame):
                stopScript()
                mpv.terminate()

            if os.name == "nt":
                signal.signal(signal.SIGBREAK, exit_handler)
            signal.signal(signal.SIGINT, exit_handler)
            signal.signal(signal.SIGTERM, exit_handler)

            mpv.quit_callback = stopScript

            task = asyncio.create_task(monitorMPV(mpvQ))
            try:
                await task
            except asyncio.CancelledError:
                pass
            mpv.terminate()

    except OSError as error:
        print(error.strerror, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
