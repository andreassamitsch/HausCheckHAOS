## 0.1.6 (recovery)
- Restore the 0.1.4 capture, buffering and server behavior (known to work after manually enabling audio).
- Replace 0.1.5 playback changes with a narrow dashboard gesture bridge; initialize output AudioContext during native shortcut tap, use it for remote audio when available.
- Keep native playback and manual audio fallback for unsupported clients. No dashboard card replacement, no change to microphone permissions.

## 0.1.5 (experimental)
- Prefer playback in the same-origin dashboard document after its launch gesture when available.
- Retry initial media playback on track unmute and connection readiness, clear obsolete blocked notices on success.
- Use the existing running Web Audio context for incoming audio if native media playback has not started; keep a manual fallback only for actual browser restrictions.
- Close and remove the temporary playback element on stop or page exit. No change to capture or subscription authentication.

## 0.1.4 (experimental)
- Keep an initialized local Codex broker ready without opening a realtime session; recycle it after each call.
- Cache login status briefly to reduce startup overhead.
- Buffer only first-utterance startup audio locally (12 s max), replay at natural speed, return to live at a verified quiet boundary. If no quiet boundary appears within six seconds of replay, temporarily accelerate the remaining audio by up to 35% to catch up. No disk audio cache.
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
