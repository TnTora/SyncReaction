import asyncio
import os
import json
import websockets
import signal
import argparse
import time
import ssl
from python_mpv_jsonipc import MPV
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from enum import Enum

from typing import Any, TYPE_CHECKING, ClassVar, Literal
from collections.abc import Callable

if TYPE_CHECKING:
    from uuid import UUID

# Uncomment the following 4 lines to monitor websocket connection

# import logging

# logger = logging.getLogger("websockets")
# logger.setLevel(logging.DEBUG)
# logger.addHandler(logging.StreamHandler())

parser = argparse.ArgumentParser()
parser.add_argument("-c", "--cache", action="store_true", default=False)
parser.add_argument("-s", "--subprocess", action="store_true", default=False)
parser.add_argument("--socket", default=None)
parser.add_argument("--ssl", action="store_true", default=False)

args = parser.parse_args()
useCached: bool = args.cache
subprocess: bool = args.subprocess
SOCKET: str | None = args.socket
use_ssl: bool = args.ssl


class Options:
    # Default Values
    PORT: int = 8001  # PORT used for websocket server
    pause_to_sync: bool = True
    cache_size:int = 20


class MpvContext:
    current_osd: str = ""
    queue_priority: int = 0
    eof: bool = False
    mpvQ = asyncio.PriorityQueue()
    mpv_pause_binding = None


class SyncContext:
    loop: asyncio.AbstractEventLoop
    player_focus: "UUID"
    current_speed: float = 1
    clients: dict["UUID", "PlayerClient"] = {}  # noqa: RUF012
    tasks: dict[str, asyncio.Task] = {}  # noqa: RUF012


# ------------- Connect to mpv -------------------------------------

if os.name == "nt":
    pipe = "\\\\.\\pipe\\"
    if SOCKET is None:
        SOCKET = "tmp\\mpvsocket"
else:
    pipe = ""
    if SOCKET is None:
        SOCKET = "/tmp/mpvsocket"  # noqa: S108

while True:
    try:
        mpv = MPV(start_mpv=False, ipc_socket=SOCKET)
        break
    except Exception as e:
        if subprocess:
            print("Failed to start mpv.", flush=True)
            raise SystemExit(e) from e
        input(
            f"Open video with mpv (or mpv based player) using the option --input-ipc-server={pipe+SOCKET}, then press ENTER"
        )

mpv.keep_open = "always"  # Leave the player on the last frame rather then closing or moving to the next file
mpv.video_sync = "audio"

# ------- Get script directory -----------------------------

directory = Path(mpv.expand_path("~~/script-opts/SyncReaction"))

if not directory.is_dir():
    directory.mkdir(parents=True)

# ------- Setup SSL certificate if needed --------------------

if use_ssl:
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    ssl_cert = directory / "fullchain.pem"
    ssl_key = directory / "cert-key.pem"

    ssl_context.load_cert_chain(ssl_cert, keyfile=ssl_key)
else:
    ssl_context = None

# ------- Load Cache ----------------------------------------

if not (directory / "SyncReaction_cache.json").is_file():
    with open(directory / "SyncReaction_cache.json", "w") as f:
        json.dump({}, f)

with open(directory / "SyncReaction_cache.json") as f:
    try:
        cache = json.load(f)
    except ValueError:
        cache = {}
        # json.dump(cache, f, indent=4)

# ------- Load Options ----------------------------------------

if not (directory / "SyncReaction_options.json").is_file():
    with open(directory / "SyncReaction_options.json", "w") as f:
        options = {
            "PORT": 8001,
            "cache_size": 20,
            "pauseToSync": True
        }
        json.dump(options, f, indent=4)

with open(directory / "SyncReaction_options.json") as f:
    try:
        options = json.load(f)
        Options.PORT = options["PORT"]  # PORT used for websocket server
        Options.pause_to_sync = options["pauseToSync"]
        Options.cache_size = options["cache_size"]
    except ValueError:
        pass

# -------------------------------------------------------------

if subprocess:
    # If the script is being run as a subprocess, sync info will be
    # displayed on the player OSD

    async def osd_output(text: str, duration: int) -> None:
        MpvContext.current_osd = text
        mpv.osd_overlay(5, "ass-events", "{\\pos(25, 25)}"+text)
        if duration > -1:
            await asyncio.sleep(duration)
            if MpvContext.current_osd == text:
                mpv.osd_overlay(5, "ass-events", "")

    def show_info(text: str, duration: int = -1, method: Literal["osd", "show-text"] = "osd") -> None:
        if method == "osd":
            asyncio.create_task(osd_output(text, duration))  # noqa: RUF006
        elif method == "show-text":
            mpv.show_text(text, duration)

