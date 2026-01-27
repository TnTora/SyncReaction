# SyncReaction

mpv script to sync mpv playback with youtube videos (or html5 videos in general).

### Demo



https://github.com/user-attachments/assets/e4cde6ee-8235-43e9-ae24-1b29ad27b0af



## Usage

Open both the YouTube video and mpv. If the userscript is running correctly you will notice a `Sync` option among the YouTube player controls, to the right of the fullscreen button.

<img width="253" height="33" alt="sync" src="https://github.com/user-attachments/assets/bd8937ef-f0c4-4d4d-852a-2786d83e122f" />


On mpv, use one of the following keybindigs to interact with the python script. They are purposely complex as to not overwrite already existing user defined ones. If you want to modify them check the `Change Keybindings` section below.

| Keybinding | Function name | Description |
|------------|---------------|-------------|
|Ctrl+Alt+s  |startsync      | Start script without searching cache database for timings
|Ctrl+Alt+c  |searchCache    | Start script searching cache database for timings
|Ctrl+Alt+a  |stopScript     | Kill the script
|Ctrl+Alt+g  |toggle_ssl     | Toggle use of SSL certificates (requires extra setup)

- Use `searchCache` when you have already synced the videos once and you want to retain the same delay.

- Use `startsync` when you sync videos for the first time or the delay found in cache is wrong and you wish to update it.

- `stopScript` will forcfully kill the script. When possible, use the `UnSync` button on the YouTube player or press `ESC` while focused on mpv.

<img width="279" height="46" alt="unsync" src="https://github.com/user-attachments/assets/2089da86-33ac-4c34-96bb-518d2c370dbc" /><br>

Once the script starts, follow the instructions that appear on top of mpv.
When the videos are synced, the following actions/properties are automatically matched:
- pause/play
- seeking (only from mpv, seeking on youtube will be reset to match mpv)
- playback speed

While the script is running you can perform small adjustment to the delay using the keybindings

`delay = youtube_playback_time - mpv_playback_time`

| Keybinding | Function name | Description |
|------------|---------------|-------------|
|Alt+n       |lessDelay      | add -0.05 to delay |
|Alt+m       |addDelay       | add 0.05 to delay |
## Installation

There are two parts to this project that you need to install: the mpv script and a userscript to interact with the browser. The following sections will guide you through the setup process. 

Locate your mpv config folder. It is typically found at `~/.config/mpv/` on Linux/MacOS and `C:\users\USERNAME\AppData\Roaming\mpv\` on Windows.  [Files section](https://mpv.io/manual/master/#files) in mpv's manual for more info. I will refer to the path of this folder as `<mpv config directory>` for the rest of this file.

To install the mpv script you can either use the precompiled binaries without having to install anything else. Otherwise you can setup a python environent to run the script. Binaries have not been thoroughly tested, open an Issue if you encounter any problem.

### Setup mpv script using compiled binaries
- Download the build version matching your system from the Release page and extract its contents
- Place the `SyncReaction` folder inside the `scripts` folder in `<mpv config directory>`. If it doesn't exist you should create it.

### Setup mpv script using python script

- Download the source code from Release section.

- Place the `SyncReaction` folder inside the `scripts` folder in `<mpv config directory>`. If it doesn't exist you should create it.

If you don't already have python 3.10 or above installed on your machine, install it. On Windows make sure python is added to PATH.

>**Optional:** Create and activate a [virtual environment](https://docs.python.org/3/library/venv.html) named `.mpv_venv` in `<mpv config directory>`. While optional, it is highly reccomended to keep the script isolated from the system python.
>
> If you chose a different name for the virtual environment or you want to use a different version of pyhton, open `main.lua` in a text editor and set the `custom_python_cmd` variable to a string containing your preferred command or path to binary.

Install dependencies (substitute `/` with `\` if you are on Windows)

```
cd <mpv config directory>
cd scripts/SyncReaction
pip install -r requirement.txt
```

**Optional:**  change speed modifiers key bindings in input.conf. The default setting multiplies the current speed by 1.1 or 1/1.1, Changing those settings to “add speed 0.25” and “add speed -0.25”  you get 0.25 increments that also match the YouTube player. 

> **NOTE: 
> If you don’t change these settings, only change speed from the YouTube player while the script is running.**

### Change Keybindings

Open the input.conf file in mpv config folder using a text editor. Create it if it does not exist.

Add the following text after changing the keybindings to your preferred ones:


```
# SyncReaction
Ctrl+Alt+s              script-binding SyncReaction/startsync
Ctrl+Alt+c              script-binding SyncReaction/searchCache
Ctrl+Alt+a              script-binding SyncReaction/stopScript
Ctrl+Alt+g              script-binding SyncReaction/toggle_ssl
```

> **NOTE: If you are not using the [standard mpv build](https://mpv.io/installation/), your player might ignore the `input.conf` file (e.g. [mpv.net](https://github.com/mpvnet-player/mpv.net), [IINA](https://iina.io/)) so you might need to use the in-app options to change the keybindings.**

### Install Userscript

Install a userscript manager extension on your browser. I have tested [Tampermonkey](https://www.tampermonkey.net/) on Firefox/Chromium and [Userscripts](https://github.com/quoid/userscripts) on Safari.

On Chromium based browsers you may need to enable `Allow user scripts` in `Manage Extensions` -> `Tampermonkey`.

<img width="674" height="308" alt="tampermonkey_options" src="https://github.com/user-attachments/assets/8dc328db-847c-47e6-b75c-224809f7661b" /><br>


Install `sync.user.js` for use on YouTube (stable) or `sync_general.user.js` for general html5 videos (alpha, does not work on Safari).

Either use the file from the release and drop it on the correct extension page or open the raw file here on github by clicking one the following links: [youtube](https://raw.githubusercontent.com/TnTora/SyncReaction/refs/heads/main/sync.user.js), [general](https://raw.githubusercontent.com/TnTora/SyncReaction/refs/heads/main/sync_general.user.js); the extension should propt you to install with either a popup or an option in the extension icon tray.

You might need to grant permission to access the web page the first time the userscript runs.

#### Safari extra steps
If you are using Safari you will need a few more stepts before you can use the script. As far as I am aware Safari does not allow to connect to a `ws` server from a `https` page such as YouTube, so you will need to switch to `wss`. If you are not comfortable with using the terminal you might want to just switch to a different browser to use this script. 

Open Userscript extension page and change the following line in the installed userscript.

`const protocol = "ws"` to `const protocol = "wss"`

Generate a self signed SSL certificate. I followed this [video](https://www.youtube.com/watch?v=VH4gXcvkmOY).

Take the `cert-key.pem` and `fullchain.pem` files that you generated and place them into `<mpv config directory>/script-opts/SyncReaction`. Create any folder that does not exist.


## Dependencies
| Name | LICENSE |
|------|---------|
| [websockets](https://github.com/python-websockets/websockets) | [BSD 3-Clause](https://github.com/python-websockets/websockets/blob/main/LICENSE) |
| [python-mpv-jsonipc](https://github.com/TnTora/python-mpv-jsonipc) (TnTora) <br> forked from [python-mpv-jsonipc](https://github.com/iwalton3/python-mpv-jsonipc) (iwalton3) | [Apache-2.0](https://github.com/TnTora/python-mpv-jsonipc/blob/master/LICENSE.md) |
