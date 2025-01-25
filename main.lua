local utils = require 'mp.utils'

local script_path = utils.join_path(mp.get_script_directory(), "SyncReaction.py")
local running = false
local video_sync = mp.get_property_native("video-sync")
local old_ipc_server = mp.get_property_native("input-ipc-server")
local new_ipc_server
local use_ssl = false
local python_cmd
local syncScript

if package.config:sub(1,1) == '/' then
  python_cmd = "python3.11"
  new_ipc_server = "/tmp/mpvsocket"
else
  python_cmd = "py"
  new_ipc_server = "\\\\.\\pipe\\tmp\\mpvsocket"
end

-- print(package.config:sub(1,1))
-- print(script_path)
-- print(script_path:sub(1,1))
-- print(python_cmd)

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

    local arguments = {
        python_cmd,
        script_path,
        "-s",
        "-d",
        mp.get_script_directory(),
        "--socket",
        new_ipc_server,

    }

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
  startScript({"-c"})
end

local function fullSubsControl()
  startScript({"-f"})
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

mp.add_forced_key_binding("CTRL+ALT+s", "startsync", sync, {repeatable=true})
mp.add_forced_key_binding("CTRL+ALT+c", "searchCache", searchCache, {repeatable=true})
mp.add_forced_key_binding("CTRL+ALT+f", "fullSubsControl", fullSubsControl, {repeatable=true})
mp.add_forced_key_binding("CTRL+ALT+a", "stopScript", stopScript, {repeatable=true})
