# HA Live Voice (experimenteller Prototyp)

Standalone HAOS-App für Live-Audio via Codex-WebRTC und die vorhandene Home-Assistant-Conversation-API. Kein Hermes-Agent, keine separate VM, kein API-Key-Fallback. Die bestehenden Assist-Pipelines werden nicht verändert.

## Einrichtung / Test

1. App bauen/installieren, starten und die Weboberfläche ausschließlich via HA-Ingress öffnen (HTTPS für Mikrofon).
2. In der App mit dem eigenen ChatGPT-Konto per Device-Code anmelden. Keine Schlüssel oder Codes in GitHub speichern.
3. Agent-ID in App-Optionen prüfen (Default: conversation.openai_conversation).
4. Gespräch starten, zunächst eine unverbindliche Temperaturabfrage testen; danach Rückfrage, Unterbrechen und Beenden. Automatisches Ende nach konfigurierbarer Inaktivität (10 s).
5. Erst nach erfolgreichem Test einen separaten Dashboard-Link zur App hinzufügen. Der alte Assist-Button bleibt bestehen.

Die App sendet Aufgaben an /api/conversation/process und nutzt die zurückgegebene conversation_id für Folgefragen. WebRTC-Audio läuft direkt zum Anbieter. Codex läuft als separater eingeschränkter Container-Benutzer ohne Supervisor-Token im Prozess-Environment. Die App verwendet den Supervisor-Token serverseitig für den gewählten HA-Agenten. Ingress ist administrativ vorgesehen; die Zugriffsgrenzen sind auf der Zielinstanz zu testen.

## Status

0.1.0 ist ein nicht freigegebener Prototyp. Noch nicht mit realem HAOS, ChatGPT-Konto, Browser/Ingress oder Codex-WebRTC geprüft. Kein automatischer kostenpflichtiger Fallback. Keine Garantie, dass das Abonnement die experimentelle Schnittstelle unterstützt oder dass keine Planlimits erreicht werden. Keine Umgehung von Kontingenten. Manuelles Unterbrechen implementiert; automatisches Barge-in hängt vom Realtime-Protokoll ab und ist zu verifizieren. Audiozeit wird angezeigt, sofern vom Dienst geliefert. Keine verlässliche Restkontingent-Anzeige.

Upstream: https://github.com/Synero/hermes-live-voice, technische Referenz docs/live-voice-recipe.md, Codex CLI 0.172.0. MIT-Lizenz und Copyright siehe LICENSE/NOTICE.md.

### First-command audio (0.1.4)
Only after an explicit conversation launch, supported browsers buffer microphone audio in memory while connecting. A short quiet boundary switches the stream back to live. With sustained noise/speech, replay temporarily accelerates by up to 35% after six seconds to catch up instead of keeping a permanent delay (pitch may change during that fallback). A startup delay longer than 12 seconds aborts rather than truncating a command. Browser audio worklet/autoplay restrictions may require waiting for connection readiness. A local initialized Codex process is prepared without a realtime session; actual latency and usage need a real-device test.

### Recovery 0.1.7
The experimental first-command audio buffer is disabled. Wait for the green ready indicator before speaking. Audio is transmitted via the original direct WebRTC microphone track.
