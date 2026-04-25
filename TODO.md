Necessary
- [ ] Tool Calling
- [x] Record conversations: save full transcript (both sides) to `storage/sessions/<id>_transcript.txt` for every session
- [x] Audio recording: save full audio to `storage/sessions/<id>_audio.wav` for voice sessions
- [ ] Latency logging: log time from end-of-speech to first agent audio chunk per turn to `storage/sessions/<id>_latency.
- [ ] Switch to handle everything as a car accident by default
- [x] Connect UI as WEB ui with live transcripts and visib ility of the state and stages etc 
- [ ] Add date and time to the system prompt
- [ ] Session reconnection: save claim state and re-attach when Gemini hits the 15-min session limit or just runs into an error
- [ ] Retry / graceful shutdown on Twilio WebSocket disconnect mid-call

Nice to have
- [ ] Add functionality that someone who already called within the last 10 mins with the same number can continue his last conversation with a natural pick like "did we lost our connection? No worries lets continue"
- [ ] Add background audio to simulate office background noice
- [ ] Add a jingle in the beginning with the question to press 1 if you have an emergency
- [ ] Add handling of session cancellations

- [ ] Connect to insurance database 

Furthermore
- Remove Twilio phone connection from open points from the plan since it is already done 
- What do you mean by onversation Loop and google live 
- Remove Session Limits & Reconnection as an aspects