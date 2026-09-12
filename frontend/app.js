(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const ICONS = {
    clock: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/><path d="M18 3l2 2"/></svg>',
    question: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.1 9a3 3 0 015.8 1c0 2-3 2-3 4"/><circle cx="12" cy="17" r=".6" fill="currentColor"/><circle cx="12" cy="12" r="9"/></svg>',
    hand: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 13V6a1.5 1.5 0 013 0v6"/><path d="M11 12.5V4.5a1.5 1.5 0 013 0v8"/><path d="M14 12.5V6a1.5 1.5 0 013 0v8"/><path d="M17 13v-3a1.5 1.5 0 013 0v5c0 4-3 7-7 7s-6-2-7.5-4.5L4 14c-.6-1 .1-2 1-2 .5 0 1 .3 1.3.8L8 15"/></svg>',
    swap: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3l4 4-4 4"/><path d="M3 11V9a4 4 0 014-4h14"/><path d="M7 21l-4-4 4-4"/><path d="M21 13v2a4 4 0 01-4 4H3"/></svg>',
    target: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
  };

  const CARD_ORDER = ["extra_minute", "direct_question", "interrupt", "yield_turn", "challenge"];
  const CARD_META = {
    extra_minute: { label: "زيد دقيقة", cls: "c-green", icon: ICONS.clock, title: "زيد 60 ثانية لوقتك، تتستعمل فدورك نتا" },
    direct_question: { label: "سؤال مباشر", cls: "c-red", icon: ICONS.question, title: "وقف ساعة الخصم 30 ثانية باش يجاوب" },
    interrupt: { label: "قطع الكلمة", cls: "c-green", icon: ICONS.hand, title: "توقيف خفيف 15 ثانية باش تقاطع الخصم وتطلب توضيح" },
    yield_turn: { label: "خلي الكلمة", cls: "c-grey", icon: ICONS.swap, title: "عطي الكلمة للخصم دغيا" },
    challenge: { label: "تحداه", cls: "c-red", icon: ICONS.target, title: "قوله يبرهن على اللي قال، بلا ما توقف الوقت" },
  };

  const PHASE_ORDER = ["intro", "discussion", "closing"];
  const PHASE_LABEL = {
    intro: "التقديم — دقيقة لكل متناظر",
    discussion: "النقاش الرئيسي — 5 دقائق لكل متناظر",
    closing: "الخاتمة — دقيقتين لكل متناظر",
  };

  // STUN alone only works when both sides can be reached directly, which
  // fails across many real home/mobile/office networks (symmetric NAT,
  // strict firewalls). These add a TURN relay as a fallback — public,
  // free, well-known test credentials (openrelay.metered.ca), fine for
  // trying this out; swap for a dedicated TURN provider before real launch.
  const ICE_SERVERS = [
    { urls: "stun:stun.l.google.com:19302" },
    { urls: "stun:openrelay.metered.ca:80" },
    { urls: "turn:openrelay.metered.ca:80", username: "openrelayproject", credential: "openrelayproject" },
    { urls: "turn:openrelay.metered.ca:443", username: "openrelayproject", credential: "openrelayproject" },
    {
      urls: "turn:openrelay.metered.ca:443?transport=tcp",
      username: "openrelayproject",
      credential: "openrelayproject",
    },
  ];

  let lobbyWs = null;
  let gameWs = null;
  let gameId = null;
  let mySlot = null; // "player1" | "player2"
  let state = null;
  let selectedTopics = [];
  let selectedRoundCount = 5;

  let pc = null;
  let localStream = null;

  // ------------------------------------------------------ audience / rematch
  let isAudience = false;
  let audienceId = null;
  let remoteStream = null; // the other debater's track, captured for mixing

  // player1-only: mixes both debaters' audio into one stream and meshes it
  // out to every spectator, one receive-only RTCPeerConnection each.
  let audienceMixStream = null;
  let audienceAudioCtx = null;
  const audiencePeers = {};
  let pendingAudienceJoins = [];

  // audience-only: single receive-only connection to player1's mix.
  let audiencePc = null;

  let hasVoted = false;
  let rematchTopics = [];

  function fmt(s) {
    s = Math.max(0, Math.floor(s));
    const m = Math.floor(s / 60), r = s % 60;
    return m + ":" + (r < 10 ? "0" + r : r);
  }

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(t._h);
    t._h = setTimeout(() => (t.hidden = true), 2400);
  }

  function showScreen(id) {
    ["screen-lobby", "screen-waiting", "screen-game"].forEach((s) => ($(s).hidden = s !== id));
  }

  function sendGame(action, extra) {
    if (!gameWs || gameWs.readyState !== WebSocket.OPEN) return;
    gameWs.send(JSON.stringify(Object.assign({ action }, extra || {})));
  }

  // ---------------------------------------------------------------- lobby

  async function loadTopicPicker() {
    try {
      const res = await fetch("/api/categories");
      const data = await res.json();
      const wrap = $("topicPicker");
      wrap.innerHTML = "";
      data.categories.forEach((cat) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "topic-chip-toggle";
        btn.textContent = cat;
        btn.addEventListener("click", () => toggleTopic(cat, btn));
        wrap.appendChild(btn);
      });
    } catch (e) {
      toast("ماقدرناش نجيبو لائحة المواضيع");
    }
  }

  function requiredTopicCount() {
    return selectedRoundCount === 3 ? 1 : 2;
  }

  function toggleTopic(cat, btn) {
    const need = requiredTopicCount();
    const idx = selectedTopics.indexOf(cat);
    if (idx !== -1) {
      selectedTopics.splice(idx, 1);
      btn.classList.remove("selected");
    } else {
      if (selectedTopics.length >= need) return;
      selectedTopics.push(cat);
      btn.classList.add("selected");
    }
    document.querySelectorAll(".topic-chip-toggle").forEach((b) => {
      if (!b.classList.contains("selected")) b.disabled = selectedTopics.length >= need;
    });
    updateJoinButton();
  }

  $("roundsRow").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    [...$("roundsRow").children].forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    selectedRoundCount = parseInt(btn.dataset.r, 10);

    const need = requiredTopicCount();
    // trim excess picks if switching to a format that needs fewer topics
    while (selectedTopics.length > need) selectedTopics.pop();
    document.querySelectorAll(".topic-chip-toggle").forEach((b) => {
      b.classList.toggle("selected", selectedTopics.includes(b.textContent));
      b.disabled = !b.classList.contains("selected") && selectedTopics.length >= need;
    });
    $("topicPickerLabel").textContent = need === 1 ? "اختار الموضوع اللي بغيتي تناقش فيه" : "اختار موضوعين اللي بغيتي تناقش فيهم";
    $("topicPickerHint").textContent =
      need === 1
        ? 'غادي نلقاو ليك خصم اختار موضوع مختلف على ديالك تماما.'
        : "غادي نلقاو ليك خصم اختار مواضيع مختلفة على ديالك تماما — هكاك كل واحد كيدافع على شي حاجة تهمو.";
    updateJoinButton();
  });

  function updateJoinButton() {
    const name = $("myName").value.trim();
    $("joinLobbyBtn").disabled = !(name.length > 0 && selectedTopics.length === requiredTopicCount());
  }
  $("myName").addEventListener("input", updateJoinButton);

  $("joinLobbyBtn").addEventListener("click", () => {
    const name = $("myName").value.trim();
    if (!name || selectedTopics.length !== requiredTopicCount()) return;
    $("setupError").hidden = true;

    lobbyWs = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/lobby`);
    lobbyWs.onopen = () => {
      lobbyWs.send(JSON.stringify({ action: "join", name, topics: selectedTopics, round_count: selectedRoundCount }));
    };
    lobbyWs.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === "waiting") {
        $("pickedTopicsView").innerHTML = selectedTopics.map((t) => `<span>${t}</span>`).join("");
        showScreen("screen-waiting");
      } else if (msg.type === "matched") {
        gameId = msg.game_id;
        mySlot = msg.slot;
        if (lobbyWs) {
          lobbyWs.close();
          lobbyWs = null;
        }
        connectGame();
      } else if (msg.type === "error") {
        $("setupError").textContent = msg.message;
        $("setupError").hidden = false;
      }
    };
    lobbyWs.onclose = () => {
      lobbyWs = null;
    };
  });

  $("cancelWaitBtn").addEventListener("click", () => {
    if (lobbyWs && lobbyWs.readyState === WebSocket.OPEN) {
      lobbyWs.send(JSON.stringify({ action: "cancel" }));
      lobbyWs.close();
    }
    lobbyWs = null;
    showScreen("screen-lobby");
  });

  // ------------------------------------------------------------ game ws

  function connectGame() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    gameWs = new WebSocket(`${proto}//${location.host}/ws/${gameId}?slot=${mySlot}`);
    gameWs.onopen = () => {
      showScreen("screen-game");
      // Mics come up right away for the pre-round green room — the actual
      // round only starts once both sides confirm ready (see set_ready).
      setupVoice();
    };
    gameWs.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === "state") {
        state = msg;
        render();
      } else if (msg.type === "rtc_signal") {
        handleSignal(msg.payload);
      } else if (msg.type === "peer_status") {
        if (msg.present) {
          peerPresent = true;
          maybeInitiateOffer();
        }
      } else if (msg.type === "reaction") {
        spawnReaction(msg.slot, msg.emoji);
      } else if (msg.type === "audience_joined") {
        if (mySlot === "player1") {
          pendingAudienceJoins.push(msg.audience_id);
          flushPendingAudienceJoins();
        }
      } else if (msg.type === "audience_left") {
        const p = audiencePeers[msg.audience_id];
        if (p) {
          p.close();
          delete audiencePeers[msg.audience_id];
        }
      } else if (msg.type === "audience_signal") {
        handlePlayerSideAudienceSignal(msg.audience_id, msg.payload);
      } else if (msg.type === "rematch_ready") {
        toast("بدات مناظرة جديدة بينكم — كتبدا دابا...");
        gameId = msg.game_id;
        resetForNewGame();
        gameWs.close();
        connectGame();
      } else if (msg.type === "error") {
        toast(msg.message);
      }
    };
    gameWs.onclose = () => {
      if (!$("screen-game").hidden) toast("انقطع الاتصال بالخادم");
    };
  }

  function connectAudience() {
    showScreen("screen-game");
    $("audienceBadge").hidden = false;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    gameWs = new WebSocket(`${proto}//${location.host}/ws/${gameId}/watch`);
    gameWs.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === "state") {
        state = msg;
        render();
      } else if (msg.type === "your_audience_id") {
        audienceId = msg.id;
      } else if (msg.type === "audience_signal") {
        handleAudienceSignal(msg.payload);
      } else if (msg.type === "reaction") {
        spawnReaction(msg.slot, msg.emoji);
      } else if (msg.type === "rematch_ready") {
        toast("بدات مناظرة جديدة، كتفرج عليها دابا...");
        gameId = msg.game_id;
        resetForNewGame();
        gameWs.close();
        connectAudience();
      } else if (msg.type === "error") {
        toast(msg.message);
      }
    };
    gameWs.onclose = () => {
      if (!$("screen-game").hidden) toast("انقطع الاتصال بالخادم");
    };
  }

  // Shared cleanup before swapping to a rematch's fresh game id — tears
  // down every WebRTC connection and per-game UI flag so the new game
  // starts from a clean slate instead of carrying over stale state.
  function resetForNewGame() {
    teardownVoice();
    teardownAudiencePc();
    Object.values(audiencePeers).forEach((p) => p.close());
    for (const k in audiencePeers) delete audiencePeers[k];
    audienceMixStream = null;
    remoteStream = null;
    pendingAudienceJoins = [];
    if (audienceAudioCtx) {
      audienceAudioCtx.close();
      audienceAudioCtx = null;
    }
    offerSent = false;
    peerPresent = false;
    pendingSignals = [];
    hasVoted = false;
    rematchTopics = [];
    const picker = $("rematchTopicPicker");
    picker.innerHTML = "";
    delete picker.dataset.built;
    delete picker.dataset.building;
    $("voiceStatus").classList.remove("live", "muted");
    $("voiceStatusText").textContent = "كنوصلو الصوت...";
  }

  // --------------------------------------------------------------- voice

  let peerPresent = false;
  let offerSent = false;
  let pendingSignals = [];

  async function setupVoice() {
    const chip = $("voiceStatus");
    try {
      localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
      $("voiceStatusText").textContent = "الميكرو ماشي متاح";
      chip.classList.add("muted");
      return;
    }

    pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    localStream.getTracks().forEach((t) => {
      t.enabled = false; // stays muted until it's actually my turn
      pc.addTrack(t, localStream);
    });

    pc.ontrack = (e) => {
      const audioEl = $("remoteAudio");
      audioEl.srcObject = e.streams[0];
      audioEl.hidden = false;
      remoteStream = e.streams[0];
      if (mySlot === "player1") flushPendingAudienceJoins();
    };
    pc.onicecandidate = (e) => {
      if (e.candidate) sendGame("rtc_signal", { payload: { candidate: e.candidate } });
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") {
        $("voiceStatusText").textContent = "الصوت متصل";
        chip.classList.add("live");
      }
    };

    // Real microphone permission prompts take an unpredictable amount of
    // time on each side (unlike a scripted test), so we can't assume the
    // other player's connection — or even their RTCPeerConnection object —
    // exists yet. Only fire the offer once the server confirms both sides
    // are actually connected, and drain any signal that arrived before
    // this peer connection existed.
    maybeInitiateOffer();
    while (pendingSignals.length) {
      await handleSignal(pendingSignals.shift());
    }
  }

  function maybeInitiateOffer() {
    if (mySlot !== "player1" || offerSent || !pc || !peerPresent) return;
    offerSent = true;
    (async () => {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      sendGame("rtc_signal", { payload: { sdp: pc.localDescription } });
    })();
  }

  async function handleSignal(payload) {
    if (!payload) return;
    if (!pc) {
      pendingSignals.push(payload);
      return;
    }
    try {
      if (payload.sdp) {
        await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
        if (payload.sdp.type === "offer") {
          const answer = await pc.createAnswer();
          await pc.setLocalDescription(answer);
          sendGame("rtc_signal", { payload: { sdp: pc.localDescription } });
        }
      } else if (payload.candidate) {
        await pc.addIceCandidate(new RTCIceCandidate(payload.candidate));
      }
    } catch (e) {
      /* ICE races on renegotiation are normal, ignore */
    }
  }

  function updateMic() {
    if (!localStream || !state) return;
    // Both mics stay open in the pre-round green room, while someone's
    // choosing the second question (nothing timed to gate yet), and during
    // any card interruption — the interrupter needs to ask and the
    // interrupted player needs to be able to reply. Otherwise it's strict
    // turn-based: only whoever's turn it is can be heard.
    const openFloor = state.status === "setup" || state.status === "choosing_second" || !!state.interruption;
    const canTalk = openFloor || (state.running && state.active_slot === mySlot);
    localStream.getAudioTracks().forEach((t) => (t.enabled = canTalk));
  }

  function teardownVoice() {
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
      localStream = null;
    }
    if (pc) {
      pc.close();
      pc = null;
    }
  }

  // ------------------------------------------------- audience audio (mesh)

  // Rather than run a full SFU, player1 mixes both debaters' tracks locally
  // via Web Audio and broadcasts that single mixed stream out to every
  // spectator over its own receive-only RTCPeerConnection. A muted debater
  // track outputs silence into the mix too, so the "only hear whoever's
  // turn it is" rule the debaters already get applies to the audience
  // automatically — no extra gating needed here.
  function ensureAudienceMix() {
    if (audienceMixStream) return audienceMixStream;
    if (!localStream || !remoteStream) return null;
    audienceAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    audienceAudioCtx.resume().catch(() => {}); // browsers may start it suspended
    const dest = audienceAudioCtx.createMediaStreamDestination();
    audienceAudioCtx.createMediaStreamSource(localStream).connect(dest);
    audienceAudioCtx.createMediaStreamSource(remoteStream).connect(dest);
    audienceMixStream = dest.stream;
    return audienceMixStream;
  }

  function flushPendingAudienceJoins() {
    if (mySlot !== "player1" || !pendingAudienceJoins.length) return;
    if (!ensureAudienceMix()) return; // not ready yet — stays queued
    const queued = pendingAudienceJoins;
    pendingAudienceJoins = [];
    queued.forEach(createAudiencePeer);
  }

  function createAudiencePeer(aid) {
    const mix = ensureAudienceMix();
    if (!mix) {
      pendingAudienceJoins.push(aid);
      return;
    }
    const apc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    mix.getTracks().forEach((t) => apc.addTrack(t, mix));
    apc.onicecandidate = (e) => {
      if (e.candidate) sendGame("audience_signal", { audience_id: aid, payload: { candidate: e.candidate } });
    };
    audiencePeers[aid] = apc;
    (async () => {
      const offer = await apc.createOffer();
      await apc.setLocalDescription(offer);
      sendGame("audience_signal", { audience_id: aid, payload: { sdp: apc.localDescription } });
    })();
  }

  async function handlePlayerSideAudienceSignal(aid, payload) {
    const apc = audiencePeers[aid];
    if (!apc || !payload) return;
    try {
      if (payload.sdp) {
        await apc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
      } else if (payload.candidate) {
        await apc.addIceCandidate(new RTCIceCandidate(payload.candidate));
      }
    } catch (e) {
      /* ICE races are normal, ignore */
    }
  }

  function handleAudienceSignal(payload) {
    if (!payload) return;
    if (!audiencePc) {
      audiencePc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      audiencePc.ontrack = (e) => {
        const audioEl = $("remoteAudio");
        audioEl.srcObject = e.streams[0];
        audioEl.hidden = false;
      };
      audiencePc.onicecandidate = (e) => {
        if (e.candidate) sendGame("audience_signal", { payload: { candidate: e.candidate } });
      };
      audiencePc.onconnectionstatechange = () => {
        if (audiencePc.connectionState === "connected") {
          $("voiceStatusText").textContent = "الصوت متصل";
          $("voiceStatus").classList.add("live");
        }
      };
    }
    (async () => {
      try {
        if (payload.sdp) {
          await audiencePc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
          if (payload.sdp.type === "offer") {
            const answer = await audiencePc.createAnswer();
            await audiencePc.setLocalDescription(answer);
            sendGame("audience_signal", { payload: { sdp: audiencePc.localDescription } });
          }
        } else if (payload.candidate) {
          await audiencePc.addIceCandidate(new RTCIceCandidate(payload.candidate));
        }
      } catch (e) {
        /* ICE races are normal, ignore */
      }
    })();
  }

  function teardownAudiencePc() {
    if (audiencePc) {
      audiencePc.close();
      audiencePc = null;
    }
  }

  // ------------------------------------------------------------- actions

  $("startPauseBtn").addEventListener("click", () => {
    if (!state) return;
    sendGame("set_running", { running: !state.running });
  });
  $("skipBtn").addEventListener("click", () => sendGame("skip_phase"));
  $("resetTimerBtn").addEventListener("click", () => sendGame("request_action", { kind: "reset_timer" }));
  $("approveRequestBtn").addEventListener("click", () => sendGame("resolve_request", { approve: true }));
  $("rejectRequestBtn").addEventListener("click", () => sendGame("resolve_request", { approve: false }));
  $("cancelRequestBtn").addEventListener("click", () => sendGame("cancel_request"));
  $("nextRoundBtn").addEventListener("click", () => sendGame("next_round"));
  $("showFinalBtn").addEventListener("click", () => sendGame("next_round"));
  $("interruptResume").addEventListener("click", () => sendGame("resolve_interruption"));

  $("submitCustomBtn").addEventListener("click", () => {
    const input = $("customQuestionInput");
    const text = input.value.trim();
    if (!text) return;
    sendGame("write_second_topic", { text });
    input.value = "";
  });

  $("readyBtn").addEventListener("click", () => {
    sendGame("set_ready", { ready: true });
    $("readyBtn").disabled = true;
    $("readyBtn").textContent = "كنستناو الخصم...";
  });

  $("settingsBtn").addEventListener("click", () => ($("settingsOverlay").hidden = false));
  $("closeSettings").addEventListener("click", () => ($("settingsOverlay").hidden = true));
  $("leaveBtn").addEventListener("click", () => ($("leaveOverlay").hidden = false));
  $("cancelLeave").addEventListener("click", () => ($("leaveOverlay").hidden = true));
  // Reloading /watch/{id} just re-joins the same audience — send spectators
  // back to the homepage instead, and only reload (rejoin the lobby) for debaters.
  $("confirmLeave").addEventListener("click", () => (isAudience ? (location.href = "/") : location.reload()));
  $("replayBtn").addEventListener("click", () => (isAudience ? (location.href = "/") : location.reload()));

  $("shareBtn").addEventListener("click", () => {
    $("shareLinkInput").value = `${location.origin}/watch/${gameId}`;
    $("shareOverlay").hidden = false;
  });
  $("closeShare").addEventListener("click", () => ($("shareOverlay").hidden = true));
  $("copyShareLinkBtn").addEventListener("click", async () => {
    const input = $("shareLinkInput");
    input.select();
    try {
      await navigator.clipboard.writeText(input.value);
    } catch (e) {
      document.execCommand("copy");
    }
    toast("تنسخ الرابط!");
  });

  window.addEventListener("beforeunload", () => {
    teardownVoice();
    teardownAudiencePc();
    Object.values(audiencePeers).forEach((p) => p.close());
  });

  // ----------------------------------------------------------- reactions

  const REACTION_COOLDOWN_MS = 2500;
  let reactionCooldownUntil = 0;

  function setReactionButtonsDisabled(disabled) {
    document.querySelectorAll(".reaction-btn").forEach((b) => (b.disabled = disabled));
  }

  document.querySelectorAll(".reaction-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (Date.now() < reactionCooldownUntil) return; // client-side guard; server enforces it for real
      sendGame("send_reaction", { emoji: btn.dataset.emoji });
      spawnReaction(mySlot, btn.dataset.emoji); // instant local feedback, don't wait on the round trip
      reactionCooldownUntil = Date.now() + REACTION_COOLDOWN_MS;
      setReactionButtonsDisabled(true);
      setTimeout(() => setReactionButtonsDisabled(false), REACTION_COOLDOWN_MS);
    });
  });

  function spawnReaction(slot, emoji) {
    const zone = $(slot === "player1" ? "reactionZoneA" : "reactionZoneB");
    if (!zone) return;
    const span = document.createElement("span");
    span.className = "reaction-float";
    span.textContent = emoji;
    zone.appendChild(span);
    setTimeout(() => span.remove(), 1700);
  }

  // -------------------------------------------------------------- cards

  function canPlay(slot, card) {
    if (!state || state.status !== "active") return false;
    if (slot !== mySlot) return false; // server also enforces this
    const player = state[slot];
    if (player.cards_used[card]) return false;
    if (!state.current_topic) return false;
    const opponent = slot === "player1" ? "player2" : "player1";
    if (card === "extra_minute" || card === "yield_turn") {
      return state.active_slot === slot && state.running;
    }
    return state.active_slot === opponent && state.running && !state.interruption;
  }

  const cardButtons = { cardsA: {}, cardsB: {} };

  function renderCards(slot, containerId) {
    const el = $(containerId);
    const cache = cardButtons[containerId];

    // Build each button once and keep reusing the same DOM node afterward —
    // recreating them every render (which happens every second while a
    // timer runs) would cut the "just played" animation off mid-flight.
    if (!el.dataset.built) {
      CARD_ORDER.forEach((card) => {
        const meta = CARD_META[card];
        const btn = document.createElement("button");
        btn.className = "card-tile " + meta.cls;
        btn.title = meta.title;
        btn.innerHTML = meta.icon + "<span>" + meta.label + "</span>";
        btn.addEventListener("click", () => sendGame("play_card", { slot, card }));
        el.appendChild(btn);
        cache[card] = btn;
      });
      el.dataset.built = "1";
    }

    CARD_ORDER.forEach((card) => {
      const btn = cache[card];
      const used = state[slot].cards_used[card];
      btn.disabled = used || !canPlay(slot, card);
      if (used && !btn.classList.contains("card-used")) {
        btn.classList.add("card-used", "card-play-pop");
        btn.addEventListener("animationend", () => btn.classList.remove("card-play-pop"), { once: true });
      }
    });
  }

  // -------------------------------------------------------------- render

  function personalCap(phase) {
    if (phase === "closing") return 120;
    if (phase === "discussion") return 300;
    return 60;
  }

  function render() {
    if (!state) return;

    $("nameA").textContent = state.player1.name;
    $("nameB").textContent = state.player2.name;
    $("statusA").lastChild.textContent = isAudience ? "متناظر" : mySlot === "player1" ? "أنت" : "الخصم";
    $("statusB").lastChild.textContent = isAudience ? "متناظر" : mySlot === "player2" ? "أنت" : "الخصم";

    const currentIdx = PHASE_ORDER.indexOf(state.phase);
    document.querySelectorAll("#stepper .step").forEach((stepEl) => {
      const idx = PHASE_ORDER.indexOf(stepEl.dataset.phase);
      stepEl.classList.toggle("done", idx < currentIdx || state.status === "finished");
      stepEl.classList.toggle("now", idx === currentIdx && state.status !== "finished");
    });

    if (state.current_topic) {
      $("topicCategory").textContent = state.current_topic.category;
      $("topicQuestion").textContent = state.current_topic.question;
    } else {
      $("topicCategory").textContent = "الفئة";
      $("topicQuestion").textContent = "راه كيتحضر السؤال...";
    }

    if (state.second_topic) {
      $("secondTopicCard").hidden = false;
      $("secondTopicQuestion").textContent = state.second_topic.question;
    } else {
      $("secondTopicCard").hidden = true;
    }

    renderChoosingSecond();
    renderPreRound();

    setRing("ringA", "timeA", state.player1.personal_remaining, personalCap(state.phase), "var(--green)");
    setRing("ringB", "timeB", state.player2.personal_remaining, personalCap(state.phase), "var(--red)");

    $("phaseBannerText").textContent = PHASE_LABEL[state.phase] || "";
    const activePlayer = state[state.active_slot];
    const activeColor = state.active_slot === "player1" ? "var(--green)" : "var(--red)";
    setRing("ringMain", "timeMain", activePlayer.personal_remaining, personalCap(state.phase), activeColor);

    const aActive = state.active_slot === "player1";
    const micA = $("micA"), micB = $("micB");
    micA.className = "mic-tag " + (aActive ? "active-a" : "muted");
    micA.querySelector("span").textContent = aActive ? "يتكلم الآن" : "في الانتظار";
    micB.className = "mic-tag " + (!aActive ? "active-b" : "muted");
    micB.querySelector("span").textContent = !aActive ? "يتكلم الآن" : "في الانتظار";

    const mainRemaining = activePlayer.personal_remaining;
    $("urgentBar").hidden = !(state.running && mainRemaining > 0 && mainRemaining <= 30);
    $("urgentSeconds").textContent = mainRemaining;

    $("startPauseBtn").textContent = state.running ? "وقف" : "ابدأ";
    $("startPauseBtn").disabled = state.status !== "active";
    // You can only end YOUR OWN turn early — ending the opponent's turn for
    // them isn't yours to do (server enforces this too).
    $("skipBtn").hidden = state.active_slot !== mySlot;

    renderPendingRequest();

    renderCards("player1", "cardsA");
    renderCards("player2", "cardsB");
    $("cardsLeftA").textContent = Object.values(state.player1.cards_used).filter((u) => !u).length + "/5";
    $("cardsLeftB").textContent = Object.values(state.player2.cards_used).filter((u) => !u).length + "/5";

    const roundResult = $("roundResult");
    if (state.status === "round_end") {
      roundResult.hidden = false;
      const isLast = state.round_no >= state.total_rounds;
      $("roundResultText").textContent = isLast ? "خلصات آخر جولة!" : `خلصات الجولة ${state.round_no}`;
      $("nextRoundBtn").hidden = isLast;
      $("showFinalBtn").hidden = !isLast;
    } else {
      roundResult.hidden = true;
    }

    if (state.interruption) {
      const i = state.interruption;
      const fromName = state[i.from_slot].name;
      const targetName = state[i.target_slot].name;
      const titles = { direct_question: "سؤال مباشر!", interrupt: "طلب توضيح!" };
      $("interruptFrom").textContent = "استجواب من " + fromName;
      $("interruptTitle").textContent = titles[i.card_type] || "استجواب";
      $("interruptTarget").textContent = targetName + "، عندك وقت باش تجاوب";
      $("interruptTime").textContent = fmt(i.remaining);
      $("interruptOverlay").hidden = false;
    } else {
      $("interruptOverlay").hidden = true;
    }

    if (state.status === "finished") {
      $("finalNamesLine").textContent = `${state.player1.name} — و — ${state.player2.name}`;
      $("finalOverlay").hidden = false;
      renderFinal();
    } else {
      $("finalOverlay").hidden = true;
    }

    const log = $("logPanel");
    log.innerHTML = "";
    state.log.forEach((line) => {
      const d = document.createElement("div");
      d.textContent = line;
      log.appendChild(d);
    });

    updateMic();
  }

  function renderPreRound() {
    const overlay = $("preRoundOverlay");
    if (state.status !== "setup") {
      overlay.hidden = true;
      return;
    }
    overlay.hidden = false;
    const a = $("preRoundNameA"), b = $("preRoundNameB");
    a.textContent = state.player1.name + (state.player1.ready ? " ✓" : "");
    a.classList.toggle("is-ready", state.player1.ready);
    b.textContent = state.player2.name + (state.player2.ready ? " ✓" : "");
    b.classList.toggle("is-ready", state.player2.ready);

    if (isAudience) return; // no ready button to drive for a spectator (CSS also hides it)

    const iAmReady = state[mySlot].ready;
    $("readyBtn").disabled = iAmReady;
    $("readyBtn").textContent = iAmReady ? "كنستناو الخصم..." : "أنا مستعد، بدا المناظرة";
  }

  function renderChoosingSecond() {
    const overlay = $("chooseSecondOverlay");
    if (state.status !== "choosing_second") {
      overlay.hidden = true;
      return;
    }
    overlay.hidden = false;
    $("chooseTimer").textContent = fmt(state.choosing_deadline);

    const iAmChoosing = state.choosing_slot === mySlot;
    $("chooseAsChooser").hidden = !iAmChoosing;
    $("chooseAsWaiting").hidden = iAmChoosing;

    if (iAmChoosing) {
      const list = $("choiceList");
      list.innerHTML = "";
      state.choosing_candidates.forEach((topic) => {
        const btn = document.createElement("button");
        btn.textContent = topic.question;
        btn.addEventListener("click", () => sendGame("choose_second_topic", { topic_id: topic.id }));
        list.appendChild(btn);
      });
    } else {
      const chooserName = state[state.choosing_slot].name;
      $("chooseWaitingText").textContent = `${chooserName} كيختار ولا كيكتب السؤال الثاني...`;
    }
  }

  function renderPendingRequest() {
    const bar = $("pendingBar");
    const req = state.pending_request;
    const resetBtn = $("resetTimerBtn");

    if (!req) {
      bar.hidden = true;
      // Resetting the clock only makes sense for your own active turn —
      // it's a request to your opponent for more of YOUR time, not theirs.
      resetBtn.hidden = state.active_slot !== mySlot;
      resetBtn.disabled = state.status !== "active";
      return;
    }

    resetBtn.hidden = true;
    bar.hidden = false;
    const iAmRequester = req.requested_by === mySlot;
    const requesterName = state[req.requested_by].name;

    $("pendingText").textContent = iAmRequester
      ? "طلبتي تعاود وقتك — كنستناو موافقة الخصم..."
      : `${requesterName} بغى يعاود وقتو. موافق؟`;
    $("pendingActionsRequester").hidden = !iAmRequester;
    $("pendingActionsResponder").hidden = iAmRequester;
  }

  function renderFinal() {
    const totalVotes = state.vote_player1 + state.vote_player2;
    const votesBlock = $("voteResultsBlock");
    if (totalVotes > 0) {
      votesBlock.hidden = false;
      const pctA = Math.round((state.vote_player1 / totalVotes) * 100);
      const pctB = 100 - pctA;
      $("voteBars").innerHTML = `
        <div class="vote-bar-row">
          <div class="vote-bar-label"><span>${state.player1.name}</span><span>${state.vote_player1} صوت (${pctA}%)</span></div>
          <div class="vote-bar-track"><div class="vote-bar-fill a" style="width:${pctA}%"></div></div>
        </div>
        <div class="vote-bar-row">
          <div class="vote-bar-label"><span>${state.player2.name}</span><span>${state.vote_player2} صوت (${pctB}%)</span></div>
          <div class="vote-bar-track"><div class="vote-bar-fill b" style="width:${pctB}%"></div></div>
        </div>`;
    } else {
      votesBlock.hidden = true;
    }

    const voteSection = $("audienceVoteSection");
    if (isAudience) {
      voteSection.hidden = false;
      $("voteNameA").textContent = state.player1.name;
      $("voteNameB").textContent = state.player2.name;
      $("voteBtnA").hidden = hasVoted;
      $("voteBtnB").hidden = hasVoted;
      $("voteThanksText").hidden = !hasVoted;
    } else {
      voteSection.hidden = true;
    }

    const rematchSection = $("rematchSection");
    if (isAudience) {
      rematchSection.hidden = true;
    } else {
      rematchSection.hidden = false;
      renderRematchPicker();
    }
  }

  $("voteBtnA").addEventListener("click", () => {
    sendGame("cast_vote", { winner: "player1" });
    hasVoted = true;
    renderFinal();
  });
  $("voteBtnB").addEventListener("click", () => {
    sendGame("cast_vote", { winner: "player2" });
    hasVoted = true;
    renderFinal();
  });

  function requiredRematchTopicCount() {
    return state.total_rounds === 3 ? 1 : 2;
  }

  function renderRematchPicker() {
    const already = state.rematch_submitted && state.rematch_submitted[mySlot];
    $("rematchWaitingText").hidden = !already;
    const wrap = $("rematchTopicPicker");
    wrap.hidden = already;
    $("submitRematchBtn").hidden = already;
    if (already) return;

    if (!wrap.dataset.built && !wrap.dataset.building) {
      wrap.dataset.building = "1";
      fetch("/api/categories")
        .then((res) => res.json())
        .then((data) => {
          wrap.innerHTML = "";
          data.categories.forEach((cat) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "topic-chip-toggle";
            btn.textContent = cat;
            btn.addEventListener("click", () => toggleRematchTopic(cat, btn));
            wrap.appendChild(btn);
          });
          wrap.dataset.built = "1";
          delete wrap.dataset.building;
        });
    }
  }

  function toggleRematchTopic(cat, btn) {
    const need = requiredRematchTopicCount();
    const idx = rematchTopics.indexOf(cat);
    if (idx !== -1) {
      rematchTopics.splice(idx, 1);
      btn.classList.remove("selected");
    } else {
      if (rematchTopics.length >= need) return;
      rematchTopics.push(cat);
      btn.classList.add("selected");
    }
    document.querySelectorAll("#rematchTopicPicker .topic-chip-toggle").forEach((b) => {
      if (!b.classList.contains("selected")) b.disabled = rematchTopics.length >= need;
    });
    $("submitRematchBtn").disabled = rematchTopics.length !== need;
  }

  $("submitRematchBtn").addEventListener("click", () => {
    sendGame("submit_rematch_topics", { topics: rematchTopics });
    $("submitRematchBtn").disabled = true;
  });

  function setRing(ringId, timeId, remaining, cap, color) {
    const ring = $(ringId);
    const pct = cap > 0 ? Math.max(0, Math.min(100, (remaining / cap) * 100)) : 0;
    ring.style.setProperty("--pct", pct);
    ring.style.setProperty("--ring-color", color);
    ring.classList.toggle("warn", remaining > 0 && remaining <= 10 && state.running);
    $(timeId).textContent = fmt(remaining);
  }

  (function init() {
    const m = location.pathname.match(/^\/watch\/([^/]+)\/?$/);
    if (m) {
      isAudience = true;
      gameId = m[1];
      mySlot = null;
      document.body.classList.add("audience-view");
      connectAudience();
    } else {
      loadTopicPicker();
    }
  })();
})();