else:

    def show_info(text: str, duration: int = -1, method: Literal["osd", "show-text"] = "osd") -> None:
        print(text, flush=True)


# If full, delete the oldest entry before updating cache file
def updateCache(current: str, delay: float) -> None:
    if len(cache) > Options.cache_size:
        # delete oldest entry
        cache.pop(next(iter(cache)))
    currtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time()))
    cache[current] = [delay, currtime]
    with open(directory / "SyncReaction_cache.json", "w") as f:
        json.dump(cache, f, indent=4)

# -------------- mpv callbacks ------------------------------------

def syncPause(name: str, value: bool) -> None:  # noqa: FBT001
    """Update clients playback state to match mpv player."""
    if MpvContext.eof:
        return
    for client in SyncContext.clients.values():
        client.setProperty_sync("pause", value)
        if value:
            client.setProperty_sync("removeListener", "playback-time")
        else:
            client.setProperty_sync("addListener", "playback-time")
            client.accuracy = 0.05


def syncSeeking(name: str, value: float) -> None:
    """Update clients playback-time to match mpv player."""
    mpv.pause = True
    for client in SyncContext.clients.values():
        client.setProperty_sync("playback-time", mpv.playback_time + client.delay)


def syncSpeed(name: str, value: float) -> None:
    """Update clients speeds to match mpv player."""
    # Small difference in speed is allowed in order to properly sync the players
    if abs(value - SyncContext.current_speed) > 0.15:  # noqa: PLR2004
        # round speed to a value available in the youtube player
        rounded_speed = min(round(value / 0.25) * 0.25, 2)
        mpv.speed = max(rounded_speed, 0.25)
        SyncContext.current_speed = mpv.speed
        print(f"set speed to {mpv.speed}", flush=True)
        for client in SyncContext.clients.values():
            client.setProperty_sync("speed", mpv.speed)
            client.speed = mpv.speed


def handle_eof(name: str, value: bool) -> None:  # noqa: FBT001
    """Once playback is over remove all listeners except the one for the YouTube Captions."""
    if value:
        MpvContext.eof = True
        ids = list(mpv.property_bindings.keys())
        for prop_id in ids:
            mpv.unbind_property_observer(prop_id)

        for client in SyncContext.clients.values():
            client.setProperty_sync("pause", False, priority=MpvContext.queue_priority + 100)
            client.setProperty_sync(
                "removeListener", "state", priority=MpvContext.queue_priority + 101
            )
            client.setProperty_sync(
                "removeListener", "playback-time", priority=MpvContext.queue_priority + 102
            )
        stopScript()


# ---------- handle connections -----------------------------

async def add_client(websocket: websockets.ServerConnection) -> None:
    new_player = PlayerClient(websocket)
    await new_player.find_id()
    await new_player.find_delay()

    SyncContext.clients[websocket.id] = new_player

    if len(SyncContext.clients) == 1:
        new_player.set_main(True)
        SyncContext.player_focus = websocket.id

        MpvContext.mpv_pause_binding = mpv.bind_property_observer("core-idle", syncPause)
        mpv.bind_property_observer("speed", syncSpeed)
        mpv.bind_property_observer("eof-reached", handle_eof)
        mpv.bind_property_observer("seeking", syncSeeking)

        rounded_speed = min(round(mpv.speed / 0.25) * 0.25, 2)
        mpv.speed = max(rounded_speed, 0.25)

        SyncContext.tasks["sync_check"] = asyncio.create_task(periodicSyncCheck())

    await new_player.setProperty("speed", mpv.speed)
    mpv.playback_time += 0.001

    print("current: ", mpv.filename + new_player.id, flush=True)
    show_info("Connected", 1)

def handle_set_pause(player: "PlayerClient", msg: Any) -> None:
    if player.delay is None:
        return

    if PlayerStatus(msg["value"]) == PlayerStatus.PLAYING:
        mpv.pause = False
        player.buffering_resume_attempts = 0
    elif PlayerStatus(msg["value"]) == PlayerStatus.BUFFERING and player.buffering_resume_attempts < PlayerClient.max_resume_attempts:
        player.setProperty_sync("pause", False)
        player.buffering_resume_attempts += 1
    else:
        mpv.pause = True
        player.buffering_resume_attempts = 0

    player.state = PlayerStatus(msg["value"])

