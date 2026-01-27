
local utils = require 'mp.utils'

local script_path = utils.join_path(mp.get_script_directory(), "SyncReaction.py")
local running = false
local video_sync = mp.get_property_native("video-sync")
local old_ipc_server = mp.get_property_native("input-ipc-server")
local new_ipc_server
local use_ssl = false
local custom_python_cmd
local python_cmd
local bin_path
local default_venv_bin
local syncScript

if package.config:sub(1,1) == '/' then
  python_cmd = "python3"
  bin_path = utils.join_path(mp.get_script_directory(), "bin/SyncReaction.bin")
  default_venv_bin = mp.command_native({"expand-path", "~~/.mpv_venv/bin/python"})
  new_ipc_server = "/tmp/mpvsocket"
else
  python_cmd = "py"
  bin_path = utils.join_path(mp.get_script_directory(), "bin/SyncReaction.exe")
  default_venv_bin = mp.command_native({"expand-path", "~~/.mpv_venv/Scripts/python.exe"})
  new_ipc_server = "\\\\.\\pipe\\tmp\\mpvsocket"
end

if utils.file_info(bin_path) == nil then
  bin_path = nil
end

if utils.file_info(default_venv_bin) ~= nil then
  python_cmd = default_venv_bin
end

if custom_python_cmd then
  python_cmd = custom_python_cmd
end

local function startScript(additional_args)
  if running then
    mp.osd_message("Script already running", 2)
  else
    running = true
    old_ipc_server = mp.get_property_native("input-ipc-server")
    if old_ipc_server == "" then
      mp.set_property("input-ipc-server", new_ipc_server)
    else
      new_ipc_server = old_ipc_server
    end

    local arguments

    print(python_cmd)

    if bin_path then
      arguments = {
        bin_path,
      }
    else
      arguments = {
        python_cmd,
        script_path,
      }
    end

    table.insert(arguments, "-s")
    table.insert(arguments, "--socket")
    table.insert(arguments, new_ipc_server)

    for i=1, #additional_args, 1 do
      table.insert(arguments, additional_args[i])
    end

    if use_ssl then
      table.insert(arguments, "--ssl")
    end

    syncScript = mp.command_native_async({
        name = "subprocess",
        playback_only = true,
        args = arguments,
      },
      function(res, val, err)
          mp.osd_message("Sync script has stopped", 2)
          mp.set_property("video-sync", video_sync)
          mp.set_property("input-ipc-server", old_ipc_server)
          mp.set_property("speed", 1)
          running = false
      end
    )
  end

end

local function sync()
  startScript({})
end

local function searchCache()
  startScript({"--cache"})
end

local function stopScript()
  if running then
    mp.abort_async_command(syncScript)
  else
    mp.osd_message("Script is not running", 2)
  end
end

mp.add_key_binding("CTRL+ALT+g", "toggle_ssl", function()
  use_ssl = not use_ssl
  mp.osd_message("use_ssl: "..tostring(use_ssl))
end)

mp.add_forced_key_binding("CTRL+ALT+s", "startsync", sync, {repeatable=false})
mp.add_forced_key_binding("CTRL+ALT+c", "searchCache", searchCache, {repeatable=false})
mp.add_forced_key_binding("CTRL+ALT+a", "stopScript", stopScript, {repeatable=false})
