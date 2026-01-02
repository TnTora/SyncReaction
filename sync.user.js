// ==UserScript==
// @name         SyncPlayers
// @version      0.4
// @description  Sync playback between YouTube video and mpv
// @match        https://www.youtube.com/*
// @icon         data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==
// @grant        none
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';
    const PORT = 8001;
    const protocol = "ws"
    let div;
    let span;
    let button;
    let running = false;

    function addButton() {
        // Check URL
        if (!window.location.pathname.startsWith("/watch")) { return }

        // Create Button, uses the actual youtube button classes so it may need to be changed if youtube ever modify them
        div = document.createElement("div");
        div.setAttribute("name", "top_level_sync_btn");
        div.className = "style-scope ytd-menu-renderer";
        div.style.marginLeft = "8px";
        span = document.createElement("span");
        span.innerText = "Sync";
        button = document.createElement("button");
        button.className = "yt-spec-button-shape-next yt-spec-button-shape-next--tonal yt-spec-button-shape-next--mono yt-spec-button-shape-next--size-m yt-spec-button-shape-next--icon-leading ";
        button.appendChild(span);
        button.onclick = startSync;
        div.appendChild(button);

        // Try to display button untill toolbar is ready
        let toolbar = document.querySelectorAll("div.style-scope ytd-watch-metadata #top-level-buttons-computed")[0];
        const test = setInterval(function () {
            console.log("Waiting for toolbar to load...");
            if (toolbar == null) { toolbar = document.querySelectorAll("div.style-scope ytd-watch-metadata #top-level-buttons-computed")[0]; }
            else {
                toolbar.appendChild(div);
                console.log("Sync button appended");
                clearInterval(test);
            };
        }, 1000);
    };

    addButton();

    document.addEventListener('yt-navigate-finish', () => {
        // Run the function every time you navigate to a new page
        addButton();
    });

    document.addEventListener('yt-navigate-start', () => {
        // Stop the script if it is still running while a new page is being loaded
        if (running) {
            // console.log("navigate-start");
            stopSync();
        };
    });

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

    function sendState() {
        const msg = {
            type: "set",
            property: "pause",
            //value: data
            value: player.getPlayerState()
        };
        websocket.send(JSON.stringify(msg));
    };

    function sendSpeed() {
        const msg = {
            type: "set",
            property: "speed",
            value: player.getPlaybackRate()
        };
        websocket.send(JSON.stringify(msg));
    };

    // Send current playback time
    function getTime() {
        const currentPlaybackTime = player.getCurrentTime();
        const currentTimeSec = Date.now() / 1000;
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
        player.removeEventListener("onStateChange", sendState);
        player.removeEventListener("onPlaybackRateChange", sendSpeed);
        const msg = {
            type: "notice",
            value: "clientStop"
        };
        websocket.send(JSON.stringify(msg));
        websocket.close(1000);
    };

    function startSync() {
        running = true;
        span.innerText = "UnSync";
        button.onclick = stopSync;
        websocket = new WebSocket(`${protocol}://localhost:${PORT}/`);
        player = document.getElementById('movie_player')
        mainVideo = document.getElementsByClassName('html5-main-video')[0]


        // Handle messages received from server
        websocket.addEventListener("message", ({ data }) => {
            const msg = JSON.parse(data);
            //console.log(msg);
            if (msg.type == "set") {
                switch (msg.property) {
                    case "pause":
                        player.removeEventListener("onStateChange", sendState);
                        if (msg.value) {
                            player.pauseVideo();
                        } else {
                            let Ystate = player.getPlayerState();
                            let i = 0
                            while (Ystate != 1 && i < 10) {
                                player.playVideo();
                                // mainVideo.play();
                                Ystate = player.getPlayerState();
                                i++
                                // console.log(Ystate);
                            }
                            // console.log(Ystate);
                        };
                        player.addEventListener("onStateChange", sendState);
                        break;
                    case "playback-time":
                        player.seekTo(msg.value, true);
                        break;
                    case "speed":
                        player.setPlaybackRate(msg.value);
                        break;
                    case "speedOffset":
                        mainVideo.playbackRate = player.getPlaybackRate() + msg.value;
                        break;
                    case "removeListener":
                        if (msg.value == "state") {
                            player.removeEventListener("onStateChange", sendState);
                        } else if (msg.value == "playback-time") {
                            mainVideo.removeEventListener("timeupdate", getTime);
                        };
                        break;
                    case "addListener":
                        if (msg.value == "state") {
                            player.addEventListener("onStateChange", sendState);
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
                            value: player.getCurrentTime()
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
                        player.removeEventListener("onStateChange", sendState);
                        player.removeEventListener("onPlaybackRateChange", sendSpeed);
                        websocket.close(1000);
                        break;
                };
            };
        });

        player.addEventListener("onStateChange", sendState);

        player.addEventListener("onPlaybackRateChange", sendSpeed);

        document.addEventListener("focus", function () {
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
            span.innerText = "Sync";
            button.onclick = startSync;
        };
    };

})();