def handle_set_speed(player: "PlayerClient", msg: Any) -> None:
    mpv.speed = float(msg["value"])

def handle_clientStop(player: "PlayerClient", msg: Any) -> None:
    if len(SyncContext.clients) == 1:
        stopScript(notifyClient=False)
        return

    SyncContext.clients.pop(player.socket.id)
    if player.main_player:
        SyncContext.clients[next(iter(SyncContext.clients))].set_main(True)

def handle_focus(player: "PlayerClient", msg: Any) -> None:
    if SyncContext.player_focus == player.socket.id:
        return
    SyncContext.player_focus = player.socket.id
    show_info(f"focus: {SyncContext.clients[SyncContext.player_focus].id}", 1)

msg_handler_set: dict[str, Callable[["PlayerClient", Any], None]] = {
    "pause": handle_set_pause,
    "speed": handle_set_speed,
}
msg_handler_notice: dict[str, Callable[["PlayerClient", Any], None]] = {
    "clientStop": handle_clientStop,
    "focus": handle_focus,
}

async def handler(websocket: websockets.ServerConnection) -> None:
    # Code executed the first time a client connect to the server
    if websocket not in SyncContext.clients.values():
        try:
            await add_client(websocket)
        except (KeyError, IndexError):
            return

    # Handling incoming messages from client
    async for message in websocket:
        player = SyncContext.clients[websocket.id]
        msg = json.loads(message)

        if msg["type"] == "playbackSync":
            client_sent_time = msg["time"]
            time_adjustment = time.time() - client_sent_time
            player.playback_time = float(msg["value"]) + time_adjustment
            await player.check_sync()
        elif msg["type"] == "set":
            msg_handler_set[msg["property"]](player, msg)
        elif msg["type"] == "notice":
            msg_handler_notice[msg["value"]](player, msg)

# ---------- monitoring funcitons -----------------------------

async def monitorMPV(queue: asyncio.Queue) -> None:
    while True:
        msg = await queue.get()
        if "client" in msg[1]:
            client = SyncContext.clients[msg[1]["client"]]
            msg[1].pop("client")
            await client.socket.send(json.dumps(msg[1]))
            continue
        for client in SyncContext.clients.values():
            await client.socket.send(json.dumps(msg[1]))

async def periodicSyncCheck() -> None:
    while True:
        await asyncio.sleep(60)
        if mpv.pause:
            continue
        for client in SyncContext.clients.values():
            await client.setProperty("addListener", "playback-time")

async def check_connection() -> None:
    while True:
        try:
            mpv.command("client_name")
            await asyncio.sleep(5)
        except BrokenPipeError:  # noqa: PERF203
            import sys  # noqa: PLC0415
            print("Connection to mpv dropped. Terminating script...", flush=True)
            mpv.terminate()
            sys.exit()

# ---------------------------------------------------------------

class PlayerStatus(Enum):
    PLAYING: int = 1
    PAUSED: int = 0
    BUFFERING: int = 3

    @classmethod
    def _missing_(cls, value):
        return cls.PAUSED

