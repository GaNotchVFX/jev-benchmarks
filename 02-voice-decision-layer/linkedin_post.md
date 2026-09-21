# LinkedIn post: lane 2 (attach chart_models.png; chart_zig_vs_python.png as the second image or a follow-up post)

Most AI phone agents feel slow for one reason: an LLM is making the small decisions.

A voice agent has about 800 ms from the moment the caller stops talking to the moment it has to start talking. Speech-to-text and text-to-speech take most of that. In the middle, code has to decide four things every turn: what does the caller want, are they done talking or just pausing, do they want a human, how urgent is it.

I measured that decision step on 400 caller turns, half of them cut off mid-sentence.

Time to get all four answers (p50):
Jev 1.13: 149 ms
GPT-5.6 Luna: 1,086 ms
Gemini 3.8 Flash: 1,496 ms
Claude Sonnet 5: 1,868 ms
GPT-6 Astra: 2,555 ms

98% of Jev's turns came back under 300 ms. Out of 1,000 LLM turns, zero did.

Jev is TypeSafe's new decision model. It does not generate text. You send it the transcript and typed questions, and it answers all of them in one call, in parallel, with a confidence on each.

The tradeoff is real: Jev got the intent right 94.5% of the time (after I wrote a one-line description for each option), the LLMs 97.5 to 100%. So you do not throw the LLM away. Jev decides every turn in 150 ms, and when its confidence is low the agent says "one second" and asks the slower model. The slow path runs only when it has to.

I also tested whether rewriting the client in Zig would make it faster. Same 200 requests, Zig vs Python: 152 ms vs 150 ms. No difference. The round trip is the whole cost, and a client rewrite buys you nothing on an API call. Zig belongs next to the audio thread, not in front of an HTTP request.

Caveats: clean text, not real speech-to-text output. Home internet, not a datacenter. One afternoon.

If you are building or running a voice agent and the pauses are killing your calls, I can measure where your milliseconds go and fix the decision layer. DM me.

Code and raw results: [link to repo]

#VoiceAI #AI #LLM #Latency
