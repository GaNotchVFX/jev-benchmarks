# LinkedIn post: lane 1 (attach chart_models.png, then chart_cascade.png)

If you use a frontier LLM to classify support tickets, you are probably paying about 46x too much.

I ran 5 models on the same job: sort bank support tickets into 77 intents (Banking77, public test set). Every model got the same label list. No tuning, no examples. Measured from my laptop, using the cost the API actually billed.

Per 1,000 tickets:

GPT-6 Astra: 86.7% accurate, 2.4 s each, $5.70
GPT-5.6 Luna: 85.3%, 1.0 s, $0.12
Claude Sonnet 5: 77.3%, 1.8 s, $1.80
Gemini 3.8 Flash: 76.4%, 1.8 s, $0.70
Jev 1.13: 78.8%, 155 ms, $0.04

Three things I took from it.

1. The small LLM lands within 1.4 points of the frontier model for 2% of the price. That is the first fix, and it has nothing to do with new tech.

2. Jev is TypeSafe's new decision model. It does not write text. It picks an option and tells you how sure it is. On its own it was not accurate enough here, and I am not going to pretend otherwise.

3. The confidence score is the useful part. Jev keeps the 75% of tickets it is sure about, the small LLM takes the rest: 84.0% accurate, $0.08 per 1,000, 629 ms average. Against the frontier model on everything, that is 71x cheaper and 4.5x faster for 2.7 points of accuracy.

Caveats: one dataset, one afternoon, no tuning on any model. Your tickets are not these tickets, so the only number that matters is the one measured on your data.

If you have an LLM bill for classification, routing, guardrails or LLM-as-judge, I will run this on a sample of your real traffic and show you the same three columns: accuracy, latency, cost. DM me.

Code and raw results: https://github.com/GaNotchVFX/jev-benchmarks

#AI #LLM #MachineLearning #CustomerSupport