class PlayerClient:

    max_diff: float = 2
    mid_diff: float = 0.2
    max_resume_attempts: int = 5
    failed_find_cache: ClassVar[set[str]] = set()

    def __init__(self, websocket: websockets.ServerConnection) -> None:
        self.socket = websocket
        self.url: str
        self.id: str | None = None
        self.delay: float | None = None
        self.state = None
        self.playback_time = None
        self.speed = 1
        self.main_player = False
        self.sleeping = False
        self.accuracy = 0.15  # (0.06-0.19) deviation from sync before the script starts small correction
        self.original_accuracy = self.accuracy
        self.buffering_resume_attempts = 0

        self.check_sync = self.check_sync_sub

    async def setProperty(self, name: str, value: Any) -> None:
        msg = {"type": "set", "property": name, "value": value}
        await self.socket.send(json.dumps(msg))

    async def getProperty(self, name: str) -> Any:
        msg = {"type": "get", "property": name, "value": None}
        await self.socket.send(json.dumps(msg))
        while True:
            answer = await self.socket.recv()
            loadedAnswer = json.loads(answer)
            if loadedAnswer["type"] == "get-property":
                break
        return loadedAnswer["value"]

    def setProperty_sync(self, name: str, value: Any, priority: int | None = None) -> None:
        if priority is None:
            priority = MpvContext.queue_priority
        msg = (priority, {"type": "set", "property": name, "value": value, "client": self.socket.id})
        MpvContext.queue_priority += 1
        SyncContext.loop.call_soon_threadsafe(MpvContext.mpvQ.put_nowait, msg)

    def set_main(self, value: bool) -> None:  # noqa: FBT001
        self.main_player = value
        if self.main_player:
            self.check_sync = self.check_sync_main
        else:
            self.check_sync = self.check_sync_sub

    @staticmethod
    def get_id_from_url(url: str) -> str | None:
        # Get video ID from youtube URL
        parsed_url = urlparse(url)
        v_query = parse_qs(parsed_url.query).get("v")
        if v_query:
            return v_query[0]
        path_list = parsed_url.path.split("/")
        if path_list:
            return path_list[-1]

    async def find_id(self) -> None:
        self.url = await self.getProperty("url")
        self.id = self.get_id_from_url(self.url)

    async def find_cached_delay(self) -> None:
        if self.id is None:
            raise ValueError("id is None")
        # if mpv.filename + self.id in cache:
        try:
            self.delay = cache[mpv.filename + self.id][0]
        except (KeyError, IndexError):
        # else:
            PlayerClient.failed_find_cache.add(self.id)
            show_info(
            text = f"Delay not found in cache. Manually sync the videos, then click the Sync button on your Browser (use_ssl: {use_ssl})",
            duration = -1 if len(SyncContext.clients) == 0 else 10,
            )
            raise
            # await asyncio.sleep(1)
            # stopScript()

    async def set_delay(self) -> None:
        if self.id is None:
            raise ValueError("id is None")
        self.delay = await self.getProperty("playback-time") - mpv.playback_time
        print(f"client_id:{self.id}, delay:{self.delay}", flush=True)
        updateCache(mpv.filename + self.id, self.delay)
        PlayerClient.failed_find_cache.discard(self.id)
        show_info(f"delay: {int(self.delay // 60)}:{round(self.delay % 60, 3)}", 2)

    async def find_delay(self) -> None:
        if not useCached or self.id in PlayerClient.failed_find_cache:
            await self.set_delay()
        else:
            await self.find_cached_delay()

    async def check_sync_main(self) -> None:

        if self.sleeping:
            return

        diff = self.playback_time - mpv.playback_time - self.delay

        if Options.pause_to_sync and -PlayerClient.max_diff < diff < -self.accuracy:
            show_info("Syncing...", round(abs(diff)) * 1000)
            if MpvContext.mpv_pause_binding in mpv.property_bindings:
                mpv.unbind_property_observer(MpvContext.mpv_pause_binding)
            self.sleeping = True
            mpv.pause = True
            await asyncio.sleep(abs(diff))
            mpv.pause = False
            if mpv.property_bindings:
                MpvContext.mpv_pause_binding = mpv.bind_property_observer("pause", syncPause)
            self.sleeping = False
            self.accuracy = 0.05
        elif abs(diff) > PlayerClient.max_diff:
            mpv.pause = True
            show_info(f"diff: {round(diff, 6)} seeking")
            await self.setProperty("playback-time", mpv.playback_time + self.delay)
        elif abs(diff) > PlayerClient.mid_diff:
            speed_modifier = (diff / abs(diff)) * 0.05
            mpv.speed = self.speed + speed_modifier
            show_info(f"diff: {round(diff, 6)};   speed: {mpv.speed}")
            self.accuracy = 0.05
        elif abs(diff) > self.accuracy:
            speed_modifier = (diff / abs(diff)) * 0.01
            mpv.speed = self.speed + speed_modifier
            show_info(f"diff: {round(diff, 6)};   speed: {mpv.speed}")
            self.accuracy = 0.05
        elif self.accuracy != self.original_accuracy:
            mpv.speed = self.speed
            show_info(f"Synced within ~{self.accuracy} sec;  speed: {mpv.speed}", 2)
            self.accuracy = self.original_accuracy
        else:
            await self.setProperty("removeListener", "playback-time")

    async def check_sync_sub(self) -> None:

        diff = mpv.playback_time + self.delay - self.playback_time

        if abs(diff) > PlayerClient.max_diff:
            mpv.pause = True
            show_info(f"sub_player diff: {round(diff, 6)} seeking")
            await self.setProperty("playback-time", mpv.playback_time + self.delay)
        elif abs(diff) > PlayerClient.mid_diff:
            speed_modifier = (diff / abs(diff)) * 0.05
            await self.setProperty("speedOffset", speed_modifier)
            show_info(f"sub_player diff: {round(diff, 6)};   speed: {mpv.speed+speed_modifier}")
            self.accuracy = 0.05
        elif abs(diff) > self.accuracy:
            speed_modifier = (diff / abs(diff)) * 0.01
            await self.setProperty("speedOffset", speed_modifier)
            show_info(f"sub_player diff: {round(diff, 6)};   speed: {mpv.speed+speed_modifier}")
            self.accuracy = 0.05
        elif self.accuracy != self.original_accuracy:
            await self.setProperty("speed", self.speed)
            show_info(f"Synced sub_player within ~{self.accuracy} sec;  speed: {self.speed}", 2)
            self.accuracy = self.original_accuracy
        else:
            await self.setProperty("removeListener", "playback-time")


