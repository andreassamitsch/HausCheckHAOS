## 0.1.4 (experimental)
- Keep an initialized local Codex broker ready without opening a realtime session; recycle it after each call.
- Cache login status briefly to reduce startup overhead.
- Buffer only first-utterance startup audio locally (12 s max), replay at natural speed, return to live at a verified quiet boundary. No disk audio cache.
- Fall back to the existing wait-for-ready behavior if browser audio processing is unavailable.
- Add capture ordering, silence transition, overflow and continuous speech tests.

## 0.1.3 (experimental)
- Dedicated dashboard launch route automatically starts a conversation after status and login checks.
- Microphone transmission and idle countdown start only when WebRTC and data channel are ready.
- Clear ready status, setup duration, optional ready tone and browser audio permission fallback.
- Automatic and manual conversation end return to Family Dashboard after capture stops; errors stay visible.

## 0.1.2 (experimental)
- Voice-only responsive dialogue with speaker-labelled transcript bubbles, status and separate settings.
- Ten-second default idle timeout, protected during speech, remote audio playback and agent requests.
- Close returns to Family Dashboard; ended conversation remains readable until closing or restarting.
- Unit tests for idle and transcript handling.

## 0.1.1 (experimental)
- Add Sonna (German) as selectable/default voice; retain previous voices.
- Pin Codex CLI 0.172.0, whose published V3 voice list includes Sonna.
- Actual live audio and account entitlement remain to be tested.

## 0.1.0 (experimental, unreleased)
- HAOS app scaffold, Codex device login, WebRTC client and broker.
- Delegate to existing Home Assistant conversation agent, retain conversation context.
- Manual interruption, hang-up, inactivity timeout, audio duration.
- Unit tests; real-world login, build, audio and authorization verification pending.
