// ==UserScript==
// @name         SyncPlayers-general
// @version      0.4
// @description  Sync playback between html5 video and mpv
// @match        https://*/*
// @icon         data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==
// @grant        GM_registerMenuCommand
// @grant        GM_unregisterMenuCommand
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';
    const PORT = 8001;
    const protocol = "ws"
    let running = false;
    let mn = GM_registerMenuCommand("Sync", startSync);

    window.addEventListener('beforeunload', function (e) {
        // Stop the script if it is still running while the window is being closed
        if (running) {
            stopSync();
        };
    });

    // Declare global variables so they can be accessed outside startSync function
    let gTime;
    let websocket;
    let player;
    let mainVideo

    function sendState(evt) {
        let v;
        if (evt.type == "pause") {
            v = 0;
        };
        if (evt.type == "playing") {
            v = 1;
        };
        const msg = {
            type: "set",
            property: "pause",
            //value: data
            value: v
        };
        websocket.send(JSON.stringify(msg));
    };

    function sendSpeed() {
        const msg = {
            type: "set",
            property: "speed",
            value: mainVideo.playbackRate
        };
        websocket.send(JSON.stringify(msg));
    };

    // Send current playback time
    function getTime() {
        const currentPlaybackTime = mainVideo.currentTime;
        const currentTimeSec = Date.now()/1000;
        const msg = {
            type: "playbackSync",
            property: "playback-time",
            value: currentPlaybackTime,
            time: currentTimeSec
        };
        websocket.send(JSON.stringify(msg));
        //console.log(currentTime);
    };

    function stopSync() {
        running = false;
        mainVideo.removeEventListener("timeupdate", getTime);
        mainVideo.removeEventListener("playing", sendState);
        mainVideo.removeEventListener("pause", sendState);
        mainVideo.removeEventListener("ratechange", sendSpeed);
        const msg = {
            type: "notice",
            value: "clientStop"
        };
        websocket.send(JSON.stringify(msg));
        websocket.close(1000);
    };

    function startSync() {
        running = true;
        GM_unregisterMenuCommand(mn);
        mn = GM_registerMenuCommand("UnSync", stopSync);
        websocket = new WebSocket(`${protocol}://localhost:${PORT}/`);
        mainVideo = document.getElementsByTagName('video')[0];
        console.log(document.getElementsByTagName('video'));


        // Handle messages received from server
        websocket.addEventListener("message", ({ data }) => {
            const msg = JSON.parse(data);
            //console.log(msg);
            if (msg.type == "set") {
                switch (msg.property) {
                    case "pause":
                        mainVideo.removeEventListener("playing", sendState);
                        mainVideo.removeEventListener("pause", sendState);
                        if (msg.value) {
                            mainVideo.pause();
                        } else {
                            mainVideo.play();
                        };
                        mainVideo.addEventListener("playing", sendState);
                        mainVideo.addEventListener("pause", sendState);
                        break;
                    case "playback-time":
                        mainVideo.currentTime = msg.value;
                        break;
                    case "speed":
                        mainVideo.playbackRate = msg.value;
                        break;
                    case "speedOffset":
                        mainVideo.playbackRate = mainVideo.playbackRate + msg.value;
                        break;
                    case "removeListener":
                        if (msg.value == "state") {
                            mainVideo.removeEventListener("playing", sendState);
                            mainVideo.removeEventListener("pause", sendState);
                        } else if (msg.value == "playback-time") {
                            mainVideo.removeEventListener("timeupdate", getTime);
                        };
                        break;
                    case "addListener":
                        if (msg.value == "state") {
                            mainVideo.addEventListener("playing", sendState);
                            mainVideo.addEventListener("pause", sendState);
                        } else if (msg.value == "playback-time") {
                            mainVideo.addEventListener("timeupdate", getTime);
                        };
                        break;
                };

            } else if (msg.type == "get") {
                let answer = {};
                switch (msg.property) {
                    case "playback-time":
                        answer = {
                            type: "get-property",
                            property: "playback-time",
                            value: mainVideo.currentTime
                        };
                        break;
                    case "url":
                        answer = {
                            type: "get-property",
                            property: "url",
                            value: window.location.href
                        };
                        break;
                };
                websocket.send(JSON.stringify(answer));
                //console.log("answering:");
                //console.log(answer);
            } else if (msg.type == "notice") {
                switch (msg.value) {
                    case "stopping server":
                        running = false;
                        mainVideo.removeEventListener("timeupdate", getTime);
                        mainVideo.removeEventListener("playing", sendState);
                        mainVideo.removeEventListener("pause", sendState);
                        mainVideo.removeEventListener("ratechange", sendSpeed);
                        websocket.close(1000);
                        break;
                };
            };
        });

        mainVideo.addEventListener("playing", sendState);
        mainVideo.addEventListener("pause", sendState);

        mainVideo.addEventListener("ratechange", sendSpeed);

        document.addEventListener("focus", function(){
            const msg = {
                type: "notice",
                value: "focus"
            };
            websocket.send(JSON.stringify(msg));
            console.log("Page in focus")
        })


        websocket.addEventListener("error", function (e) {
            console.log(e);
            stopSync();
        });

        websocket.onclose = () => {
            GM_unregisterMenuCommand(mn);
            mn = GM_registerMenuCommand("Sync", startSync);
        };
    };

})();