# ------ Setup Key Bindings -------------------------------

def changeDelay(offSet: float, client: "PlayerClient", *, show_msg: bool = True):
    if client.delay is None:
        return
    client.delay += offSet
    client_id = f" {client.id}" if len(SyncContext.clients) > 1 else ""
    if show_msg:
        show_info(f"delay{client_id}: {int(client.delay // 60)}:{round(client.delay % 60, 3)}", 1000, "show-text")
    client.setProperty_sync("addListener", "playback-time")


@mpv.on_key_press("ALT+m", forced=True)
def addDelay() -> None:
    changeDelay(0.05, SyncContext.clients[SyncContext.player_focus])


@mpv.on_key_press("ALT+n", forced=True)
def lessDelay() -> None:
    changeDelay(-0.05, SyncContext.clients[SyncContext.player_focus])


@mpv.on_key_press("ALT+Shift+m", forced=True)
def addDelayAll() -> None:
    msg = ""
    for client in SyncContext.clients.values():
        if client.delay is None:
            continue
        changeDelay(0.05, client, show_msg=False)
        msg += f"delay {client.id}: {int(client.delay // 60)}:{round(client.delay % 60, 3)}\n"
    show_info(msg, 1000, "show-text")


@mpv.on_key_press("ALT+Shift+n", forced=True)
def lessDelayAll() -> None:
    msg = ""
    for client in SyncContext.clients.values():
        if client.delay is None:
            continue
        changeDelay(-0.05, client, show_msg=False)
        msg += f"delay {client.id}: {int(client.delay // 60)}:{round(client.delay % 60, 3)}\n"
    show_info(msg, 1000, "show-text")


@mpv.on_key_press("ALT+CTRL+x", forced=True)
def manualSyncCheck() -> None:
    for client in SyncContext.clients.values():
        client.setProperty_sync("addListener", "playback-time")


@mpv.on_key_press("ESC", forced=True)
def stopScript(*, notifyClient: bool = True) -> None:
    if notifyClient:
        msg = {"type": "notice", "property": None, "value": "stopping server"}
        SyncContext.loop.call_soon_threadsafe(MpvContext.mpvQ.put_nowait, (0, msg))
    with open(directory / "SyncReaction_cache.json", "w") as f:
        json.dump(cache, f, indent=4)
    for task in asyncio.all_tasks(loop=SyncContext.loop):
        task.cancel()


async def main() -> None:

    SyncContext.tasks["conn_check"] = asyncio.create_task(check_connection())

    SyncContext.loop = asyncio.get_running_loop()

    if useCached:
        show_info(f"Click the Sync button on your Browser (use_ssl: {use_ssl})")
    else:
        show_info(
            f"Manually sync the videos, then click the Sync button on your Browser (use_ssl: {use_ssl})",
        )

    try:
        async with websockets.serve(handler, "localhost", Options.PORT, ssl=ssl_context):

            def exit_handler(signal, frame):
                stopScript()
                mpv.terminate()

            if os.name == "nt":
                signal.signal(signal.SIGBREAK, exit_handler)
            signal.signal(signal.SIGINT, exit_handler)
            signal.signal(signal.SIGTERM, exit_handler)

            mpv.quit_callback = stopScript

            main_task = asyncio.create_task(monitorMPV(MpvContext.mpvQ))
            SyncContext.tasks["main"] = main_task
            try:  # noqa: SIM105
                await main_task
            except asyncio.CancelledError:
                pass
            mpv.terminate()

    except OSError as error:
        print(error.strerror, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
